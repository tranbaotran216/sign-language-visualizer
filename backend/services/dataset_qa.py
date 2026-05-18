"""Phase 5 — dataset-level quality analysis.

Scans backend/outputs/ for extraction folders, loads manifest.json and
quality_report.json for each one, and produces a dataset-level summary
plus per-video rows. Pure functions; no FastAPI deps.
"""
from __future__ import annotations
import csv
import io
import json
import os
from typing import Dict, List, Optional


def _safe_load(path: str) -> Optional[dict]:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _quality_status(pose_r: float, lh_r: float, rh_r: float, zero_r: float) -> str:
    if zero_r >= 0.5:
        return "critical"
    rates = [pose_r, lh_r, rh_r]
    if any(r >= 0.7 for r in rates):
        return "bad"
    if any(r >= 0.3 for r in rates):
        return "warning"
    return "good"


def scan_dataset(outputs_root: str) -> Dict:
    """Walk outputs/, load each video's manifest + quality_report, return summary."""
    rows: List[Dict] = []
    missing_meta = 0
    if not os.path.isdir(outputs_root):
        return {"summary": {}, "rows": []}

    for name in sorted(os.listdir(outputs_root)):
        if name.startswith("_") or name.startswith("."):
            continue
        p = os.path.join(outputs_root, name)
        if not os.path.isdir(p):
            continue

        manifest = None
        qr = None
        for fn in os.listdir(p):
            if fn.startswith("manifest_") and fn.endswith(".json"):
                manifest = _safe_load(os.path.join(p, fn))
        reports_dir = os.path.join(p, "reports")
        if os.path.isdir(reports_dir):
            for fn in os.listdir(reports_dir):
                if fn.startswith("quality_report_") and fn.endswith(".json"):
                    qr = _safe_load(os.path.join(reports_dir, fn))

        if not manifest or not qr:
            missing_meta += 1
            rows.append({
                "project_dir": name,
                "video_name": (manifest or {}).get("video_name", name),
                "label": (manifest or {}).get("label", ""),
                "timesteps": (manifest or {}).get("timesteps", 0),
                "pose_missing_rate": None,
                "left_hand_missing_rate": None,
                "right_hand_missing_rate": None,
                "all_zero_rate": None,
                "quality_status": "missing",
                "grid_url": None,
            })
            continue

        pose_r = float(qr.get("pose_missing_rate", 0))
        lh_r = float(qr.get("left_hand_missing_rate", 0))
        rh_r = float(qr.get("right_hand_missing_rate", 0))
        zero_r = float(qr.get("all_zero_rate", 0))
        status = _quality_status(pose_r, lh_r, rh_r, zero_r)
        grid_rel = (manifest.get("outputs") or {}).get("grid")
        rows.append({
            "project_dir": name,
            "video_name": manifest.get("video_name", name),
            "label": manifest.get("label", ""),
            "timesteps": manifest.get("timesteps", 0),
            "total_original_frames": manifest.get("total_original_frames", 0),
            "pose_missing_rate": pose_r,
            "left_hand_missing_rate": lh_r,
            "right_hand_missing_rate": rh_r,
            "all_zero_rate": zero_r,
            "quality_status": status,
            "grid_url": f"/files/{name}/{grid_rel}" if grid_rel else None,
            "worst_score": max(pose_r, lh_r, rh_r, zero_r),
        })

    n = len([r for r in rows if r["quality_status"] != "missing"])
    valid = [r for r in rows if r["quality_status"] != "missing"]
    def avg(k: str) -> float:
        return round(sum(r[k] for r in valid) / n, 4) if n else 0.0

    summary = {
        "total_videos": len(rows),
        "videos_with_data": n,
        "videos_missing_metadata": missing_meta,
        "total_sampled_frames": sum(r.get("timesteps", 0) or 0 for r in valid),
        "avg_pose_missing_rate": avg("pose_missing_rate"),
        "avg_left_hand_missing_rate": avg("left_hand_missing_rate"),
        "avg_right_hand_missing_rate": avg("right_hand_missing_rate"),
        "avg_all_zero_rate": avg("all_zero_rate"),
        "n_good": sum(1 for r in valid if r["quality_status"] == "good"),
        "n_warning": sum(1 for r in valid if r["quality_status"] == "warning"),
        "n_bad": sum(1 for r in valid if r["quality_status"] == "bad"),
        "n_critical": sum(1 for r in valid if r["quality_status"] == "critical"),
    }
    return {"summary": summary, "rows": rows}


def video_detail(outputs_root: str, project_dir: str) -> Optional[Dict]:
    p = os.path.join(outputs_root, project_dir)
    if not os.path.isdir(p):
        return None
    manifest = None
    qr = None
    for fn in os.listdir(p):
        if fn.startswith("manifest_") and fn.endswith(".json"):
            manifest = _safe_load(os.path.join(p, fn))
    reports_dir = os.path.join(p, "reports")
    if os.path.isdir(reports_dir):
        for fn in os.listdir(reports_dir):
            if fn.startswith("quality_report_") and fn.endswith(".json"):
                qr = _safe_load(os.path.join(reports_dir, fn))
    grid_rel = (manifest or {}).get("outputs", {}).get("grid") if manifest else None
    return {
        "project_dir": project_dir,
        "manifest": manifest,
        "quality_report": qr,
        "grid_url": f"/files/{project_dir}/{grid_rel}" if grid_rel else None,
        "file_url_prefix": f"/files/{project_dir}/",
    }


def export_csv(rows: List[Dict]) -> bytes:
    buf = io.StringIO()
    fields = [
        "project_dir", "video_name", "label", "timesteps",
        "total_original_frames", "pose_missing_rate", "left_hand_missing_rate",
        "right_hand_missing_rate", "all_zero_rate", "quality_status",
    ]
    w = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return buf.getvalue().encode("utf-8-sig")
