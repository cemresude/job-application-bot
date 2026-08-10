import re


class JobMatcher:
    def __init__(self, skills: list, exclude_keywords: list = None):
        self.skills = [s.lower() for s in skills]
        self.exclude_keywords = [kw.lower() for kw in (exclude_keywords or [])]

    def score(self, title: str, description: str = "") -> float:
        """İlan başlığı ve açıklamasına göre 0-1 arası uyum skoru döndürür."""
        text = (title + " " + description).lower()

        matched = sum(1 for skill in self.skills if skill in text)
        score = matched / max(len(self.skills), 1)
        return round(score, 3)

    def is_excluded(self, title: str, description: str = "") -> bool:
        text = (title + " " + description).lower()
        return any(kw in text for kw in self.exclude_keywords)

    def is_match(self, title: str, description: str = "", min_score: float = 0.15) -> bool:
        if self.is_excluded(title, description):
            return False
        return self.score(title, description) >= min_score
