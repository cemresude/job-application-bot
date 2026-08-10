import re
import unicodedata


def normalize(s: str) -> str:
    """
    Türkçe-güvenli ASCII normalize: İ/I/ı → i, aksanları kaldırır, küçük harfe çevirir.

    Hem yetenek adına hem ilan metnine uygulanır; böylece "Makine Öğrenmesi"
    ilandaki "MAKİNE ÖĞRENMESİ" ile eşleşir. (Python'da 'İ'.lower() birleşik
    noktalı 'i̇' üretip eşleşmeyi bozuyordu.)
    """
    s = (s or "").replace("İ", "i").replace("I", "i").replace("ı", "i")
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def _boundary_pattern(skill: str) -> "re.Pattern":
    """
    Yeteneği kelime sınırlarıyla arayan desen üretir.

    Düz `skill in text` araması kısa yeteneklerde yanlış eşleşiyordu:
    'git' → "digital"/"legitimate", 'c' → "docker", 'gat' → "investigating".
    Bunlar uyum skorunu şişirip alakasız ilanlara başvurulmasına yol açıyordu.

    Sınır kümesine '+' ve '#' de dahil: böylece 'c' yeteneği "C++" ve "C#"
    içinde eşleşmez (onlar ayrı yetenek), ama "C, SQL, Python" içinde eşleşir.
    Bedeli: 'sql' artık "MySQL/PostgreSQL" içinde eşleşmiyor — ilanlar zaten
    çoğunlukla "SQL" kelimesini ayrıca geçirdiği için kabul edilebilir bir takas.
    """
    return re.compile(r"(?<![a-z0-9+#])" + re.escape(skill) + r"(?![a-z0-9+#])")


class JobMatcher:
    """
    İlan–yetenek uyum skoru.

    Skor, eşleşen yetenek SAYISI'nın `full_match_skills` hedefine oranıdır
    (1.0'da doyar). Toplam yetenek listesinin uzunluğuna bölmüyoruz: liste
    büyüdükçe her ilanın skoru düşüyordu ve 24 yetenekle pratik tavan ~0.2'de
    kalıyordu — yani eşiği ayarlamak sezgisel değildi.

    Varsayılan hedefle (5) skorun okunuşu doğrudan şu:
        0.2 → 1 yetenek   0.6 → 3 yetenek   1.0 → 5+ yetenek
    """

    def __init__(self, skills: list, exclude_keywords: list = None, full_match_skills: int = 5,
                 core_skills: list = None, exclude_title_keywords: list = None):
        self.skills = [normalize(s) for s in skills]
        self.exclude_keywords = [normalize(kw) for kw in (exclude_keywords or [])]

        # Yalnızca BAŞLIKTA aranan hariç tutmalar. Kıdem bir başlık özelliğidir:
        # "senior" kelimesini tüm metinde arasaydık, açıklamasında "kıdemli
        # mühendislerle çalışacaksın" geçen uygun ilanlar da elenirdi.
        self.exclude_title_keywords = [normalize(kw) for kw in (exclude_title_keywords or [])]
        self.full_match_skills = max(int(full_match_skills), 1)
        self._skill_patterns = [(s, _boundary_pattern(s)) for s in self.skills]

        # Çekirdek yetenekler: en az biri geçmezse ilan elenir (boşsa kural kapalı).
        # Neden: Python/Git/Docker/SQL gibi genel araçlar neredeyse HER yazılım
        # ilanında geçiyor, dolayısıyla tek başlarına "Java Developer" ya da
        # ".NET Full-Stack" ilanlarını da eşiğin üstüne taşıyorlardı. Skora
        # katkıları sürüyor, ama artık bir ilanı tek başlarına nitelendiremiyorlar.
        self.core_skills = [normalize(s) for s in (core_skills or [])]
        self._core_patterns = [(s, _boundary_pattern(s)) for s in self.core_skills]

    def matched_skills(self, title: str, description: str = "") -> list:
        """İlanda geçen yetenekleri döndürür (skorun neden o olduğunu görmek için)."""
        text = normalize(title + " " + description)
        return [skill for skill, pattern in self._skill_patterns if pattern.search(text)]

    def matched_core_skills(self, title: str, description: str = "") -> list:
        """İlanda geçen çekirdek (alan-özel) yetenekler."""
        text = normalize(title + " " + description)
        return [skill for skill, pattern in self._core_patterns if pattern.search(text)]

    def score(self, title: str, description: str = "") -> float:
        """İlan başlığı ve açıklamasına göre 0-1 arası uyum skoru döndürür."""
        matched = len(self.matched_skills(title, description))
        return round(min(matched / self.full_match_skills, 1.0), 3)

    def is_excluded(self, title: str, description: str = "") -> bool:
        # Hariç tutulanlar ifade olduğu için düz alt-dize araması yeterli.
        if any(kw in normalize(title) for kw in self.exclude_title_keywords):
            return True
        text = normalize(title + " " + description)
        return any(kw in text for kw in self.exclude_keywords)

    def is_match(self, title: str, description: str = "", min_score: float = 0.6) -> bool:
        if self.is_excluded(title, description):
            return False
        if self._core_patterns and not self.matched_core_skills(title, description):
            return False
        return self.score(title, description) >= min_score
