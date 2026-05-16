"""CSV metadata service. Expects ID_video and Meaning columns."""
from __future__ import annotations
import io
from typing import Optional, Tuple, List, Dict
import pandas as pd


def load_csv(file_bytes: bytes) -> pd.DataFrame:
    try:
        df = pd.read_csv(io.BytesIO(file_bytes))
    except Exception:
        df = pd.read_csv(io.BytesIO(file_bytes), encoding="utf-8", sep=";")
    return df


def detect_columns(df: pd.DataFrame) -> Tuple[Optional[str], Optional[str]]:
    id_col = None
    label_col = None
    for c in df.columns:
        low = str(c).strip().lower()
        if id_col is None and low in ("id_video", "id", "video_id", "videoid"):
            id_col = c
        if label_col is None and low in ("meaning", "label", "gloss", "gt", "ground_truth"):
            label_col = c
    return id_col, label_col


def build_mapping(df: pd.DataFrame, id_col: str, label_col: str) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for _, row in df.iterrows():
        vid = str(row[id_col]).strip()
        lbl = str(row[label_col]).strip()
        if vid and vid.lower() != "nan":
            mapping[vid] = lbl
    return mapping


def preview_rows(df: pd.DataFrame, n: int = 20) -> List[Dict]:
    return df.head(n).fillna("").to_dict(orient="records")


def lookup_label(mapping: Dict[str, str], filename: str) -> Tuple[Optional[str], Optional[str]]:
    """Return (video_id, label) found by matching filename against mapping keys."""
    base = filename.rsplit(".", 1)[0]
    # exact prefix or substring match — prefer longest key
    candidates = [k for k in mapping.keys() if k and k in base]
    if not candidates:
        return None, None
    best = max(candidates, key=len)
    return best, mapping[best]
