import re


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

    def __init__(self, skills: list, exclude_keywords: list = None, full_match_skills: int = 5):
        self.skills = [s.lower() for s in skills]
        self.exclude_keywords = [kw.lower() for kw in (exclude_keywords or [])]
        self.full_match_skills = max(int(full_match_skills), 1)

    def matched_skills(self, title: str, description: str = "") -> list:
        """İlanda geçen yetenekleri döndürür (skorun neden o olduğunu görmek için)."""
        text = (title + " " + description).lower()
        return [skill for skill in self.skills if skill in text]

    def score(self, title: str, description: str = "") -> float:
        """İlan başlığı ve açıklamasına göre 0-1 arası uyum skoru döndürür."""
        matched = len(self.matched_skills(title, description))
        return round(min(matched / self.full_match_skills, 1.0), 3)

    def is_excluded(self, title: str, description: str = "") -> bool:
        text = (title + " " + description).lower()
        return any(kw in text for kw in self.exclude_keywords)

    def is_match(self, title: str, description: str = "", min_score: float = 0.6) -> bool:
        if self.is_excluded(title, description):
            return False
        return self.score(title, description) >= min_score
