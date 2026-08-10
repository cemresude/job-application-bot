import json
from datetime import datetime
from pathlib import Path

from loguru import logger
from rich.console import Console
from rich.table import Table

LOG_FILE = Path(__file__).parent.parent / "logs" / "applications.json"
console = Console()


ICONS = {
    "applied": ("✓", "green"),
    "dry_run": ("○", "cyan"),
}


class AppLogger:
    def __init__(self, dry_run: bool = False):
        # dry_run: kayıtlar bellekte tutulur ama diske YAZILMAZ — deneme
        # taraması gerçek başvuru geçmişini kirletmemeli.
        self.dry_run = dry_run
        LOG_FILE.parent.mkdir(exist_ok=True)
        self._data: list = self._load()

    def _load(self) -> list:
        if LOG_FILE.exists():
            try:
                return json.loads(LOG_FILE.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return []
        return []

    def _save(self):
        if self.dry_run:
            return
        LOG_FILE.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")

    def already_applied(self, url: str) -> bool:
        return any(r["url"] == url and r["status"] == "applied" for r in self._data)

    def record(self, platform: str, title: str, company: str, url: str, status: str, note: str = ""):
        entry = {
            "platform": platform,
            "title": title,
            "company": company,
            "url": url,
            "status": status,
            "note": note,
            "date": datetime.now().isoformat(),
        }
        self._data.append(entry)
        self._save()

        icon, color = ICONS.get(status, ("✗", "yellow"))
        console.print(f"  [{color}]{icon}[/{color}] {title} @ {company} [{status}]")
        if note:
            logger.debug(f"Not: {note}")

    def print_summary(self):
        if not self._data:
            return
        table = Table(title="Başvuru Özeti", show_header=True)
        table.add_column("Platform")
        table.add_column("Pozisyon")
        table.add_column("Şirket")
        table.add_column("Durum")
        table.add_column("Tarih")

        for r in self._data[-30:]:
            color = "green" if r["status"] == "applied" else "yellow"
            table.add_row(
                r["platform"],
                r["title"][:40],
                r["company"][:30],
                f"[{color}]{r['status']}[/{color}]",
                r["date"][:10],
            )
        console.print(table)

    def matches(self) -> list:
        """Dry-run taramasında eşleşen (başvurulabilir) ilanlar."""
        return [r for r in self._data if r["status"] == "dry_run"]

    def print_matches(self):
        """Dry-run sonucunu link'leriyle birlikte tablo olarak basar."""
        rows = self.matches()
        if not rows:
            console.print("[yellow]Eşleşen ilan bulunamadı.[/yellow]")
            return
        table = Table(title="Eşleşen İlanlar — başvuru YAPILMADI", show_header=True)
        table.add_column("Platform")
        table.add_column("Pozisyon")
        table.add_column("Şirket")
        table.add_column("Link", overflow="fold")

        for r in rows:
            table.add_row(r["platform"], r["title"][:45], r["company"][:28], r["url"])
        console.print(table)

    def stats(self) -> dict:
        total = len(self._data)
        applied = sum(1 for r in self._data if r["status"] == "applied")
        skipped = total - applied
        return {"total": total, "applied": applied, "skipped": skipped}
