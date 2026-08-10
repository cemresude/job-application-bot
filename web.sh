#!/bin/bash
# Başvuru botu web arayüzünü başlatır.
# Botun bulduğu ilanları, başvuru durumlarını ve başvurulmama nedenlerini
# tarayıcıda gösterir. Ek bağımlılık gerektirmez (Python standart kütüphanesi).
#
# Kullanım:
#   ./web.sh              # http://127.0.0.1:8787 açar
#   ./web.sh --port 9000  # başka port
#   ./web.sh --no-open    # tarayıcıyı otomatik açma
cd "$(dirname "$0")"
exec python -m src.web "$@"
