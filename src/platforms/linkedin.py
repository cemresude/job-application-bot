import re
import time
import urllib.parse
from typing import Optional

from loguru import logger
from playwright.sync_api import Page, TimeoutError as PWTimeout

from src.base_platform import BasePlatform


class LinkedInPlatform(BasePlatform):
    name = "LinkedIn"
    CONFIG_KEY = "linkedin"
    BASE = "https://www.linkedin.com"
    HOME_URL = "https://www.linkedin.com/feed/"
    LOGIN_URL = "https://www.linkedin.com/login"

    # Her anahtar kelime TEK arama ile tüm Türkiye için taranır (Ankara +
    # İstanbul + uzaktan hepsi dahil). Böylece aynı kelime lokasyon lokasyon
    # tekrar aranmaz; kelime bitince sıradakine geçilir.
    SEARCH_LOCATION = "Türkiye"
    MAX_PAGES = 10  # bir kelime için taranacak azami sonuç sayfası (güvenlik sınırı)

    # ------------------------------------------------------------------ #
    # Oturum kontrolü
    # ------------------------------------------------------------------ #

    def is_logged_in(self, page: Page) -> bool:
        url = page.url
        if "linkedin.com/feed" in url or "linkedin.com/in/" in url:
            return True
        if "linkedin.com/login" in url or "linkedin.com/checkpoint" in url:
            return False
        # Element kontrolü
        for sel in [
            ".global-nav__me-photo",
            ".nav-item__profile-member-photo",
            "a[href*='/messaging/']",
            ".feed-identity-module",
            "[data-control-name='identity_profile_photo']",
        ]:
            try:
                el = page.query_selector(sel)
                if el:
                    return True
            except Exception:
                pass
        return False

    # ------------------------------------------------------------------ #
    # Arama + başvuru döngüsü
    # ------------------------------------------------------------------ #

    def search_and_apply(self, page: Page) -> int:
        total = 0
        platform_max = self.settings.max_per_run
        keywords = self.config.keywords
        self._seen_jobs: set = set()  # run boyunca aynı ilanı tekrar işleme

        for idx, keyword in enumerate(keywords, 1):
            if total >= platform_max:
                logger.info(f"[LinkedIn] Başvuru hedefine ulaşıldı ({platform_max}), arama bitiriliyor.")
                break
            logger.info(f"[LinkedIn] ═══ Anahtar kelime {idx}/{len(keywords)}: {keyword!r} ═══")
            applied = self._search_keyword(page, keyword, platform_max - total)
            total += applied
            logger.info(
                f"[LinkedIn] {keyword!r} tamamlandı ({applied} başvuru). Sıradaki kelimeye geçiliyor."
            )

        return total

    def _search_keyword(self, page: Page, keyword: str, remaining: int) -> int:
        """Tek anahtar kelimeyi tüm Türkiye için arar ve TÜM sonuç sayfalarını gezer."""
        params = urllib.parse.urlencode({
            "keywords": keyword,
            "location": self.SEARCH_LOCATION,
            "f_AL": "true",   # Easy Apply filtresi
            "sortBy": "DD",   # En yeni
        })
        url = f"{self.BASE}/jobs/search/?{params}"
        logger.info(f"[LinkedIn] Aranıyor: {keyword!r} @ {self.SEARCH_LOCATION}")

        if not self.safe_goto(page, url):
            return 0

        self.delay()
        applied = 0

        for page_num in range(1, self.MAX_PAGES + 1):
            if applied >= remaining:
                break

            cards = self._get_job_cards(page)
            logger.info(f"[LinkedIn] Sayfa {page_num}: {len(cards)} ilan bulundu.")

            for card_idx in range(len(cards)):
                if applied >= remaining:
                    break
                cards = self._get_job_cards(page)
                if card_idx >= len(cards):
                    break

                try:
                    result = self._process_card(page, cards[card_idx])
                    if result:
                        applied += 1
                        self.applied_count += 1
                except Exception as exc:
                    logger.warning(f"[LinkedIn] Kart işlenirken hata: {exc}")
                    self._close_modal(page)

                self.delay()

            if not self._go_next_page(page):
                logger.info(f"[LinkedIn] {keyword!r}: son sayfa ({page_num}), tüm sonuçlar tarandı.")
                break

        return applied

    # Eski düzenin kart seçicileri. LinkedIn yeni arama sayfasında bunların
    # hiçbiri tutmuyor; yine de önce deneniyor, çünkü hesabın hangi düzeni
    # gördüğü değişebiliyor (kademeli dağıtım).
    CARD_SELECTORS = [
        ".jobs-search-results__list-item",
        ".job-card-container",
        "li.scaffold-layout__list-item",
    ]

    def _get_job_cards(self, page: Page) -> list:
        for sel in self.CARD_SELECTORS:
            cards = page.query_selector_all(sel)
            if cards:
                return cards
        return self._find_cards_structurally(page)

    def _find_cards_structurally(self, page: Page) -> list:
        """
        İlan kartlarını sayfa YAPISINDAN bulur.

        LinkedIn yeni iş arama düzeninde sınıf adları karıştırılmış
        ('c7f3f3a7', '_8707df48' gibi), yani sınıf tabanlı hiçbir seçici
        kalıcı olarak çalışmıyor. Onun yerine listeyi kalıbından tanıyoruz:
        aynı ebeveyn altında, her biri anlamlı metin içeren en kalabalık
        <div> kardeş grubu. İlan açıklamasındaki madde listeleri <ul>/<li>
        olduğu için bu kalıba takılmıyor.
        """
        try:
            handle = page.evaluate_handle("""
            () => {
              let best = null;
              for (const parent of document.querySelectorAll('div')) {
                const kids = Array.from(parent.children).filter(k => k.tagName === 'DIV');
                if (kids.length < 5) continue;
                const rich = kids.filter(k => (k.innerText || '').trim().length > 25);
                if (rich.length < 5) continue;
                if (!best || rich.length > best.length) best = rich;
              }
              return best || [];
            }
            """)
            cards = [h.as_element() for h in handle.get_properties().values() if h.as_element()]
            if cards:
                logger.debug(f"[LinkedIn] Kartlar yapısal olarak bulundu: {len(cards)}")
            return cards
        except Exception as exc:
            logger.debug(f"[LinkedIn] Yapısal kart tespiti başarısız: {exc}")
            return []

    def _process_card(self, page: Page, card) -> bool:
        """İlan kartını işler; başvuru yapıldıysa True döner."""
        try:
            card.click()
            page.wait_for_timeout(1500)
        except Exception:
            return False

        title, company = self._job_title_and_company(page)
        job_url = page.url

        if not title:
            return False

        # Bu çalıştırmada bu ilanı daha önce gördük mü? (Farklı anahtar kelimeler
        # aynı ilanı döndürebilir — tekrar işlemeyip zaman kaybını önlüyoruz.)
        m = re.search(r"currentJobId=(\d+)", job_url)
        seen_key = m.group(1) if m else job_url
        seen = getattr(self, "_seen_jobs", None)
        if seen is not None:
            if seen_key in seen:
                logger.debug(f"[LinkedIn] Bu çalıştırmada zaten görüldü: {title}")
                return False
            seen.add(seen_key)

        # Daha önce başvurulmuş mu? (kimlik üzerinden — URL arama kelimesine
        # göre değiştiği için düz URL karşılaştırması yetmiyor)
        job_id = m.group(1) if m else ""
        if self.app_logger.already_applied(job_url) or self.app_logger.already_applied_id(job_id):
            logger.debug(f"[LinkedIn] Zaten başvurulmuş: {title}")
            return False

        description = self._job_description(page)
        if not self.matcher.is_match(title, description, self.config.min_score):
            self.app_logger.record("LinkedIn", title, company or "", job_url, "skipped", "düşük uyum skoru")
            return False

        # Hariç kelime kontrolü
        if self.matcher.is_excluded(title, description):
            self.app_logger.record("LinkedIn", title, company or "", job_url, "skipped", "hariç tutulan kelime")
            return False

        # Easy Apply düğmesini bul
        apply_btn = self._find_apply_button(page)
        if not apply_btn:
            self.app_logger.record("LinkedIn", title, company or "", job_url, "skipped", "Easy Apply yok")
            return False

        if self.dry_run:
            return self.note_dry_run(title, company, job_url)

        apply_btn.click()
        page.wait_for_timeout(2000)

        # Formu doldur ve gönder
        success = self._handle_easy_apply_modal(page, title)
        status = "applied" if success else "skipped"
        note = "" if success else "form doldurulamadı"
        self.app_logger.record("LinkedIn", title, company or "", job_url, status, note)
        return success

    def _job_title_and_company(self, page: Page) -> tuple:
        """
        İlan başlığı ve şirketini döndürür.

        Önce bilinen seçiciler denenir; yeni düzende hepsi ölü olduğu için
        sekme başlığına düşülür — o hâlâ "Başlık | Şirket | LinkedIn" biçiminde
        ve karıştırılmış sınıf adlarından bağımsız olduğu için çok daha sağlam.
        """
        title = self._get_text(page, [
            ".job-details-jobs-unified-top-card__job-title",
            ".jobs-unified-top-card__job-title",
            "h1.t-24",
        ])
        company = self._get_text(page, [
            ".job-details-jobs-unified-top-card__company-name",
            ".jobs-unified-top-card__company-name",
            ".topcard__org-name-link",
        ])
        if title and company:
            return title, company

        try:
            parts = [p.strip() for p in (page.title() or "").split("|")]
        except Exception:
            parts = []
        parts = [p for p in parts if p and p.lower() != "linkedin"]
        if not title and parts:
            title = parts[0]
        if not company and len(parts) > 1:
            company = parts[1]
        return title, company

    def _job_description(self, page: Page) -> str:
        """
        İlan açıklaması. Eski seçiciler yeni düzende tutmadığı için
        "İş ilanı hakkında" / "About the job" başlığından yukarı çıkarak
        yeterince uzun metin içeren kapsayıcıyı buluyoruz.
        """
        desc = self._get_text(page, [
            ".jobs-description__content",
            "#job-details",
            ".jobs-box__html-content",
        ])
        if desc:
            return desc
        try:
            return page.evaluate("""
            () => {
              // Kalıpta Türkçe büyük 'İ' KULLANILMIYOR: JS'te /i/ bayrağı
              // 'İ' ile 'i'yi eşleştirmiyor, bu yüzden 'İş ilanı hakkında'
              // başlığını 'iş...' kalıbıyla aramak sessizce boş dönüyordu.
              const RE = /hakk[ıi]nda|about the job/i;
              const heads = Array.from(document.querySelectorAll('h2, h3'));
              const h = heads.find(e => RE.test(e.innerText || ''));
              if (!h) return '';
              // Başlıktan yukarı çıkarak açıklamayı içeren kapsayıcıyı bul.
              // Üst sınır: sol listedeki diğer ilanları da kapsayacak kadar
              // büyüyüp eşleştirmeyi kirletmesin.
              let el = h.parentElement, best = '';
              for (let i = 0; i < 5 && el; i++) {
                const t = (el.innerText || '').trim();
                if (t.length > 200 && t.length < 12000) best = t;
                if (best && t.length >= 12000) break;
                el = el.parentElement;
              }
              return best;
            }
            """) or ""
        except Exception:
            return ""

    def _find_apply_button(self, page: Page):
        selectors = [
            # Sınıf tabanlı seçici dilden bağımsızdır ama yeni düzende yok.
            "button.jobs-apply-button",
            "button[data-control-name='jobdetails_topcard_inapply']",
            # aria-label: yeni düzende çalışan en sağlam tutamak
            "button[aria-label*='kolay başvuru' i]",
            "button[aria-label*='easy apply' i]",
            # Metin tabanlı (İngilizce + Türkçe arayüz)
            "button:has-text('Easy Apply')",
            "button:has-text('Kolay Başvuru')",
            "button:has-text('Hızlı Başvur')",
        ]
        for sel in selectors:
            try:
                btn = page.query_selector(sel)
                if btn and btn.is_visible():
                    # "Applied / Başvuruldu" durumundaki butonu başvuru sayma
                    label = (btn.inner_text() or "").strip().lower()
                    if any(k in label for k in ("applied", "başvuruldu", "başvurdunuz")):
                        return None
                    return btn
            except Exception:
                pass
        return None

    # ------------------------------------------------------------------ #
    # Easy Apply modal form işleme
    # ------------------------------------------------------------------ #

    # Buton metinleri arayüz diline göre değişir → İngilizce + Türkçe anahtar
    # kelimelerle eşleştiriyoruz (aria-label VEYA görünen metin).
    _SUBMIT_KW = ["submit application", "başvuruyu gönder", "başvuruyu tamamla", "gönder ve"]
    _REVIEW_KW = ["review your application", "review", "gözden geçir", "incele", "değerlendir"]
    _NEXT_KW = ["continue to next", "next", "sonraki", "ileri", "devam"]

    def _handle_easy_apply_modal(self, page: Page, job_title: str) -> bool:
        modal_sel = "div[role='dialog'], .jobs-easy-apply-modal, .artdeco-modal"
        try:
            page.wait_for_selector(modal_sel, timeout=8_000)
        except PWTimeout:
            logger.warning("[LinkedIn] Modal açılmadı.")
            return False

        for step in range(12):  # Maksimum 12 form sayfası
            self.delay(0.5)
            self._fill_current_form_page(page)

            action = self._click_primary_button(page)

            if action == "submitted":
                logger.success(f"[LinkedIn] ✓ Başvuru gönderildi: {job_title}")
                self._dismiss_post_submit(page)
                return True
            if action == "advanced":
                continue

            # Hiçbir buton tıklanamadı (muhtemelen zorunlu alan boş/buton pasif).
            # Taslak olarak KAYDETMEK yerine başvuruyu iptal ediyoruz.
            logger.warning(f"[LinkedIn] Form ilerleyemedi (adım {step+1}), atlanıyor: {job_title}")
            self._discard_application(page)
            return False

        self._discard_application(page)
        return False

    def _click_primary_button(self, page: Page) -> str:
        """
        Modal alt çubuğundaki birincil butonu bulup tıklar.
        Döner: 'submitted' (başvuru gönderildi) | 'advanced' (sonraki adım) | 'none'.
        Dilden bağımsız: aria-label ve görünen metni birlikte kontrol eder.
        """
        buttons = page.query_selector_all(
            "div[role='dialog'] footer button, "
            ".artdeco-modal__actionbar button, "
            ".jobs-easy-apply-modal footer button"
        )
        if not buttons:
            buttons = page.query_selector_all("div[role='dialog'] button")

        def label_of(btn) -> str:
            aria = btn.get_attribute("aria-label") or ""
            try:
                txt = btn.inner_text() or ""
            except Exception:
                txt = ""
            return f"{aria} {txt}".lower()

        def try_click(keywords) -> bool:
            for btn in buttons:
                try:
                    if not (btn.is_visible() and btn.is_enabled()):
                        continue
                    if any(kw in label_of(btn) for kw in keywords):
                        btn.click()
                        page.wait_for_timeout(1500)
                        return True
                except Exception:
                    pass
            return False

        # Öncelik: Gönder > Gözden geçir > Sonraki
        if try_click(self._SUBMIT_KW):
            return "submitted"
        if try_click(self._REVIEW_KW):
            return "advanced"
        if try_click(self._NEXT_KW):
            return "advanced"
        return "none"

    def _dismiss_post_submit(self, page: Page):
        """Başvuru sonrası açılan 'Gönderildi' / 'Done' onay penceresini kapatır."""
        page.wait_for_timeout(1500)
        for sel in [
            "button[aria-label='Dismiss']",
            "button[aria-label='Kapat']",
            "button:has-text('Done')",
            "button:has-text('Bitti')",
            "button:has-text('Tamam')",
            ".artdeco-modal__dismiss",
        ]:
            if self._click_if_visible(page, sel):
                page.wait_for_timeout(600)
                return

    def _discard_application(self, page: Page):
        """
        Yarım kalan başvuruyu TASLAK OLARAK KAYDETMEDEN iptal eder.
        Dismiss (X) → 'Save this application?' diyaloğunda 'Discard/Sil' seçilir.
        """
        for sel in [
            "button[aria-label='Dismiss']",
            "button[aria-label='Kapat']",
            ".artdeco-modal__dismiss",
        ]:
            if self._click_if_visible(page, sel):
                page.wait_for_timeout(800)
                break
        # 'Kaydet mi?' diyaloğu: taslağı SİL (kaydetme)
        for sel in [
            "button[data-control-name='discard_application_confirm_btn']",
            "button:has-text('Discard')",
            "button:has-text('Sil')",
            "button:has-text('İptal')",
        ]:
            if self._click_if_visible(page, sel):
                page.wait_for_timeout(600)
                return

    @staticmethod
    def _looks_placeholder(text: str) -> bool:
        """Bir seçenek metni 'Seçiniz / Select an option' gibi boş yer tutucu mu?"""
        t = BasePlatform._norm(text)
        if not t:
            return True
        return any(k in t for k in ("select", "secin", "seciniz", "choose", "please", "lutfen", "--"))

    def _fill_current_form_page(self, page: Page):
        """
        Modal'daki mevcut form sayfasını doldurur.
        Amaç: HER ZORUNLU alanı yanıtlayıp 'İleri/Gönder' butonunu aktifleştirmek.
        (Yanıtsız bir dropdown/radio, butonu pasif bırakıp başvuruyu kilitliyordu.)
        """
        self.upload_cv(page)
        scope = "div[role='dialog'] "

        # 1) Metin/sayı/tel/e-posta girişleri
        for field in page.query_selector_all(scope + "input:visible"):
            try:
                ftype = (field.get_attribute("type") or "text").lower()
                if ftype in ("hidden", "file", "submit", "button", "checkbox", "radio", "search"):
                    continue
                cur = field.evaluate("el => el.value") or ""
                if cur.strip():
                    continue
                val = self.value_for_field(self._get_field_label(page, field))
                if val:
                    field.fill(val)
            except Exception as exc:
                logger.debug(f"[LinkedIn] input hatası: {exc}")

        # 2) Metin kutuları (ön yazı vb.)
        for ta in page.query_selector_all(scope + "textarea:visible"):
            try:
                cur = ta.evaluate("el => el.value") or ""
                if not cur.strip():
                    val = self.value_for_field(self._get_field_label(page, ta))
                    ta.fill(val or self.default_cover_letter())
            except Exception:
                pass

        # 3) Açılır menüler — her zaman geçerli bir seçenek bırak
        for sel in page.query_selector_all(scope + "select:visible"):
            try:
                self._fill_select(page, sel)
            except Exception as exc:
                logger.debug(f"[LinkedIn] select hatası: {exc}")

        # 4) Onay kutuları (KVKK / şartlar / zorunlu)
        for cb in page.query_selector_all(scope + "input[type='checkbox']:visible"):
            try:
                lbl = self._norm(self._get_field_label(page, cb))
                required = cb.get_attribute("required") is not None
                if required or any(k in lbl for k in
                                   ("agree", "consent", "terms", "kvkk", "onay", "kabul",
                                    "privacy", "gizlilik", "acknowledge", "confirm")):
                    if not cb.is_checked():
                        cb.check()
            except Exception:
                pass

        # 5) Radio grupları — her grup için bir yanıt seç
        self._fill_radio_groups(page, scope)

    def _fill_select(self, page: Page, field):
        options = field.query_selector_all("option")
        if not options:
            return
        low = [(o.inner_text() or "").strip().lower() for o in options]
        values = [(o.get_attribute("value") or "") for o in options]
        label = self._norm(self._get_field_label(page, field))

        def choose(keywords) -> bool:
            for kw in keywords:
                for i, txt in enumerate(low):
                    if kw and kw in txt and not self._looks_placeholder(txt):
                        field.select_option(index=i)
                        return True
            return False

        # Config'ten hedef değer (deneyim yılı, mezuniyet vb.)
        val = self.value_for_field(self._get_field_label(page, field))
        if val and choose([str(val).lower()]):
            return
        if any(k in label for k in ("education", "egitim", "ogrenim", "degree", "derece")):
            if choose(["bachelor", "lisans", "undergraduate", "universite"]):
                return
        if any(k in label for k in ("relocat", "tasin")):
            if choose(["yes", "evet"]):
                return
        if any(k in label for k in ("sponsor", "vize", "visa")):
            if choose(["no", "hayir"]):
                return
        if any(k in label for k in ("authoriz", "izin", "work permit", "work auth", "calisma")):
            if choose(["yes", "evet"]):
                return
        if any(k in label for k in ("year", "yil", "experience", "deneyim")):
            if choose(["1-2", "1 to 2", "0-1", "less than", "1 year", "1"]):
                return
        if any(k in label for k in ("english", "ingilizce", "language", "dil")):
            if choose(["professional", "fluent", "native", "advanced", "ileri", "yes", "evet"]):
                return
        # Genel Evet/Hayır
        if choose(["yes", "evet"]):
            return

        # Son çare: placeholder seçiliyse ilk gerçek seçeneği seç → buton aktifleşir
        try:
            sel_idx = field.evaluate("el => el.selectedIndex")
        except Exception:
            sel_idx = 0
        cur_txt = low[sel_idx] if 0 <= sel_idx < len(low) else ""
        if sel_idx <= 0 or self._looks_placeholder(cur_txt):
            for i, txt in enumerate(low):
                if self._looks_placeholder(txt) or not values[i]:
                    continue
                field.select_option(index=i)
                return

    def _fill_radio_groups(self, page: Page, scope: str):
        """Her radio grubunda (name'e göre) bir seçenek işaretler → zorunlu grup boş kalmaz."""
        radios = page.query_selector_all(scope + "input[type='radio']:visible")
        groups, order = {}, []
        for r in radios:
            key = r.get_attribute("name") or f"__anon_{len(order)}"
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(r)

        answers = self.config.form_answers
        for key in order:
            items = groups[key]
            # Zaten seçili mi?
            if any(self._safe_checked(r) for r in items):
                continue

            label = self._norm(self._get_field_label(page, items[0]))
            pref = None
            if any(k in label for k in ("sponsor", "vize", "visa")):
                pref = answers.get("visa_sponsorship", "No").lower()
            elif any(k in label for k in ("relocat", "tasin", "authoriz", "izin", "work", "calisma")):
                pref = "yes"

            chosen = self._pick_radio(page, items, pref)
            if chosen:
                try:
                    chosen.check()
                except Exception:
                    try:
                        chosen.click()
                    except Exception:
                        pass

    def _pick_radio(self, page: Page, items: list, pref):
        def opt_text(r):
            return self._norm((r.get_attribute("value") or "") + " " + self._get_field_label(page, r))

        if pref:
            want_yes = pref in ("yes", "evet")
            want_no = pref in ("no", "hayir", "hayır")
            for r in items:
                ot = opt_text(r)
                if (pref in ot
                        or (want_yes and ("yes" in ot or "evet" in ot))
                        or (want_no and ("no" in ot or "hayir" in ot))):
                    return r
        # Olumlu yanıtı tercih et
        for r in items:
            if any(x in opt_text(r) for x in ("yes", "evet", "true")):
                return r
        return items[0] if items else None

    @staticmethod
    def _safe_checked(r) -> bool:
        try:
            return r.is_checked()
        except Exception:
            return False

    def _get_field_label(self, page: Page, field) -> str:
        try:
            field_id = field.get_attribute("id")
            if field_id:
                label = page.query_selector(f"label[for='{field_id}']")
                if label:
                    return label.inner_text()
            # Üst div'deki label'ı dene
            return field.evaluate(
                "el => el.closest('.artdeco-text-input, .jobs-easy-apply-form-element, .fb-form-element')?.querySelector('label')?.textContent || ''"
            )
        except Exception:
            return ""

    # ------------------------------------------------------------------ #
    # Yardımcılar
    # ------------------------------------------------------------------ #

    def _click_if_visible(self, page: Page, selector: str) -> bool:
        try:
            btn = page.query_selector(selector)
            if btn and btn.is_visible() and btn.is_enabled():
                btn.click()
                page.wait_for_timeout(1000)
                return True
        except Exception:
            pass
        return False

    def _close_modal(self, page: Page):
        for sel in [
            "button[aria-label='Dismiss']",
            "button[aria-label='Kapat']",
            ".artdeco-modal__dismiss",
            "button.artdeco-button--circle",
        ]:
            if self._click_if_visible(page, sel):
                page.wait_for_timeout(800)
                # "Discard / Sil" onayı gelebilir (taslak kaydetme)
                self._click_if_visible(page, "button[data-control-name='discard_application_confirm_btn']")
                self._click_if_visible(page, "button:has-text('Discard')")
                self._click_if_visible(page, "button:has-text('Sil')")
                return

    def _get_text(self, page: Page, selectors: list) -> str:
        for sel in selectors:
            try:
                el = page.query_selector(sel)
                if el:
                    return el.inner_text().strip()
            except Exception:
                pass
        return ""

    def _go_next_page(self, page: Page) -> bool:
        try:
            next_btn = page.query_selector("button[aria-label='View next page']")
            if next_btn and next_btn.is_enabled():
                next_btn.click()
                page.wait_for_timeout(3000)
                return True
        except Exception:
            pass
        return False
