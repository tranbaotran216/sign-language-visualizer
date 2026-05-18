"""Phase 6 — model prediction results loader & analysis.

Stores prediction datasets in-memory (local app, no DB). Supports flexible
column mapping, filtering, and matching prediction rows with extraction
output folders.
"""
from __future__ import annotations
import csv
import io
import os
import uuid
from typing import Dict, List, Optional, Tuple
import pandas as pd


_DATASETS: Dict[str, Dict] = {}


CANDIDATE_COLS = {
    "video_id": ["video_id", "id", "id_video", "videoid", "video_name", "filename", "file"],
    "ground_truth": ["ground_truth", "label", "gt", "truth", "target", "meaning"],
    "prediction": ["prediction", "pred", "predicted", "top1", "top1_label"],
    "confidence": ["confidence", "conf", "top1_confidence", "score", "prob"],
    "modality": ["modality", "stream", "branch", "model_type"],
    "model_name": ["model_name", "model", "exp", "experiment"],
}


def _detect(columns: List[str]) -> Dict[str, Optional[str]]:
    low = {c.lower(): c for c in columns}
    out: Dict[str, Optional[str]] = {}
    for key, cands in CANDIDATE_COLS.items():
        found = None
        for cand in cands:
            if cand in low:
                found = low[cand]
                break
        out[key] = found
    return out


def import_csv(file_bytes: bytes, filename: str) -> Dict:
    try:
        df = pd.read_csv(io.BytesIO(file_bytes))
    except Exception:
        df = pd.read_csv(io.BytesIO(file_bytes), sep=";", encoding="utf-8")
    cols = [str(c) for c in df.columns]
    suggested = _detect(cols)
    ds_id = uuid.uuid4().hex
    _DATASETS[ds_id] = {
        "id": ds_id, "filename": filename, "df": df,
        "columns": cols, "mapping": suggested, "rows": [],
    }
    preview = df.head(20).fillna("").to_dict(orient="records")
    return {
        "dataset_id": ds_id,
        "filename": filename,
        "n_rows": int(len(df)),
        "columns": cols,
        "suggested_mapping": suggested,
        "preview_rows": preview,
    }


def _normalize(s: str) -> str:
    return str(s).strip().lower().rsplit(".", 1)[0]


def apply_mapping(ds_id: str, mapping: Dict, outputs_root: str) -> Dict:
    ds = _DATASETS.get(ds_id)
    if not ds:
        raise KeyError("dataset not found")
    ds["mapping"] = {**ds["mapping"], **{k: v for k, v in mapping.items() if v}}
    m = ds["mapping"]
    df = ds["df"]

    # build extraction lookup: project_dir, video_name keys -> project_dir
    extraction_index: Dict[str, str] = {}
    if os.path.isdir(outputs_root):
        for name in os.listdir(outputs_root):
            if name.startswith("_"):
                continue
            extraction_index[_normalize(name)] = name
            # also store by leading token
            parts = name.split("_", 1)
            if parts:
                extraction_index.setdefault(_normalize(parts[0]), name)

    rows = []
    for i, r in df.iterrows():
        vid_raw = str(r.get(m.get("video_id") or "", "")).strip()
        gt = str(r.get(m.get("ground_truth") or "", "")).strip()
        pr = str(r.get(m.get("prediction") or "", "")).strip()
        try:
            conf = float(r.get(m.get("confidence") or "", 0) or 0)
        except Exception:
            conf = 0.0
        modality = str(r.get(m.get("modality") or "", "")).strip()
        model_name = str(r.get(m.get("model_name") or "", "")).strip()
        # match
        key = _normalize(vid_raw)
        matched = extraction_index.get(key)
        if not matched:
            # try substring match
            for k, v in extraction_index.items():
                if key and (key in k or k in key):
                    matched = v
                    break
        correct = bool(gt) and bool(pr) and gt.strip().lower() == pr.strip().lower()
        rows.append({
            "row_id": i,
            "video_id": vid_raw,
            "ground_truth": gt,
            "prediction": pr,
            "confidence": conf,
            "modality": modality,
            "model_name": model_name,
            "matched_output": matched,
            "matched_grid_url": f"/files/{matched}/preview/grid_{matched}.jpg" if matched else None,
            "correct": correct,
        })
    ds["rows"] = rows
    return {"dataset_id": ds_id, "n_rows": len(rows), "summary": summary(ds_id), "rows_preview": rows[:50]}


