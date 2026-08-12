import random
import time
from abc import ABC, abstractmethod

from loguru import logger
from playwright.sync_api import Page
from rich.console import Console

from src import browser as br
from src.app_logger import AppLogger
from src.config import Config, PlatformConfig
from src.matcher import JobMatcher, normalize

console = Console()


class BasePlatform(ABC):
    name: str = "base"
    HOME_URL: str = ""
    LOGIN_URL: str = ""  # boşsa HOME_URL kullanılır
    CONFIG_KEY: str = ""  # config.yaml -> platforms.<CONFIG_KEY>

    def __init__(self, config: Config, app_logger: AppLogger, matcher: JobMatcher,
                 dry_run: bool = False):
        self.config = config
        self.app_logger = app_logger
        self.matcher = matcher
        self.dry_run = dry_run
        self._pw = None
        # Başvuru sayacı: alt sınıflar her başarılı başvuruda ANINDA artırır.
        # Yerel bir değişkende toplanıp en sonda döndürülürse, tarama ortasında
        # çıkan bir istisna (ör. net::ERR_CONNECTION_CLOSED) o ana kadarki tüm
        # ilerlemeyi sayaçtan siliyordu — gerçekte başvurular gönderilmiş olsa bile.
        self.applied_count = 0
        # Bu çalıştırmada işlenmiş ilan adresleri. Aynı ilan birden çok arama
        # sonucunda çıkıyor; already_applied() yalnızca GERÇEKTEN başvurulanları
        # yakaladığı için dry-run'da aynı ilan tekrar tekrar raporlanıyordu.
        self.seen_jobs: set = set()

    @property
    def settings(self) -> PlatformConfig:
        """Bu platformun config.yaml ayarları (enabled / max_per_run / language)."""
        return getattr(self.config, self.CONFIG_KEY)

    # ------------------------------------------------------------------ #
    # Alt sınıflar implement eder
    # ------------------------------------------------------------------ #

    @abstractmethod
    def is_logged_in(self, page: Page) -> bool:
        """Oturumun açık olup olmadığını döndürür."""
        ...

    @abstractmethod
    def search_and_apply(self, page: Page) -> int: ...

    # ------------------------------------------------------------------ #
    # Login akışı (override etmeye gerek yok)
    # ------------------------------------------------------------------ #

    def login(self, page: Page):
        """
        Oturumu kalıcı profilden yükle. Zaten giriş yapılmışsa devam et;
        yapılmamışsa giriş sayfasını aç ve kullanıcı MANUEL giriş yapana kadar bekle.

        Otomatik Google/e-posta girişi bilinçli olarak KULLANILMAZ:
        platformlar (özellikle Google) otomatik formu bot olarak yakalayıp
        doğrulamaya takıyordu. Kullanıcı bir kez elle giriş yapar; oturum
        profilde saklandığı için sonraki çalıştırmalarda giriş gerekmez.
        """
        landing = self.HOME_URL or self.LOGIN_URL
        if landing:
            try:
                page.goto(landing, wait_until="domcontentloaded", timeout=20_000)
            except Exception:
                pass
            self._short_delay()

        if self.is_logged_in(page):
            logger.success(f"[{self.name}] Oturum aktif (profilden), giriş atlanıyor.")
            return

        # Girişli değil → varsa özel giriş sayfasına götür, sonra manuel giriş bekle.
        if self.LOGIN_URL:
            try:
                page.goto(self.LOGIN_URL, wait_until="domcontentloaded", timeout=20_000)
            except Exception:
                pass
            self._short_delay()

        self._wait_for_manual_login(page)

    def _wait_for_manual_login(self, page: Page, timeout_seconds: int = 420):
        """
        Tarayıcıda kullanıcı giriş yapana kadar bekler.

        Sayfa OTOMATİK YENİLENMEZ — yenileme, kullanıcı şifre/2FA girerken
        akışı bozup Google doğrulamasında takılmaya yol açıyordu. Sadece
        oturum durumu yoklanır; giriş tamamlandığında sayfa kendisi yönlenir
        ve is_logged_in True döner.
        """
        console.print(
            f"\n[bold yellow]── {self.name}: Manuel Giriş Gerekli ──[/bold yellow]\n"
            f"Açılan tarayıcıda [bold]{self.name}[/bold] hesabına elle giriş yap\n"
            f"(Google, e-posta, QR kod, 2FA — hangisiyse acele etmeden tamamla).\n"
            f"Giriş tespit edilince otomatik devam edecek "
            f"[dim](max {timeout_seconds // 60} dakika)[/dim].\n"
            f"[dim]Bu oturum profile kaydedilir; sonraki çalıştırmalarda tekrar giriş gerekmez.[/dim]\n"
        )
        for _tick in range(timeout_seconds // 2):
            time.sleep(2)
            try:
                if self.is_logged_in(page):
                    logger.success(f"[{self.name}] Giriş tespit edildi, devam ediliyor.")
                    self._short_delay()
                    return
            except Exception:
                pass

        raise TimeoutError(
            f"[{self.name}] {timeout_seconds}s içinde giriş tespit edilemedi. "
            "Platformu atlıyorum."
        )

    # ------------------------------------------------------------------ #
    # Ortak yardımcılar
    # ------------------------------------------------------------------ #

    def safe_goto(self, page: Page, url: str, timeout: int = 20_000) -> bool:
        """
        Sayfaya gider; açılamazsa istisna fırlatmak yerine False döner.

        Sadece PWTimeout yakalamak yetmiyordu: net::ERR_CONNECTION_CLOSED gibi
        ağ hataları Playwright'ta ayrı bir Error sınıfı ve dışarı sızıp TÜM
        taramayı iptal ediyordu — tek bir bağlantı hatası yüzünden kalan
        anahtar kelimeler hiç çalışmıyordu.
        """
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            return True
        except Exception as exc:
            logger.warning(
                f"[{self.name}] Sayfa açılamadı ({type(exc).__name__}), geçiliyor: {url[:90]}"
            )
            return False

    def delay(self, extra: float = 0):
        time.sleep(random.uniform(self.config.min_delay, self.config.max_delay) + extra)

    def _short_delay(self):
        time.sleep(random.uniform(0.8, 1.8))

    def human_type(self, page: Page, selector: str, text: str):
        br.human_type(page, selector, text)

    def screenshot(self, page: Page, tag: str = ""):
        return br.screenshot(page, f"{self.name}_{tag}")

    def _get_text(self, page: Page, selectors: list) -> str:
        for sel in selectors:
            try:
                el = page.query_selector(sel)
                if el:
                    return el.inner_text().strip()
            except Exception:
                pass
        return ""

    def _click_if_visible(self, page: Page, selector: str) -> bool:
        try:
            btn = page.query_selector(selector)
            if btn and btn.is_visible() and btn.is_enabled():
                btn.click()
                page.wait_for_timeout(800)
                return True
        except Exception:
            pass
        return False

    # ------------------------------------------------------------------ #
    # Form yanıtları (tüm platformlar paylaşır)
    # ------------------------------------------------------------------ #

    @staticmethod
    def _norm(s: str) -> str:
        """
        Türkçe-güvenli normalize (matcher.normalize ile aynı kural).
        'İlçe', 'Şehir', 'Yıl' gibi etiketler ASCII anahtar kelimelerle eşleşsin diye.
        """
        return normalize(s)

    def value_for_field(self, label: str):
        """
        Bir form alanının etiketine bakıp config.form_answers'tan uygun yanıtı döndürür.
        Eşleşme yoksa None döner (alan boş bırakılır). İngilizce + Türkçe etiketleri tanır.
        Anahtar kelimeler ASCII-normalize edilmiştir (yıl→yil, şehir→sehir vb.).
        """
        t = self._norm(label)
        a = self.config.form_answers

        def has(*kws) -> bool:
            return any(k in t for k in kws)

        if not t.strip():
            return None

        # Telefon
        if has("phone", "telefon", "mobile", "cep", "gsm"):
            return self.config.phone
        # E-posta
        if has("e-mail", "email", "e-posta", "eposta"):
            return self.config.email

        # Maaş / ücret beklentisi — para birimine göre TL veya USD
        if has("salary", "maas", "ucret", "wage", "compensation", "expected pay", "desired pay"):
            if has("usd", "dollar", "dolar", "$", "euro"):
                return a.get("salary_expectation_usd") or a.get("salary_expectation")
            return a.get("salary_expectation") or a.get("salary_expectation_usd")

        # Profil bağlantıları (URL kontrolü 'name'den ÖNCE — "LinkedIn profile
        # name" gibi etiketler yanlışlıkla ad-soyad olarak doldurulmasın)
        if has("linkedin"):
            return self.config.linkedin_url
        if has("github", "portfolio", "portfoy", "personal website", "kisisel site"):
            return a.get("github_url", "")

        # Mezuniyet (deneyim/yıl kontrolünden ÖNCE — "Graduation year" içinde 'year' geçer)
        if has("graduation", "mezuniyet"):
            return a.get("graduation_year", "")
        # Okul / bölüm
        if has("university", "school", "universite", "okul", "college"):
            return a.get("university", "")
        if has("field of study", "major", "bolum", "program"):
            return a.get("field_of_study", "")

        # Adres bileşenleri (özelden genele sırayla)
        if has("postal", "zip", "posta kodu"):
            return a.get("postal_code", "")
        if has("street", "sokak", "cadde", "address line", "adres satir"):
            return a.get("street_address") or a.get("address")
        if has("district", "ilce", "semt"):
            return a.get("district", "")
        if has("city", "sehir", "town"):
            return a.get("city", "")
        if has("country", "ulke"):
            return a.get("country", "")
        if has("address", "adres"):
            return a.get("address") or a.get("street_address")

        # Deneyim yılı (teknolojiye özel ya da varsayılan)
        if has("year", "yil", "experience", "deneyim"):
            yoe = a.get("years_of_experience", {}) or {}
            for tech, years in yoe.items():
                if tech != "default" and self._norm(tech) in t:
                    return str(years)
            return str(yoe.get("default", "1"))

        # Çalışma izni / vize / taşınma. Bunlar genelde açılır menü ya da radio
        # olur (o yollar select_option/answer_radio'da ele alınır), ama serbest
        # metin olarak sorulduğunda da yanıtsız kalmamalı — boş bırakılan zorunlu
        # alan "İleri" butonunu pasif bırakıp başvuruyu kilitliyor.
        # 'relocat' kontrolü 'available'dan ÖNCE: "Are you available to relocate?"
        if has("relocat", "tasin"):
            return a.get("willing_to_relocate", "Yes")
        if has("sponsor", "vize", "visa"):
            return a.get("visa_sponsorship", "No")
        if has("authoriz", "work permit", "calisma izni", "calismaya yetkili"):
            return a.get("work_authorization", "Yes")

        # Başlangıç tarihi
        if has("start", "baslangic", "available", "musait", "notice"):
            return a.get("earliest_start_date", "Immediately")
        # Not ortalaması
        if has("gpa", "gno", "grade", "not ortalama"):
            return a.get("gpa", "")
        # Ad soyad
        if has("full name", "name", "ad soyad", "isim", "adiniz"):
            return self.config.name

        return None

    def field_label(self, scope, field) -> str:
        """Bir input/select/textarea için görünür etiket metnini bulur (Page veya Frame)."""
        try:
            fid = field.get_attribute("id")
            if fid:
                lab = scope.query_selector(f"label[for='{fid}']")
                if lab:
                    return lab.inner_text()
        except Exception:
            pass
        for attr in ("aria-label", "placeholder", "name", "title"):
            try:
                v = field.get_attribute(attr)
                if v and v.strip():
                    return v
            except Exception:
                pass
        try:
            return field.evaluate(
                "el => (el.closest('label')?.textContent) "
                "|| (el.closest('fieldset, .ia-Questions-item, div, li')?.querySelector('label, legend')?.textContent) "
                "|| ''"
            )
        except Exception:
            return ""

    def default_cover_letter(self) -> str:
        """Platformun CV diline göre ön yazı (LinkedIn/Indeed → EN, Kariyer.net → TR)."""
        if self.settings.language == "english":
            return (
                f"Hi,\n\nI am {self.config.name}, a Software Engineer working on Deep Learning "
                "and Data Science solutions with Python, C++, PyTorch and TensorFlow. My "
                "project experience spans LIDAR-based Computer Vision, Explainable AI (XAI) "
                "and LLM integration, and I have co-authored research published at IEEE/IFIP "
                "NOMS 2026. I believe my background aligns well with this role and I would be "
                "glad to contribute.\n\nBest regards,\n" + self.config.name
            )
        return (
            f"Merhaba,\n\nBen {self.config.name}. Python, C++, PyTorch ve TensorFlow ile derin "
            "öğrenme ve veri bilimi çözümleri geliştiriyorum. LIDAR tabanlı bilgisayarlı görü, "
            "açıklanabilir yapay zeka (XAI) ve LLM entegrasyonu alanlarında uçtan uca proje "
            "deneyimim, IEEE/IFIP NOMS 2026'da yayımlanan bir araştırma makalem var. "
            "Bu pozisyonun profilime çok uygun olduğunu düşünüyor ve katkı sağlamak istiyorum.\n\n"
            "Saygılarımla,\n" + self.config.name
        )

    # ------------------------------------------------------------------ #
    # Dry-run
    # ------------------------------------------------------------------ #

    def already_seen(self, url: str) -> bool:
        """
        İlan bu çalıştırmada daha önce işlendiyse True döner; işlenmediyse
        kaydedip False döner (yani çağıran devam edebilir).
        """
        if url in self.seen_jobs:
            return True
        self.seen_jobs.add(url)
        return False

    def note_dry_run(self, title: str, company: str, url: str) -> bool:
        """
        Dry-run modunda başvuru yapılacak ilanı kaydeder (diske yazılmaz).
        Çağıran akış bunu 'eşleşme' olarak saysın diye her zaman True döner.
        """
        self.app_logger.record(
            self.name, title, company or "", url, "dry_run", "dry-run: başvuru yapılmadı"
        )
        return True

    # ------------------------------------------------------------------ #
    # Genel form doldurma — Indeed ve Glassdoor bunu paylaşır
    # (LinkedIn'in modal'ı kendi özel akışını kullanır)
    # ------------------------------------------------------------------ #

    def form_scopes(self, page: Page) -> list:
        """Ana sayfa + varsa başvuru iframe'leri. Formlar sık sık iframe içinde açılır."""
        scopes = [page]
        try:
            for frame in page.frames:
                if frame != page.main_frame:
                    scopes.append(frame)
        except Exception:
            pass
        return scopes

    def upload_cv(self, scope) -> bool:
        """
        CV'yi ilk uygun dosya alanına yükler.

        Görünürlük KONTROL EDİLMEZ: yükleme inputları neredeyse her zaman
        gizlidir (üstlerinde şık bir buton durur), dolayısıyla is_visible()
        filtrelemek CV yüklemeyi tamamen engellerdi. İlk başarılı yüklemeden
        sonra durulur — CV'yi ön yazı gibi başka bir dosya alanına da
        yüklemek istemiyoruz.
        """
        cv_path = self.config.get_cv_path(self.settings.language)
        if not cv_path:
            return False
        try:
            inputs = scope.query_selector_all("input[type='file']")
        except Exception:
            return False

        for inp in inputs:
            try:
                inp.set_input_files(cv_path)
                scope.wait_for_timeout(1200)
                logger.debug(f"[{self.name}] CV yüklendi.")
                return True
            except Exception:
                pass
        return False

    def fill_scope_fields(self, scope):
        """Bir scope (Page/Frame) içindeki görünür alanları config'e göre doldurur."""
        try:
            fields = scope.query_selector_all("input:visible, select:visible, textarea:visible")
        except Exception:
            return

        for field in fields:
            try:
                tag = field.evaluate("el => el.tagName.toLowerCase()")
                ftype = (field.get_attribute("type") or "").lower()
                if ftype in ("hidden", "file", "submit", "button", "search", "reset"):
                    continue

                label = self.field_label(scope, field) or ""
                val = self.value_for_field(label)

                if tag == "select":
                    self.select_option(field, val, label)
                elif tag == "textarea":
                    cur = field.evaluate("el => el.value") or ""
                    if not cur.strip():
                        field.fill(val or self.default_cover_letter())
                elif ftype == "radio":
                    self.answer_radio(field, label)
                elif ftype == "checkbox":
                    # Onay/izin kutuları (KVKK, şartlar) işaretlenir
                    if any(k in self._norm(label) for k in
                           ("kvkk", "onay", "kabul", "terms", "consent", "agree",
                            "privacy", "gizlilik", "acknowledge")):
                        if not field.is_checked():
                            field.check()
                else:  # text, tel, email, number, url...
                    cur = field.evaluate("el => el.value") or ""
                    if val and not cur.strip():
                        field.fill(val)
            except Exception:
                pass

    def select_option(self, field, val, label):
        """Açılır menüde uygun seçeneği seçer."""
        try:
            options = field.query_selector_all("option")
            texts = [(o.inner_text() or "").strip().lower() for o in options]
        except Exception:
            return

        def pick(keywords) -> bool:
            for kw in keywords:
                for i, txt in enumerate(texts):
                    if kw and kw in txt:
                        try:
                            field.select_option(index=i)
                            return True
                        except Exception:
                            pass
            return False

        low = self._norm(label)
        if val and pick([str(val).lower()]):
            return
        if any(k in low for k in ("education", "egitim", "ogrenim", "degree", "derece")):
            pick(["lisans", "bachelor", "universite", "undergraduate"])
            return
        if any(k in low for k in ("authoriz", "izin", "work permit", "calisma")):
            pick(["yes", "evet"])
            return
        if any(k in low for k in ("sponsor", "vize", "visa")):
            pick(["no", "hayir"])
            return
        # Genel: ilk anlamlı (yer tutucu olmayan) seçenek
        for i, txt in enumerate(texts):
            if txt and "secin" not in self._norm(txt) and "select" not in txt:
                try:
                    field.select_option(index=i)
                except Exception:
                    pass
                return

    def answer_radio(self, field, label):
        low = self._norm(label)
        rval = (field.get_attribute("value") or "").lower()
        answers = self.config.form_answers
        if any(k in low for k in ("sponsor", "vize", "visa")):
            if rval in (answers.get("visa_sponsorship", "No").lower(), "no", "hayır"):
                field.check()
            return
        # Diğer evet/hayır sorularında olumlu yanıt
        if rval in ("yes", "evet", "true", "1"):
            field.check()

    # Öncelik sırası önemli: önce gönderme, sonra ilerleme butonları.
    SUBMIT_SELECTORS = [
        "button:has-text('Submit')",
        "button:has-text('Gönder')",
        "button:has-text('Başvur')",
        "button:has-text('Apply')",
        "button:has-text('Continue')",
        "button:has-text('Devam')",
        "button:has-text('İleri')",
        "button[type='submit']",
    ]

    def click_continue_or_submit(self, page: Page) -> bool:
        """Formdaki bir sonraki adım/gönder butonuna basar (iframe'ler dahil)."""
        for scope in self.form_scopes(page):
            for sel in self.SUBMIT_SELECTORS:
                try:
                    btn = scope.query_selector(sel)
                    if btn and btn.is_visible() and btn.is_enabled():
                        btn.click()
                        page.wait_for_timeout(2000)
                        return True
                except Exception:
                    pass
        return False

    # ------------------------------------------------------------------ #
    # Ana akış
    # ------------------------------------------------------------------ #

    def run(self) -> int:
        self._pw, ctx = br.launch_persistent(
            self.name,
            headless=self.config.headless,
            slow_mo=self.config.slow_mo,
        )
        page = ctx.new_page()
        try:
            self.login(page)
            self.delay()
            self.search_and_apply(page)
        except TimeoutError as exc:
            logger.warning(str(exc))
        except Exception as exc:
            self.screenshot(page, "error")
            logger.error(f"[{self.name}] Beklenmeyen hata: {exc}")
        finally:
            try:
                ctx.close()
            except Exception:
                pass
            try:
                self._pw.stop()
            except Exception:
                pass
        return self.applied_count
