#!/usr/bin/env python3
"""
Başvuru botu için web arayüzü (dashboard).

Ek bağımlılık YOK — sadece Python standart kütüphanesi (http.server) kullanır.
logs/applications.json dosyasını okur, ilanları kategorilere ayırır ve
tarayıcıda gösterilebilen bir kontrol paneli sunar.

Öne çıkan iki liste (kullanıcı isteği):
  1. Bulunan ama başvurulmayan ilanlar  -> NEDENİYLE birlikte
  2. Bulunan ama "kolay başvuru" olmayan ilanlar (LinkedIn Easy Apply yok /
     Indeed harici başvuru / form doldurulamadı) -> manuel başvuru adayları

Kullanım:
    python -m src.web                 # http://127.0.0.1:8787 açar
    python -m src.web --port 9000     # başka port
    python -m src.web --no-open       # tarayıcıyı otomatik açma
"""

import argparse
import json
import re
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).parent.parent
LOG_FILE = ROOT / "logs" / "applications.json"
DASHBOARD_HTML = Path(__file__).parent.parent / "web" / "dashboard.html"


# --------------------------------------------------------------------------- #
# Veri işleme
# --------------------------------------------------------------------------- #

def _load_raw() -> list:
    if not LOG_FILE.exists():
        return []
    try:
        return json.loads(LOG_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def categorize(status: str, note: str) -> dict:
    """
    Bir kaydı insan-dostu bir kategoriye eşler.

    category  : makine anahtarı (filtreleme için)
    label     : ekranda görünecek Türkçe etiket
    manual    : bot otomatik başvuramadı ama eşleşme vardı -> elle başvurulabilir
    """
    note_l = (note or "").lower()

    if status == "applied":
        return {"category": "applied", "label": "Başvuruldu", "manual": False}

    # Dry-run taraması: eşleşti ama bilinçli olarak başvurulmadı (MANUEL aday)
    if status == "dry_run":
        return {"category": "dry_run", "label": "Dry-run eşleşmesi", "manual": True}

    # Kolay başvuru yok — bot başvuramaz, ilan uygun olabilir (MANUEL aday)
    if "easy apply yok" in note_l or "indeed apply yok" in note_l or "harici" in note_l:
        return {"category": "no_easy_apply", "label": "Kolay başvuru yok", "manual": True}

    # Form doldurulamadı — Easy Apply vardı ama form soruları geçilemedi (MANUEL aday)
    if "form" in note_l:
        return {"category": "form_failed", "label": "Form doldurulamadı", "manual": True}

    # Düşük uyum skoru — botun ilgisiz bulup elediği ilanlar
    if "uyum" in note_l:
        return {"category": "low_match", "label": "Düşük uyum", "manual": False}

    return {"category": "other", "label": "Diğer / belirsiz", "manual": False}


def clean_url(url: str) -> str:
    """
    Tıklanabilir doğrudan ilan linki üretir.

    LinkedIn kayıtlarında URL bir arama sayfasıdır (currentJobId parametresiyle);
    bunu gerçek ilan sayfasına (jobs/view/<id>) çeviririz.
    """
    if not url:
        return ""
    if "linkedin.com" in url and "currentJobId=" in url:
        m = re.search(r"currentJobId=(\d+)", url)
        if m:
            return f"https://www.linkedin.com/jobs/view/{m.group(1)}/"
    return url


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def build_dataset() -> dict:
    """
    Ham logu okur, benzersizleştirir (aynı ilan birden çok koşuda tekrar eder)
    ve dashboard'un ihtiyaç duyduğu her şeyi içeren bir sözlük döndürür.
    """
    raw = _load_raw()

    # (platform, başlık, şirket) anahtarıyla grupla; en güncel kaydı tut,
    # gruptaki herhangi bir kayıt 'applied' ise başvurulmuş say.
    groups: dict = {}
    for r in raw:
        key = (_norm(r.get("platform")), _norm(r.get("title")), _norm(r.get("company")))
        g = groups.setdefault(key, {"records": [], "applied": None})
        g["records"].append(r)
        if r.get("status") == "applied" and g["applied"] is None:
            g["applied"] = r

    jobs = []
    for g in groups.values():
        latest = max(g["records"], key=lambda r: r.get("date", ""))
        chosen = g["applied"] or latest
        cat = categorize(chosen.get("status", ""), chosen.get("note", ""))
        jobs.append({
            "platform": chosen.get("platform", ""),
            "title": chosen.get("title", "") or "(başlıksız)",
            "company": chosen.get("company", "") or "—",
            "url": clean_url(chosen.get("url", "")),
            "status": chosen.get("status", ""),
            "note": chosen.get("note", "") or cat["label"],
            "category": cat["category"],
            "category_label": cat["label"],
            "manual": cat["manual"],
            "date": chosen.get("date", ""),
            "seen_count": len(g["records"]),
        })

    # En yeni ilanlar üstte
    jobs.sort(key=lambda j: j["date"], reverse=True)

    def count(pred):
        return sum(1 for j in jobs if pred(j))

    stats = {
        "unique": len(jobs),
        "scans": len(raw),
        "applied": count(lambda j: j["category"] == "applied"),
        "manual": count(lambda j: j["manual"]),
        "no_easy_apply": count(lambda j: j["category"] == "no_easy_apply"),
        "form_failed": count(lambda j: j["category"] == "form_failed"),
        "low_match": count(lambda j: j["category"] == "low_match"),
        "other": count(lambda j: j["category"] == "other"),
        "skipped": count(lambda j: j["category"] != "applied"),
    }

    platforms = sorted({j["platform"] for j in jobs if j["platform"]})

    return {
        "generated_at": datetime.now().isoformat(),
        "stats": stats,
        "platforms": platforms,
        "jobs": jobs,
    }


# --------------------------------------------------------------------------- #
# HTTP sunucusu
# --------------------------------------------------------------------------- #

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):  # sessiz (konsolu kirletme)
        pass

    def _send(self, code: int, body: bytes, content_type: str):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/api/applications":
            try:
                payload = json.dumps(build_dataset(), ensure_ascii=False).encode("utf-8")
                self._send(200, payload, "application/json; charset=utf-8")
            except Exception as exc:  # noqa: BLE001
                err = json.dumps({"error": str(exc)}).encode("utf-8")
                self._send(500, err, "application/json; charset=utf-8")
            return

        if path in ("/", "/index.html", "/dashboard"):
            if DASHBOARD_HTML.exists():
                self._send(200, DASHBOARD_HTML.read_bytes(), "text/html; charset=utf-8")
            else:
                self._send(500, b"dashboard.html bulunamadi", "text/plain; charset=utf-8")
            return

        self._send(404, b"Not Found", "text/plain; charset=utf-8")


def main():
    parser = argparse.ArgumentParser(description="Başvuru botu web arayüzü")
    parser.add_argument("--port", type=int, default=8787, help="Sunucu portu (varsayılan 8787)")
    parser.add_argument("--host", default="127.0.0.1", help="Sunucu adresi")
    parser.add_argument("--no-open", action="store_true", help="Tarayıcıyı otomatik açma")
    args = parser.parse_args()

    url = f"http://{args.host}:{args.port}/"
    server = ThreadingHTTPServer((args.host, args.port), Handler)

    n = len(_load_raw())
    print("=" * 52)
    print("  Başvuru Botu — Web Arayüzü")
    print(f"  Adres : {url}")
    print(f"  Kayıt : logs/applications.json ({n} işlem)")
    print("  Durdurmak için: Ctrl+C")
    print("=" * 52)

    if not args.no_open:
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            pass

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nSunucu kapatıldı.")
        server.shutdown()


if __name__ == "__main__":
    main()
