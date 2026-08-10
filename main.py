#!/usr/bin/env python3
"""
Otomatik iş başvuru aracı.

Kullanım:
    python main.py                  # Tüm aktif platformlarda başvuru yap
    python main.py --dry-run        # Başvuru yapmadan sadece eşleşen ilanları listele
    python main.py --platform linkedin kariyer   # Belirli platformlarda çalış
    python main.py --stats          # Geçmiş başvuru istatistiklerini göster
"""

import argparse
import sys
import time
from pathlib import Path

from loguru import logger
from rich.console import Console
from rich.panel import Panel

from src.app_logger import AppLogger
from src.config import Config
from src.matcher import JobMatcher
from src.platforms.glassdoor import GlassdoorPlatform
from src.platforms.indeed import IndeedPlatform
from src.platforms.kariyer import KariyerPlatform
from src.platforms.linkedin import LinkedInPlatform

console = Console()


def setup_logging(verbose: bool = False):
    """
    Konsolu sadeleştirir: varsayılanda yalnızca INFO+ gösterilir.
    Ayrıntılı DEBUG kayıtları (alan doldurma denemeleri dahil) logs/run.log'a yazılır.
    Böylece her form alanı için ekrana 'hatası' satırı basılmaz.
    """
    logger.remove()
    logger.add(
        sys.stderr,
        level="DEBUG" if verbose else "INFO",
        format="<level>{level: <7}</level> | {message}",
    )
    log_path = Path(__file__).parent / "logs" / "run.log"
    log_path.parent.mkdir(exist_ok=True)
    logger.add(str(log_path), level="DEBUG", rotation="2 MB", retention=3, encoding="utf-8")

PLATFORM_MAP = {
    "linkedin": LinkedInPlatform,
    "kariyer": KariyerPlatform,
    "indeed": IndeedPlatform,
    "glassdoor": GlassdoorPlatform,
}


def build_platforms(config: Config, app_logger: AppLogger, matcher: JobMatcher, selected: list):
    # Giriş artık MANUEL yapılıyor (oturum tarayıcı profilinde saklanır), bu
    # yüzden .env'de e-posta/şifre olması ZORUNLU değildir. Sadece platformun
    # açık olup olmadığına bakılır.
    enabled_map = {
        "linkedin": config.linkedin.enabled,
        "kariyer": config.kariyer.enabled,
        "indeed": config.indeed.enabled,
        "glassdoor": config.glassdoor.enabled,
    }
    platforms = []
    for name, cls in PLATFORM_MAP.items():
        if selected and name not in selected:
            continue
        if not enabled_map[name]:
            logger.info(f"[{name}] devre dışı, atlanıyor.")
            continue
        platforms.append(cls(config, app_logger, matcher))
    return platforms


def main():
    parser = argparse.ArgumentParser(description="Otomatik iş başvuru botu")
    parser.add_argument("--dry-run", action="store_true", help="Başvuru yapma, sadece listele")
    parser.add_argument("--platform", nargs="+", choices=list(PLATFORM_MAP.keys()), help="Belirli platformlar")
    parser.add_argument("--stats", action="store_true", help="Başvuru istatistiklerini göster ve çık")
    parser.add_argument("--verbose", "-v", action="store_true", help="Ayrıntılı DEBUG loglarını konsolda göster")
    args = parser.parse_args()

    setup_logging(args.verbose)

    config = Config.load()

    console.print(Panel.fit(
        "[bold cyan]Otomatik İş Başvuru Aracı[/bold cyan]\n"
        f"[dim]{config.name} için[/dim]",
        border_style="cyan",
    ))

    app_logger = AppLogger()
    matcher = JobMatcher(config.skills, config.exclude_keywords)

    if args.stats:
        app_logger.print_summary()
        stats = app_logger.stats()
        console.print(f"\nToplam: {stats['total']} | Başvurulan: {stats['applied']} | Atlanan: {stats['skipped']}")
        return

    if args.dry_run:
        console.print("[yellow]DRY-RUN modu: başvuru yapılmayacak.[/yellow]")

    platforms = build_platforms(config, app_logger, matcher, args.platform)

    if not platforms:
        console.print("[red]Aktif platform bulunamadı. .env ve config.yaml dosyalarını kontrol et.[/red]")
        return

    console.print(f"\n[bold]{len(platforms)} platform[/bold] aktif: {', '.join(p.name for p in platforms)}")
    console.print(f"Aranacak kelimeler: {len(config.keywords)} | Lokasyonlar: {', '.join(config.locations)}\n")

    total_applied = 0

    for i, platform in enumerate(platforms):
        console.rule(f"[bold]{platform.name}[/bold]")

        if args.dry_run:
            console.print(f"[dim][{platform.name}] dry-run: gerçek çalıştırma için --dry-run bayrağını kaldır.[/dim]")
            continue

        try:
            applied = platform.run()
            total_applied += applied
            console.print(f"[green]✓ {platform.name}: {applied} başvuru[/green]")
        except Exception as exc:
            console.print(f"[red]✗ {platform.name}: {exc}[/red]")
            logger.exception(exc)

        if i < len(platforms) - 1:
            wait = config.between_platforms
            console.print(f"[dim]{wait}s bekleniyor...[/dim]")
            time.sleep(wait)

    console.rule()
    console.print(f"\n[bold green]Toplam {total_applied} pozisyona başvuru yapıldı.[/bold green]\n")
    app_logger.print_summary()
    stats = app_logger.stats()
    console.print(f"Tüm zamanlar: {stats['applied']} başvuru / {stats['total']} işlem")


if __name__ == "__main__":
    main()
