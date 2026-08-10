import urllib.parse

from loguru import logger
from playwright.sync_api import Page, TimeoutError as PWTimeout

from src.base_platform import BasePlatform


class IndeedPlatform(BasePlatform):
    name = "Indeed"
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
        max_per_run = self.config.indeed.max_per_run

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
            for scope in self._form_scopes(page):
                self._upload_cv(scope)
                self._fill_scope_fields(scope)

            if self._click_continue_or_submit(page):
                if any(kw in page.url for kw in ["confirmation", "thank", "success", "submitted", "post-apply"]):
                    logger.success("[Indeed] ✓ Başvuru gönderildi.")
                    return True
                continue

            # İlerlenemedi
            logger.warning("[Indeed] Form ilerleyemedi, atlanıyor.")
            return False
        return False

    def _form_scopes(self, page: Page) -> list:
        """Ana sayfa + Indeed Apply iframe'lerini (varsa) döndürür."""
        scopes = [page]
        try:
            for frame in page.frames:
                if frame != page.main_frame:
                    scopes.append(frame)
        except Exception:
            pass
        return scopes

    def _upload_cv(self, scope):
        cv_path = self.config.get_cv_path(self.config.indeed.language)
        if not cv_path:
            return
        try:
            for inp in scope.query_selector_all("input[type='file']"):
                try:
                    inp.set_input_files(cv_path)
                    scope.wait_for_timeout(1200)
                except Exception:
                    pass
        except Exception:
            pass

    def _fill_scope_fields(self, scope):
        """Bir scope (Page/Frame) içindeki görünür alanları config'e göre doldurur."""
        try:
            fields = scope.query_selector_all(
                "input:visible, select:visible, textarea:visible"
            )
        except Exception:
            return

        for field in fields:
            try:
                tag = field.evaluate("el => el.tagName.toLowerCase()")
                ftype = (field.get_attribute("type") or "").lower()
                if ftype in ("hidden", "file", "submit", "button", "search", "reset"):
                    continue

                label = self.field_label(scope, field)
                val = self.value_for_field(label)

                if tag == "select":
                    self._select_option(field, val, label)
                elif tag == "textarea":
                    cur = field.evaluate("el => el.value") or ""
                    if not cur.strip():
                        field.fill(val or self.default_cover_letter())
                elif ftype == "radio":
                    self._answer_radio(scope, field, label)
                elif ftype == "checkbox":
                    # Onay/izin kutuları (KVKK, şartlar) işaretlenir
                    if any(k in label.lower() for k in ("kvkk", "onay", "kabul", "terms", "consent", "agree", "privacy", "gizlilik")):
                        if not field.is_checked():
                            field.check()
                else:  # text, tel, email, number, url...
                    cur = field.evaluate("el => el.value") or ""
                    if val and not cur.strip():
                        field.fill(val)
            except Exception:
                pass

    def _select_option(self, field, val, label):
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

        low = (label or "").lower()
        if val and pick([str(val).lower()]):
            return
        if any(k in low for k in ("education", "eğitim", "öğrenim", "degree")):
            pick(["lisans", "bachelor", "üniversite", "undergraduate"])
            return
        if any(k in low for k in ("authoriz", "izin", "work permit", "çalışma")):
            pick(["yes", "evet"])
            return
        if any(k in low for k in ("sponsor", "vize", "visa")):
            pick(["no", "hayır"])
            return
        # Genel Evet/Hayır → ilk anlamlı (boş olmayan) seçenek
        for i, txt in enumerate(texts):
            if txt and "seçin" not in txt and "select" not in txt:
                try:
                    field.select_option(index=i)
                except Exception:
                    pass
                return

    def _answer_radio(self, scope, field, label):
        low = (label or "").lower()
        rval = (field.get_attribute("value") or "").lower()
        answers = self.config.form_answers
        if any(k in low for k in ("sponsor", "vize", "visa")):
            if rval in (answers.get("visa_sponsorship", "No").lower(), "no", "hayır"):
                field.check()
            return
        # Diğer evet/hayır sorularında olumlu yanıt
        if rval in ("yes", "evet", "true", "1"):
            field.check()

    def _click_continue_or_submit(self, page: Page) -> bool:
        for scope in self._form_scopes(page):
            for sel in [
                "button:has-text('Submit')",
                "button:has-text('Gönder')",
                "button:has-text('Başvur')",
                "button:has-text('Continue')",
                "button:has-text('Devam')",
                "button[type='submit']",
            ]:
                try:
                    btn = scope.query_selector(sel)
                    if btn and btn.is_visible() and btn.is_enabled():
                        btn.click()
                        page.wait_for_timeout(2000)
                        return True
                except Exception:
                    pass
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
