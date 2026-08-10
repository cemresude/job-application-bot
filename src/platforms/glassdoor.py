import urllib.parse

from loguru import logger
from playwright.sync_api import Page, TimeoutError as PWTimeout

from src.base_platform import BasePlatform


class GlassdoorPlatform(BasePlatform):
    name = "Glassdoor"
    BASE = "https://www.glassdoor.com"
    HOME_URL = "https://www.glassdoor.com"
    LOGIN_URL = "https://www.glassdoor.com/profile/login_input.htm"

    # ------------------------------------------------------------------ #
    # Oturum kontrolü — giriş/login akışı BasePlatform tarafından yönetilir
    # (kullanıcı manuel giriş yapar, oturum profilde saklanır).
    # ------------------------------------------------------------------ #

    def is_logged_in(self, page: Page) -> bool:
        url = page.url
        if any(kw in url for kw in ["login", "signin", "auth"]):
            return False
        for sel in [
            "[data-test='site-header-profile']",
            "[data-test='account-menu']",
            "button[aria-label*='profile' i]",
            "a[href*='/member/']",
            "a[href*='logout']",
        ]:
            try:
                el = page.query_selector(sel)
                if el:
                    return True
            except Exception:
                pass
        return False

    def search_and_apply(self, page: Page) -> int:
        total = 0
        max_per_run = self.config.glassdoor.max_per_run

        for keyword in self.config.keywords:
            if total >= max_per_run:
                break
            for location in self.config.locations:
                if total >= max_per_run:
                    break
                total += self._search(page, keyword, location, max_per_run - total)

        return total

    def _search(self, page: Page, keyword: str, location: str, remaining: int) -> int:
        params = urllib.parse.urlencode({
            "keyword": keyword,
            "locKeyword": location,
            "easyApply": "true",
        })
        url = f"{self.BASE}/Job/jobs.htm?{params}"
        logger.info(f"[Glassdoor] Aranıyor: {keyword!r} @ {location}")

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=20_000)
        except PWTimeout:
            return 0

        self.delay()
        applied = 0

        for _page_num in range(4):
            if applied >= remaining:
                break

            links = self._collect_links(page)
            logger.info(f"[Glassdoor] {len(links)} ilan.")

            for link in links:
                if applied >= remaining:
                    break
                try:
                    if self._apply(page, link):
                        applied += 1
                except Exception as exc:
                    logger.warning(f"[Glassdoor] Hata: {exc}")
                self.delay()

            if not self._next_page(page):
                break

        return applied

    def _collect_links(self, page: Page) -> list:
        links = []
        for sel in [
            "a.jobLink",
            "li.react-job-listing a",
            "a[data-test='job-link']",
            ".jobContainer a",
        ]:
            els = page.query_selector_all(sel)
            if els:
                for el in els:
                    href = el.get_attribute("href")
                    if href:
                        full = href if href.startswith("http") else self.BASE + href
                        if full not in links:
                            links.append(full)
                break
        return links

    def _apply(self, page: Page, url: str) -> bool:
        if self.app_logger.already_applied(url):
            return False

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=15_000)
        except PWTimeout:
            return False

        self.delay()

        title = self._get_text(page, [
            "[data-test='job-title']",
            "h1.job-title",
            "h1",
        ])
        company = self._get_text(page, [
            "[data-test='employer-name']",
            ".employer-name",
            "span.EmployerProfile__employerNameAndRatings",
        ])
        description = self._get_text(page, [
            "[data-test='jobDescriptionContent']",
            ".jobDescriptionContent",
            "#JobDescriptionContainer",
        ])

        if not title:
            return False
        if not self.matcher.is_match(title, description, self.config.min_score):
            self.app_logger.record(self.name, title, company, url, "skipped", "düşük uyum")
            return False
        if self.matcher.is_excluded(title, description):
            self.app_logger.record(self.name, title, company, url, "skipped", "hariç kelime")
            return False

        # Easy Apply
        apply_btn = None
        for sel in [
            "button[data-test='easyApplyButton']",
            "button.easy-apply-btn",
            "button:has-text('Easy Apply')",
            "button:has-text('Hızlı Başvur')",
        ]:
            try:
                btn = page.query_selector(sel)
                if btn and btn.is_visible():
                    apply_btn = btn
                    break
            except Exception:
                pass

        if not apply_btn:
            self.app_logger.record(self.name, title, company, url, "skipped", "Easy Apply yok")
            return False

        apply_btn.click()
        self.delay(2)

        # Basit form: birkaç İleri/Gönder adımı
        for _step in range(6):
            self.delay(0.5)
            found = False
            for sel in [
                "button:has-text('Submit')",
                "button:has-text('Apply')",
                "button:has-text('Continue')",
                "button[type='submit']",
            ]:
                try:
                    btn = page.query_selector(sel)
                    if btn and btn.is_visible() and btn.is_enabled():
                        btn.click()
                        page.wait_for_timeout(1500)
                        found = True
                        break
                except Exception:
                    pass

            if any(kw in page.url for kw in ["confirm", "success", "thank"]):
                self.app_logger.record(self.name, title, company, url, "applied")
                return True

            if not found:
                break

        self.app_logger.record(self.name, title, company, url, "skipped", "form tamamlanamadı")
        return False

    def _get_text(self, page: Page, selectors: list) -> str:
        for sel in selectors:
            try:
                el = page.query_selector(sel)
                if el:
                    return el.inner_text().strip()
            except Exception:
                pass
        return ""

    def _next_page(self, page: Page) -> bool:
        for sel in [
            "button[data-test='pagination-next']",
            "li.next a",
            "button:has-text('Next')",
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
