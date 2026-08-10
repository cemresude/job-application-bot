import json
from datetime import datetime
from pathlib import Path

from loguru import logger
from rich.console import Console
from rich.table import Table

LOG_FILE = Path(__file__).parent.parent / "logs" / "applications.json"
console = Console()


class AppLogger:
    def __init__(self):
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

        icon = "✓" if status == "applied" else "✗"
        color = "green" if status == "applied" else "yellow"
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

    def stats(self) -> dict:
        total = len(self._data)
        applied = sum(1 for r in self._data if r["status"] == "applied")
        skipped = total - applied
        return {"total": total, "applied": applied, "skipped": skipped}
