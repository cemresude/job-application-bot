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
  karşılaştırılır. Skor, eşleşen yetenek **sayısının** `full_match_skills` hedefine
  oranıdır (1.0'da doyar), toplam liste uzunluğuna bölünmez — böylece yetenek
  eklemek eşiği kaydırmaz:

  | Eşleşen yetenek | 1 | 2 | 3 | 4 | 5+ |
  |---|---|---|---|---|---|
  | Skor (`full_match_skills: 5`) | 0.2 | 0.4 | 0.6 | 0.8 | 1.0 |

  Skorun yanında ikinci bir şart var: **`core_skills`'ten en az biri geçmeli.**
  Python, Git, Docker, SQL gibi genel araçlar neredeyse her yazılım ilanında
  geçtiği için tek başlarına `Java Developer` ya da `.NET Full-Stack` ilanlarını
  da eşiğin üstüne taşıyorlardı — bir full-stack ilanı yalnızca HTML/CSS/JS/SQL/Git
  ile 1.0 skor alabiliyor. Çekirdek yetenek şartı bunu keser; genel araçlar skora
  katkı vermeye devam eder ama bir ilanı tek başlarına nitelendiremez.

  Eşleşme **kelime sınırlarıyla** yapılır (`git` artık "digital" içinde, `c` de
  "docker" içinde eşleşmez) ve her iki taraf Türkçe-güvenli ASCII'ye normalize
  edilir — böylece `makine öğrenmesi` ilandaki `MAKİNE ÖĞRENMESİ` ile eşleşir.
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
     linkedin_url: "linkedin.com/in/kullanici-adi"
   form_answers:
     github_url: "github.com/kullanici-adi"
     university: "..."
     field_of_study: "..."
     gpa: "..."
     address: "..."
     city: "..."
   ```

2. **CV dosyaları** — `cv/cv_tr.pdf` ve `cv/cv_en.pdf`
3. **Arama ayarları** — `config.yaml` içinden anahtar kelime, lokasyon ve yetenekler

> `.env` dosyası opsiyoneldir; giriş manuel yapıldığı için şifre saklamak gerekmez.

## Kullanım

```bash
python main.py                            # tüm aktif platformlarda çalış
python main.py --dry-run                  # tara + eşleşenleri listele, BAŞVURMA
python main.py --platform linkedin        # sadece belirli platformlar
python main.py --stats                    # geçmiş başvuru istatistikleri
python main.py -v                         # ayrıntılı DEBUG logları
```

`--dry-run` ilanları gerçekten tarar ve başvurulabilir olanları link'leriyle
tablo hâlinde basar; başvuru butonuna basmaz ve `logs/applications.json`'a
yazmaz — yani başvuru geçmişin bozulmaz. Tarama yapabilmek için yine de
platforma giriş yapılması gerekir.

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
