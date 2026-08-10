import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv

load_dotenv()


def _deep_merge(base: dict, override: dict) -> dict:
    """override'ı base'in üzerine iç içe (recursive) bindirir; base'i değiştirir."""
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


@dataclass
class PlatformConfig:
    enabled: bool
    max_per_run: int
    language: str


@dataclass
class Config:
    # Kişisel bilgiler
    name: str
    email: str
    phone: str
    location: str
    linkedin_url: str

    # CV yolları
    cv_turkish: str
    cv_english: str

    # Platform kimlik bilgileri
    linkedin_email: str
    linkedin_password: str
    kariyer_email: str
    kariyer_password: str
    indeed_email: str
    indeed_password: str
    glassdoor_email: str
    glassdoor_password: str

    # Platform ayarları
    linkedin: PlatformConfig
    kariyer: PlatformConfig
    indeed: PlatformConfig
    glassdoor: PlatformConfig

    # Arama kriterleri
    keywords: list
    locations: list
    exclude_keywords: list

    # Yetenek eşleştirme
    min_score: float
    skills: list

    # Form yanıtları
    form_answers: dict

    # Tarayıcı
    headless: bool
    slow_mo: int

    # Hız sınırı
    min_delay: float
    max_delay: float
    between_platforms: int

    @classmethod
    def load(cls) -> "Config":
        base_dir = Path(__file__).parent.parent
        with open(base_dir / "config.yaml", "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        # config.local.yaml varsa üstüne bindirilir. Kişisel bilgiler (ad, telefon,
        # adres, not ortalaması) burada tutulur; bu dosya git'e gönderilmez.
        local_path = base_dir / "config.local.yaml"
        if local_path.exists():
            with open(local_path, "r", encoding="utf-8") as f:
                _deep_merge(raw, yaml.safe_load(f) or {})

        personal = raw["personal"]
        cv = raw["cv"]
        platforms = raw["platforms"]
        search = raw["search"]
        skill_cfg = raw["skill_matching"]
        browser = raw["browser"]
        rate = raw["rate_limiting"]
        form = raw.get("form_answers", {})

        return cls(
            name=personal["name"],
            email=personal["email"],
            phone=personal["phone"],
            location=personal["location"],
            linkedin_url=personal.get("linkedin_url", ""),
            cv_turkish=cv["turkish"],
            cv_english=cv["english"],
            linkedin_email=os.getenv("LINKEDIN_EMAIL", ""),
            linkedin_password=os.getenv("LINKEDIN_PASSWORD", ""),
            kariyer_email=os.getenv("KARIYER_EMAIL", ""),
            kariyer_password=os.getenv("KARIYER_PASSWORD", ""),
            indeed_email=os.getenv("INDEED_EMAIL", ""),
            indeed_password=os.getenv("INDEED_PASSWORD", ""),
            glassdoor_email=os.getenv("GLASSDOOR_EMAIL", ""),
            glassdoor_password=os.getenv("GLASSDOOR_PASSWORD", ""),
            linkedin=PlatformConfig(**platforms["linkedin"]),
            kariyer=PlatformConfig(**platforms["kariyer"]),
            indeed=PlatformConfig(**platforms["indeed"]),
            glassdoor=PlatformConfig(**platforms["glassdoor"]),
            keywords=search["keywords"],
            locations=search["locations"],
            exclude_keywords=search.get("exclude_keywords", []),
            min_score=skill_cfg["min_score"],
            skills=skill_cfg["skills"],
            form_answers=form,
            headless=browser["headless"],
            slow_mo=browser["slow_mo"],
            min_delay=rate["min_delay"],
            max_delay=rate["max_delay"],
            between_platforms=rate["between_platforms"],
        )

    def get_cv_path(self, language: str) -> Optional[str]:
        base = Path(__file__).parent.parent
        path = base / (self.cv_english if language == "english" else self.cv_turkish)
        return str(path) if path.exists() else None