def summary(ds_id: str) -> Dict:
    ds = _DATASETS.get(ds_id)
    if not ds:
        return {}
    rows = ds.get("rows") or []
    n = len(rows)
    correct = sum(1 for r in rows if r["correct"])
    matched = sum(1 for r in rows if r["matched_output"])
    confs = [r["confidence"] for r in rows if r["confidence"] is not None]
    modalities = sorted({r["modality"] for r in rows if r["modality"]})
    return {
        "total": n,
        "correct": correct,
        "wrong": n - correct,
        "accuracy": (correct / n) if n else 0.0,
        "mean_confidence": (sum(confs) / len(confs)) if confs else 0.0,
        "matched_count": matched,
        "unmatched_count": n - matched,
        "modalities": modalities,
        "has_multi_modality": len(modalities) > 1,
    }


def filter_rows(ds_id: str, filter_kind: str = "all", q: str = "") -> List[Dict]:
    ds = _DATASETS.get(ds_id)
    if not ds:
        return []
    rows = list(ds.get("rows") or [])
    if q:
        ql = q.lower()
        rows = [r for r in rows if ql in str(r["video_id"]).lower()
                or ql in str(r["ground_truth"]).lower()
                or ql in str(r["prediction"]).lower()]
    if filter_kind == "correct":
        rows = [r for r in rows if r["correct"]]
    elif filter_kind == "wrong":
        rows = [r for r in rows if not r["correct"]]
    elif filter_kind == "low_conf":
        rows = [r for r in rows if r["confidence"] < 0.5]
    elif filter_kind == "high_conf_wrong":
        rows = [r for r in rows if (not r["correct"]) and r["confidence"] >= 0.7]
    elif filter_kind in ("rgb_wins", "pose_wins", "fusion_wins"):
        # group rows by video_id+gt, compare per-modality correctness
        by_vid: Dict[Tuple[str, str], Dict[str, Dict]] = {}
        for r in rows:
            key = (r["video_id"], r["ground_truth"])
            by_vid.setdefault(key, {})[r["modality"].lower()] = r
        winner = filter_kind.split("_")[0]
        out = []
        for key, mods in by_vid.items():
            w = mods.get(winner)
            if not w or not w["correct"]:
                continue
            others = [m for k, m in mods.items() if k != winner]
            if any(not m["correct"] for m in others):
                out.append(w)
        rows = out
    return rows


def class_report(ds_id: str) -> Dict:
    ds = _DATASETS.get(ds_id)
    if not ds:
        return {}
    rows = ds.get("rows") or []
    classes: Dict[str, Dict] = {}
    confusion: Dict[Tuple[str, str], int] = {}
    for r in rows:
        gt = r["ground_truth"]
        pr = r["prediction"]
        if not gt:
            continue
        c = classes.setdefault(gt, {"total": 0, "correct": 0})
        c["total"] += 1
        if r["correct"]:
            c["correct"] += 1
        confusion[(gt, pr)] = confusion.get((gt, pr), 0) + 1
    per_class = [
        {"class": k, "total": v["total"], "correct": v["correct"],
         "accuracy": v["correct"] / v["total"] if v["total"] else 0}
        for k, v in classes.items()
    ]
    confused_pairs = sorted(
        [{"gt": k[0], "pred": k[1], "count": v} for k, v in confusion.items() if k[0] != k[1]],
        key=lambda x: -x["count"],
    )[:20]
    return {"per_class": sorted(per_class, key=lambda x: x["accuracy"]),
            "most_confused": confused_pairs}


def export_csv(ds_id: str, filter_kind: str = "all") -> bytes:
    rows = filter_rows(ds_id, filter_kind)
    buf = io.StringIO()
    fields = ["video_id", "ground_truth", "prediction", "correct",
              "confidence", "modality", "model_name", "matched_output"]
    w = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return buf.getvalue().encode("utf-8-sig")


def get_dataset(ds_id: str) -> Optional[Dict]:
    return _DATASETS.get(ds_id)
