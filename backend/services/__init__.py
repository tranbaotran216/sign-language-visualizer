"""Utilities for safe filenames and label normalization."""
from __future__ import annotations
import re
from unidecode import unidecode


def safe_label(label: str) -> str:
    """Convert Vietnamese label -> ascii safe identifier.

    "độc ác" -> "doc_ac"
    "môn tiếng việt" -> "mon_tieng_viet"
    """
    if not label:
        return "unknown"
    s = unidecode(str(label)).lower().strip()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = s.strip("_")
    return s or "unknown"


def safe_video_name(name: str) -> str:
    if not name:
        return "video"
    s = unidecode(str(name)).strip()
    s = re.sub(r"[^A-Za-z0-9_-]+", "_", s)
    return s.strip("_") or "video"
