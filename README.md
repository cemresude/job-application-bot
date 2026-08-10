# Otomatik İş Başvuru Botu

LinkedIn, Kariyer.net, Indeed ve Glassdoor üzerinde ilan arayan, profiline uyanları
skorlayan ve "kolay başvuru" formlarını otomatik dolduran bir Playwright botu.
Başvurulan/atlanan ilanları, atlanma nedenleriyle birlikte bir web panelinde gösterir.

## Nasıl çalışır

- **Kalıcı tarayıcı profili** — her platform için ayrı bir Chromium profili
  (`.browser-profiles/`) tutulur. Giriş bir kez **manuel** yapılır, oturum profilde
  saklanır; sonraki çalıştırmalarda giriş istenmez. Otomatik şifre girişi bilinçli
  olarak kullanılmaz (platformlar bunu bot davranışı sayıp doğrulamaya takıyor).
- **Uyum skoru** — ilan başlığı ve açıklaması `config.yaml`'daki yetenek listesiyle
  karşılaştırılır; `min_score` altındaki ilanlar atlanır.
- **Form doldurma** — deneyim yılı, çalışma izni, maaş beklentisi gibi sık sorulan
  alanlar `form_answers` bölümünden yanıtlanır; CV otomatik yüklenir.
- **Kayıt** — her işlem `logs/applications.json`'a yazılır, aynı ilana iki kez
  başvurulmaz.

## Kurulum

```bash
./setup.sh          # bağımlılıklar + Playwright tarayıcısı + .env
```

Ardından:

1. **Kişisel bilgiler** — `config.local.yaml` oluştur (git'e gitmez, `config.yaml`'ın
   üzerine biner):

   ```yaml
   personal:
     name: "Ad Soyad"
     email: "ornek@eposta.com"
     phone: "+90 5XX XXX XX XX"
   form_answers:
     address: "..."
     city: "..."
     gpa: "..."
   ```

2. **CV dosyaları** — `cv/cv_tr.pdf` ve `cv/cv_en.pdf`
3. **Arama ayarları** — `config.yaml` içinden anahtar kelime, lokasyon ve yetenekler

> `.env` dosyası opsiyoneldir; giriş manuel yapıldığı için şifre saklamak gerekmez.

## Kullanım

```bash
python main.py                            # tüm aktif platformlarda çalış
python main.py --platform linkedin        # sadece belirli platformlar
python main.py --stats                    # geçmiş başvuru istatistikleri
python main.py -v                         # ayrıntılı DEBUG logları
```

### Web paneli

```bash
./web.sh                                  # http://127.0.0.1:8787
```

Bulunan ilanları kategorilere ayırır: başvurulan, kolay başvuru olmayan
(manuel aday), formu doldurulamayan ve düşük uyumlu ilanlar. Ek bağımlılık
gerektirmez — yalnızca Python standart kütüphanesi kullanır.

## Proje yapısı

```
main.py                 CLI giriş noktası
config.yaml             arama kriterleri, yetenekler, form yanıtları
src/config.py           yapılandırma yükleme (+ config.local.yaml override)
src/browser.py          kalıcı Chromium profili, stealth ayarları
src/base_platform.py    ortak giriş akışı ve form yanıtlama mantığı
src/matcher.py          ilan–yetenek uyum skoru
src/app_logger.py       başvuru kaydı ve özet tablosu
src/web.py              dashboard sunucusu (stdlib http.server)
src/platforms/          LinkedIn, Kariyer.net, Indeed, Glassdoor
```

## Notlar

- `headless: false` önerilir — platformlar başsız tarayıcıyı daha kolay tespit ediyor.
- Sistemde Google Chrome kuruluysa otomatik kullanılır; yoksa paketli Chromium'a düşer.
- `.browser-profiles/`, `.env`, `config.local.yaml`, CV'ler ve loglar git'e dahil değildir.
