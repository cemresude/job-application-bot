"""
Tarayıcı yönetimi.

launch_persistent() kullanılır:
  - Her platform için ayrı, kalıcı Chromium profili (.browser-profiles/<platform>/)
  - Profil oturum çerezlerini saklar → ikinci çalıştırmada giriş gerekmez
    (kullanıcı bir kez manuel giriş yapar, sonraki çalıştırmalar hazır oturumu kullanır)
  - Mümkünse sistemdeki gerçek Google Chrome kullanılır (channel="chrome").
    Gerçek Chrome, Playwright'ın paketlediği Chromium'a göre çok daha az
    "bot" izi bırakır (gerçek eklentiler, yazı tipleri, User-Agent vb.).
"""

import random
import time
from pathlib import Path

from loguru import logger
from playwright.sync_api import BrowserContext, Page, sync_playwright

# Playwright/otomasyon izlerini gizleyen init script.
# ctx.add_init_script() ile eklenir → sayfadaki tüm scriptlerden ÖNCE çalışır.
STEALTH_JS = """
() => {
    // navigator.webdriver izini kaldır
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

    // window.chrome nesnesini gerçekçi hale getir
    if (!window.chrome) {
        window.chrome = { runtime: {}, loadTimes: function(){}, csi: function(){}, app: {} };
    }

    // Notification izni sorgusunu normalleştir
    const origQuery = window.navigator.permissions && window.navigator.permissions.query;
    if (origQuery) {
        window.navigator.permissions.query = (p) =>
            p && p.name === 'notifications'
                ? Promise.resolve({ state: Notification.permission })
                : origQuery(p);
    }

    // Dil, platform ve donanım bilgilerini tutarlı ver
    Object.defineProperty(navigator, 'languages', { get: () => ['tr-TR', 'tr', 'en-US', 'en'] });
    Object.defineProperty(navigator, 'platform', { get: () => 'MacIntel' });
    Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
    Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });

    // Boş plugin/mimeType listeleri headless izi sayılır → dolu göster
    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
}
"""

PROFILES_DIR = Path(__file__).parent.parent / ".browser-profiles"
SCREENSHOTS_DIR = Path(__file__).parent.parent / "screenshots"
SCREENSHOTS_DIR.mkdir(exist_ok=True)

_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-infobars",
    "--start-maximized",
    "--window-size=1366,900",
]


def launch_persistent(platform_name: str, headless: bool = False, slow_mo: int = 30) -> tuple:
    """
    Platforma özel kalıcı tarayıcı profili başlatır.
    Döndürür: (playwright_instance, BrowserContext)
    """
    safe_name = platform_name.lower().replace(".", "").replace(" ", "_")
    profile_dir = PROFILES_DIR / safe_name
    profile_dir.mkdir(parents=True, exist_ok=True)

    pw = sync_playwright().start()

    common_kwargs = dict(
        user_data_dir=str(profile_dir),
        headless=headless,
        slow_mo=slow_mo,
        args=_LAUNCH_ARGS,
        viewport=None,  # gerçek pencere boyutunu kullan (sabit viewport bir bot izidir)
        locale="tr-TR",
        timezone_id="Europe/Istanbul",
        accept_downloads=True,
        ignore_https_errors=True,
        # User-Agent'ı elle EZMİYORUZ: gerçek tarayıcının UA'sı, sürümüyle
        # tutarlı olduğu için sahte/eski bir UA'dan daha az iz bırakır.
    )

    # Önce sistemdeki gerçek Chrome'u dene; yoksa paketli Chromium'a düş.
    try:
        ctx = pw.chromium.launch_persistent_context(channel="chrome", **common_kwargs)
        logger.debug(f"[{platform_name}] Gerçek Google Chrome ile başlatıldı.")
    except Exception:
        logger.warning(
            f"[{platform_name}] Sistemde Chrome bulunamadı, paketli Chromium'a dönülüyor "
            "(bot tespiti biraz daha olası). Kalıcı çözüm için Google Chrome kur."
        )
        ctx = pw.chromium.launch_persistent_context(**common_kwargs)

    ctx.add_init_script(STEALTH_JS)
    return pw, ctx


def human_type(page: Page, selector: str, text: str):
    page.click(selector)
    for ch in text:
        page.keyboard.type(ch)
        time.sleep(random.uniform(0.05, 0.15))


def screenshot(page: Page, name: str) -> str:
    path = SCREENSHOTS_DIR / f"{name}_{int(time.time())}.png"
    try:
        page.screenshot(path=str(path))
    except Exception:
        pass
    return str(path)
