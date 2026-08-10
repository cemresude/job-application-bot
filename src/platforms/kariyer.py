import re

from loguru import logger
from playwright.sync_api import Page, TimeoutError as PWTimeout

from src.base_platform import BasePlatform


class KariyerPlatform(BasePlatform):
    name = "Kariyer.net"
    BASE = "https://www.kariyer.net"
    HOME_URL = "https://www.kariyer.net"
    # Kariyer.net'te ayrı bir giriş SAYFASI yoktur; giriş ana sayfadaki
    # "Giriş Yap" butonuyla açılan bir MODAL'dır. Bu yüzden özel bir LOGIN_URL
    # tanımlamıyoruz (deep giriş adresleri 404 verip "boş sayfa"ya götürüyordu).
    # Manuel giriş ana sayfa üzerinden yapılır ve oturum profile kaydedilir.
    LOGIN_URL = ""

    # ------------------------------------------------------------------ #
    # Oturum kontrolü
    # ------------------------------------------------------------------ #

    def is_logged_in(self, page: Page) -> bool:
        url = page.url
        # Giriş sayfasındaysak kesinlikle değil
        if any(kw in url for kw in ["giris", "login", "signin"]):
            return False

        # Giriş yapılmışken görünen elementler
        for sel in [
            # Kullanıcı menüsü / avatar
            ".c-header__user",
            ".header-user",
            ".user-menu",
            ".member-area",
            ".logged-in",
            # Profilim / Başvurularım linkleri
            "a[href*='basvurularim']",
            "a[href*='profilim']",
            "a[href*='hesabim']",
            # Çıkış yap linki (sadece giriş yapılınca çıkar)
            "a[href*='cikis']",
            "a[href*='logout']",
            "a[href*='signout']",
        ]:
            try:
                el = page.query_selector(sel)
                if el:
                    return True
            except Exception:
                pass

        # "Giriş Yap" butonu hâlâ görünüyorsa giriş yapılmamış
        for sel in [
            "a[href*='giris-yap']:visible",
            "a[href*='login']:visible",
            "button:has-text('Giriş Yap'):visible",
        ]:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    return False
            except Exception:
                pass

        return False

    # ------------------------------------------------------------------ #
    # Arama + başvuru döngüsü
    # ------------------------------------------------------------------ #

    def search_and_apply(self, page: Page) -> int:
        total = 0
        max_per_run = self.config.kariyer.max_per_run
        self._visited_urls: set = set()

        for keyword in self.config.keywords:
            if total >= max_per_run:
                break
            for location in self.config.locations:
                if total >= max_per_run:
                    break
                total += self._search(page, keyword, location, max_per_run - total)

        return total

    def _slug_term(self, text: str) -> str:
        """
        Bir terimi Kariyer.net slug parçasına çevirir:
        'Yazılım Mühendisi' -> 'yazilim+muhendisi'
        (Türkçe-güvenli ASCII, küçük harf, boşluklar '+' ile birleşir.)
        """
        ascii_text = self._norm(text)                  # ör. 'yazilim muhendisi'
        words = re.findall(r"[a-z0-9]+", ascii_text)   # sadece harf/rakam grupları
        return "+".join(words)

    def _first_visible(self, page: Page, selectors: list):
        """Verilen seçicilerden görünür olan İLK elementi döndürür (yoksa None)."""
        for sel in selectors:
            try:
                for el in page.query_selector_all(sel):
                    if el.is_visible():
                        return el
            except Exception:
                pass
        return None

    def _click_first(self, page: Page, selectors: list) -> bool:
        for sel in selectors:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible() and el.is_enabled():
                    el.click()
                    return True
            except Exception:
                pass
        return False

    def _perform_search(self, page: Page, keyword: str, location: str) -> bool:
        """
        Aramayı sayfadaki arama kutusuna YAZARAK yapar (gerçek kullanıcı gibi).

        Neden URL değil: /is-ilanlari/{konum}-{kelime} slug'ı yalnızca
        taksonomideki (bilinen) pozisyonlar için keyword'ü uyguluyor; İngilizce/
        serbest metin ('Machine Learning Engineer' gibi) keyword'leri düşürüp
        geriye sadece konumu bırakıyordu → "tüm Ankara ilanları" dönüyordu.
        Arama kutusu ise backend'de tam-metin araması yaptığı için doğru sonuç verir.
        """
        try:
            page.goto(f"{self.BASE}/is-ilanlari", wait_until="domcontentloaded", timeout=20_000)
        except PWTimeout:
            return False
        page.wait_for_timeout(1500)  # arama formu render olsun

        kw_input = self._first_visible(page, [
            "input[placeholder*='ozisyon' i]",   # 'Pozisyon...'
            "input[placeholder*='anahtar' i]",
            "input[placeholder*='irket' i]",     # '...şirket'
            "input[placeholder*='arıyor' i]",
            "input[name*='keyword' i]",
            "input[name*='search' i]",
            "input[type='search']",
            "form input[type='text']",
        ])
        if not kw_input:
            logger.warning("[Kariyer.net] Arama kutusu bulunamadı.")
            self.screenshot(page, "no_search_box")
            return False

        kw_input.click()
        try:
            kw_input.fill("")
        except Exception:
            pass
        kw_input.type(keyword, delay=50)
        page.wait_for_timeout(900)  # autocomplete açılsın

        # Konum (Remote/Uzaktan hariç) — best-effort, keyword aramasını bozmaz
        loc_slug = self._slug_term(location)
        if loc_slug and loc_slug not in ("remote", "uzaktan"):
            loc_input = self._first_visible(page, [
                "input[placeholder*='ehir' i]",   # 'Şehir'
                "input[placeholder*='onum' i]",   # 'Konum'
                "input[placeholder*='semt' i]",
                "input[name*='location' i]",
                "input[name*='city' i]",
            ])
            if loc_input:
                loc_input.click()
                try:
                    loc_input.fill("")
                except Exception:
                    pass
                loc_input.type(location, delay=50)
                page.wait_for_timeout(1100)
                try:  # açılan öneri listesinden ilkini seç
                    page.keyboard.press("ArrowDown")
                    page.wait_for_timeout(250)
                    page.keyboard.press("Enter")
                except Exception:
                    pass

        # Aramayı gönder: buton varsa tıkla, yoksa Enter
        pre_url = page.url
        if not self._click_first(page, [
            "button:has-text('Ara')",
            "button[type='submit']",
            "form button",
            ".btn-search",
            ".search-btn",
        ]):
            try:
                kw_input.press("Enter")
            except Exception:
                pass

        # Aramanın gerçekten sonuç sayfasına geçmesini bekle (URL değişmeli).
        # Değişmezse arama tetiklenmemiş olabilir → görünürlük için logla.
        for _ in range(12):  # ~6 sn
            page.wait_for_timeout(500)
            if page.url != pre_url:
                break
        logger.info(f"[Kariyer.net] Arama sonuç URL'si: {page.url}")
        return True

    def _search(self, page: Page, keyword: str, location: str, remaining: int) -> int:
        # Aynı aramayı tekrarlama (ör. Remote + Uzaktan → aynı sonuç)
        loc_slug = self._slug_term(location)
        loc_key = "" if loc_slug in ("remote", "uzaktan") else loc_slug
        dedup_key = (self._slug_term(keyword), loc_key)
        if dedup_key in getattr(self, "_visited_urls", set()):
            return 0
        self._visited_urls.add(dedup_key)

        logger.info(f"[Kariyer.net] Aranıyor: {keyword!r} @ {location}")

        if not self._perform_search(page, keyword, location):
            return 0

        applied = 0

        for _page_num in range(5):
            if applied >= remaining:
                break

            # İlanlar AJAX ile SONRADAN yükleniyor. Kartlar DOM'a gelene kadar
            # aktif bekle; beklemeden geçince liste boş görünüp arama sıfır
            # sonuç dönüyordu (asıl sorun buydu).
            if not self._wait_for_results(page):
                logger.info(
                    f"[Kariyer.net] Uygun ilan bulunamadı: {keyword!r} @ {location}"
                )
                break

            links = self._collect_job_links(page)
            logger.info(f"[Kariyer.net] {len(links)} ilan bulundu.")

            for link in links:
                if applied >= remaining:
                    break
                try:
                    if self._apply_to_job(page, link):
                        applied += 1
                except Exception as exc:
                    logger.warning(f"[Kariyer.net] Hata: {exc}")
                self.delay()

            if not self._next_page(page):
                break

        return applied

    def _wait_for_results(self, page: Page, timeout_ms: int = 20_000) -> bool:
        """
        İlan sonuçlarının yüklenmesini bekler.

        Kariyer.net sonuç listesini JavaScript (AJAX) ile sonradan bastığı için
        sabit bir bekleme yeterli değil; kartlar DOM'a GELENE kadar ya da gerçek
        'sonuç bulunamadı' ekranı belirene kadar aktif olarak yoklar.

        Dönüş: ilan varsa True, sonuç boşsa/süre dolduysa False.
        """
        step_ms = 400
        waited = 0
        while waited < timeout_ms:
            # Kartlar geldiyse hemen başarı
            if self._collect_job_links(page):
                return True
            # Gerçekten 'sonuç yok' ekranı çıktıysa boşuna bekleme
            if self._results_empty(page):
                return False
            page.wait_for_timeout(step_ms)
            waited += step_ms
        # Son bir deneme (süre dolarken kartlar gelmiş olabilir)
        return bool(self._collect_job_links(page))

    def _results_empty(self, page: Page) -> bool:
        """Kariyer.net 'sonuç/ilan bulunamadı' boş-durum ekranını yakalar."""
        try:
            body = page.inner_text("body").lower()
        except Exception:
            return False
        # 'bulunamad' negatif sonucun net sinyali (Türkçe küçük harf güvenli).
        return "bulunamad" in body

    def _collect_job_links(self, page: Page) -> list:
        # Kariyer.net ilan DETAY linkleri '/is-ilani/...-{id}' biçimindedir.
        # (Liste/arama sayfası '/is-ilanlari' — dikkat, farklı; eski kodda
        #  aranan '/pozisyon/' Kariyer.net'te yok, bu yüzden 0 link dönüyordu.)
        links = []
        for el in page.query_selector_all("a[href*='/is-ilani/']"):
            href = el.get_attribute("href")
            if not href or "/is-ilani/" not in href:
                continue
            full = href if href.startswith("http") else self.BASE + href
            full = full.split("?")[0].split("#")[0]   # takip parametrelerini at, tekilleştir
            if full not in links:
                links.append(full)
        return links

    def _apply_to_job(self, page: Page, url: str) -> bool:
        if self.app_logger.already_applied(url):
            return False

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=15_000)
        except PWTimeout:
            return False

        # Detay içeriği de JS ile geldiği için başlık DOM'a gelene kadar bekle
        try:
            page.wait_for_selector("h1", timeout=10_000)
        except PWTimeout:
            pass

        self.delay()

        title = self._get_text(page, [
            "h1.job-detail-position-title",
            "h1.position-title",
            "h1",
        ])
        company = self._get_text(page, [
            ".employer-name",
            ".company-name",
            "span.company",
        ])
        description = self._get_text(page, [
            ".job-detail-description",
            ".detail-desc",
            "#jobDescription",
        ])

        if not title:
            return False
        if not self.matcher.is_match(title, description, self.config.min_score):
            self.app_logger.record(self.name, title, company, url, "skipped", "düşük uyum skoru")
            return False
        if self.matcher.is_excluded(title, description):
            self.app_logger.record(self.name, title, company, url, "skipped", "hariç kelime")
            return False

        apply_btn = None
        for sel in [
            "button.apply-btn",
            "a.apply-btn",
            "button:has-text('Başvur')",
            "a:has-text('Başvur')",
            "#applyBtn",
            ".btn-apply",
        ]:
            try:
                btn = page.query_selector(sel)
                if btn and btn.is_visible():
                    apply_btn = btn
                    break
            except Exception:
                pass

        if not apply_btn:
            self.app_logger.record(self.name, title, company, url, "skipped", "Başvur butonu yok")
            return False

        apply_btn.click()
        self.delay(1)
        self._handle_apply_modal(page)
        self.app_logger.record(self.name, title, company, url, "applied")
        return True

    def _handle_apply_modal(self, page: Page):
        page.wait_for_timeout(1500)

        for sel in [
            ".cv-select-item:first-child",
            "input[type='radio']:first-child",
            ".resume-item:first-child",
        ]:
            try:
                item = page.query_selector(sel)
                if item and item.is_visible():
                    item.click()
                    self.delay(0.5)
                    break
            except Exception:
                pass

        for sel in [
            "button:has-text('Başvur')",
            "button:has-text('Onayla')",
            "button:has-text('Gönder')",
            "button[type='submit']",
        ]:
            try:
                btn = page.query_selector(sel)
                if btn and btn.is_visible():
                    btn.click()
                    page.wait_for_timeout(2000)
                    return
            except Exception:
                pass

    def _next_page(self, page: Page) -> bool:
        for sel in [
            "a[rel='next']",
            "a.next-page",
            "button:has-text('Sonraki')",
            "li.next a",
        ]:
            try:
                btn = page.query_selector(sel)
                if btn and btn.is_visible():
                    btn.click()
                    page.wait_for_timeout(2500)
                    return True
            except Exception:
                pass
        return False
