import random
import time
import unicodedata
from abc import ABC, abstractmethod

from loguru import logger
from playwright.sync_api import Page
from rich.console import Console

from src import browser as br
from src.app_logger import AppLogger
from src.config import Config
from src.matcher import JobMatcher

console = Console()


class BasePlatform(ABC):
    name: str = "base"
    HOME_URL: str = ""
    LOGIN_URL: str = ""  # boşsa HOME_URL kullanılır

    def __init__(self, config: Config, app_logger: AppLogger, matcher: JobMatcher):
        self.config = config
        self.app_logger = app_logger
        self.matcher = matcher
        self._pw = None

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
        Türkçe-güvenli normalize: İ/I/ı → i, aksanları kaldırır, küçük harfe çevirir.
        Böylece 'İlçe', 'Şehir', 'Yıl' gibi etiketler ASCII anahtar kelimelerle eşleşir.
        (Python'da 'İ'.lower() birleşik noktalı 'i̇' üretip eşleşmeyi bozuyordu.)
        """
        s = (s or "").replace("İ", "i").replace("I", "i").replace("ı", "i")
        s = unicodedata.normalize("NFKD", s.lower())
        return "".join(c for c in s if not unicodedata.combining(c))

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

        # Mezuniyet (deneyim/yıl kontrolünden ÖNCE — "Graduation year" içinde 'year' geçer)
        if has("graduation", "mezuniyet"):
            return a.get("graduation_year", "")

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
        return (
            f"Merhaba,\n\nBen {self.config.name}. Python, Makine Öğrenmesi, Derin Öğrenme ve "
            "Bilgisayarlı Görü alanlarında deneyimli bir Yazılım Mühendisliği öğrencisiyim. "
            "Bu pozisyonun profilime çok uygun olduğunu düşünüyor ve katkı sağlamak istiyorum.\n\n"
            "Saygılarımla,\n" + self.config.name
        )

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
        applied = 0
        try:
            self.login(page)
            self.delay()
            applied = self.search_and_apply(page)
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
        return applied
