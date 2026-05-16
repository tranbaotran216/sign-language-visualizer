"""Parse extracted frame filenames.

Expected formats:
  pair_{video_name}_{label}_{sample_index}_{original_frame_index}.jpg
  rgb_{video_name}_{label}_{sample_index}_{original_frame_index}.jpg
  pose_{video_name}_{label}_{sample_index}_{original_frame_index}.jpg
  grid_{video_name}_{label}.jpg

Label is the *safe* label (ascii, underscored). It may contain underscores.
We use the trailing two integer tokens as sample_index and original_frame_index.
"""
from __future__ import annotations
import os
import re
from typing import Optional, Dict

_KINDS = ("pair", "rgb", "pose", "grid")
_FRAME_RE = re.compile(
    r"^(pair|rgb|pose)_(?P<video>[^_]+)_(?P<rest>.+)_(?P<sample>\d+)_(?P<orig>\d+)\.(jpg|jpeg|png)$",
    re.IGNORECASE,
)
_GRID_RE = re.compile(
    r"^grid_(?P<video>[^_]+)_(?P<label>.+)\.(jpg|jpeg|png)$",
    re.IGNORECASE,
)


def parse_filename(filename: str) -> Optional[Dict]:
    base = os.path.basename(filename)
    m = _FRAME_RE.match(base)
    if m:
        return {
            "kind": base.split("_", 1)[0].lower(),
            "video_name": m.group("video"),
            "safe_label": m.group("rest"),
            "sample_index": int(m.group("sample")),
            "original_frame_index": int(m.group("orig")),
            "filename": base,
        }
    m = _GRID_RE.match(base)
    if m:
        return {
            "kind": "grid",
            "video_name": m.group("video"),
            "safe_label": m.group("label"),
            "sample_index": None,
            "original_frame_index": None,
            "filename": base,
        }
    return None
