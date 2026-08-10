import urllib.parse

from loguru import logger
from playwright.sync_api import Page, TimeoutError as PWTimeout

from src.base_platform import BasePlatform


class IndeedPlatform(BasePlatform):
    name = "Indeed"
    CONFIG_KEY = "indeed"
    BASE = "https://tr.indeed.com"
    HOME_URL = "https://tr.indeed.com"
    LOGIN_URL = "https://secure.indeed.com/account/login?hl=tr"

    # ------------------------------------------------------------------ #
    # Oturum kontrolü
    # ------------------------------------------------------------------ #

    def is_logged_in(self, page: Page) -> bool:
        if "login" in page.url or "signin" in page.url:
            return False
        for sel in [
            # Giriş yapılmış kullanıcıya özel elementler
            "a[href*='/my/jobs']",
            "a[href*='/profile']",
            ".gnav-email-header",
            "[data-gnav-element-name='MyJobs']",
            "[data-gnav-element-name='Resume']",
            ".dd-NavItem-userAvatar",
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
        max_per_run = self.settings.max_per_run

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
            "q": keyword,
            "l": location,
            "iafilter": "1",   # Indeed Apply filtresi
            "sort": "date",
        })
        url = f"{self.BASE}/jobs?{params}"
        logger.info(f"[Indeed] Aranıyor: {keyword!r} @ {location}")

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=20_000)
        except PWTimeout:
            return 0

        self.delay()
        applied = 0

        for _page_num in range(5):
            if applied >= remaining:
                break

            job_links = self._collect_links(page)
            logger.info(f"[Indeed] {len(job_links)} ilan.")

            for link in job_links:
                if applied >= remaining:
                    break
                try:
                    if self._apply(page, link):
                        applied += 1
                except Exception as exc:
                    logger.warning(f"[Indeed] Hata: {exc}")
                self.delay()

            if not self._next_page(page):
                break

        return applied

    def _collect_links(self, page: Page) -> list:
        links = []
        for sel in [
            "a.jcs-JobTitle",
            "h2.jobTitle a",
            "a[data-jk]",
            ".job_seen_beacon a",
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

        title = self._get_text(page, ["h1.jobsearch-JobInfoHeader-title", "h1"])
        company = self._get_text(page, [
            "[data-company-name='true']",
            ".css-1cjkto6",
            ".jobsearch-CompanyReview--heading",
        ])
        description = self._get_text(page, ["#jobDescriptionText", ".jobsearch-jobDescriptionText"])

        if not title:
            return False
        if not self.matcher.is_match(title, description, self.config.min_score):
            self.app_logger.record(self.name, title, company, url, "skipped", "düşük uyum")
            return False
        if self.matcher.is_excluded(title, description):
            self.app_logger.record(self.name, title, company, url, "skipped", "hariç kelime")
            return False

        # Indeed Apply düğmesi (şirket sitesine yönlendirenleri atla)
        apply_btn = None
        for sel in [
            "button#indeedApplyButton",
            "button[class*='indeed-apply']",
            "span.indeed-apply-button",
            "button:has-text('Indeed ile Başvur')",
            "button:has-text('Apply on Indeed')",
        ]:
            try:
                btn = page.query_selector(sel)
                if btn and btn.is_visible():
                    apply_btn = btn
                    break
            except Exception:
                pass

        if not apply_btn:
            self.app_logger.record(self.name, title, company, url, "skipped", "Indeed Apply yok (harici)")
            return False

        if self.dry_run:
            return self.note_dry_run(title, company, url)

        apply_btn.click()
        self.delay(2)

        # Indeed Apply çok adımlı form
        success = self._handle_indeed_form(page)
        status = "applied" if success else "skipped"
        self.app_logger.record(self.name, title, company, url, status)
        return success

    def _handle_indeed_form(self, page: Page) -> bool:
        for _step in range(10):
            self.delay(1)

            # Indeed Apply formu çoğunlukla bir iframe içinde açılır; hem ana
            # sayfayı hem de tüm frame'leri tarayarak alanları dolduruyoruz.
            for scope in self.form_scopes(page):
                self.upload_cv(scope)
                self.fill_scope_fields(scope)

            if self.click_continue_or_submit(page):
                if any(kw in page.url for kw in ["confirmation", "thank", "success", "submitted", "post-apply"]):
                    logger.success("[Indeed] ✓ Başvuru gönderildi.")
                    return True
                continue

            # İlerlenemedi
            logger.warning("[Indeed] Form ilerleyemedi, atlanıyor.")
            return False
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
        for sel in ["a[aria-label='Next Page']", "a[data-testid='pagination-page-next']"]:
            try:
                btn = page.query_selector(sel)
                if btn and btn.is_visible():
                    btn.click()
                    page.wait_for_timeout(2500)
                    return True
            except Exception:
                pass
        return False
