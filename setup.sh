#!/bin/bash
set -e

echo "==> Bağımlılıklar yükleniyor..."
pip install -r requirements.txt

echo "==> Playwright tarayıcısı indiriliyor..."
playwright install chromium

echo "==> .env dosyası oluşturuluyor..."
if [ ! -f .env ]; then
    cp .env.example .env
    echo "   .env oluşturuldu — kimlik bilgilerini gir!"
else
    echo "   .env zaten mevcut."
fi

echo ""
echo "Kurulum tamamlandı."
echo "Sıradaki adımlar:"
echo "  1. .env dosyasını aç ve platform kimlik bilgilerini gir"
echo "  2. CV dosyalarını cv/ klasörüne koy:"
echo "     cv/cv_tr.pdf  (Türkçe CV)"
echo "     cv/cv_en.pdf  (İngilizce CV)"
echo "  3. python main.py --dry-run  # test et"
echo "  4. python main.py            # başvuru yap"
