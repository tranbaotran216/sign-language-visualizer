"""KLTN VSL Visualization Tool — FastAPI backend (local only)."""
from __future__ import annotations
import json
import os
import shutil
import threading
import time
import uuid
import zipfile
from datetime import datetime
from typing import List, Optional, Dict

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from services import safe_label as _safe_label, safe_video_name as _safe_vid
from services.csv_metadata import load_csv, detect_columns, build_mapping, preview_rows, lookup_label
from services.extract_mediapipe import ExtractConfig, extract_video
from services.compare_renderer import (
    LayoutSettings, render_comparison, apply_annotations,
    caption_en as _cap_en, caption_vi as _cap_vi,
)
from services.pdf_report import build_pdf
from services.filename_parser import parse_filename

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
OUTPUTS_DIR = os.path.join(BASE_DIR, "outputs")
COMPARISONS_DIR = os.path.join(OUTPUTS_DIR, "_comparisons")
os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(OUTPUTS_DIR, exist_ok=True)
os.makedirs(COMPARISONS_DIR, exist_ok=True)

app = FastAPI(title="KLTN VSL Visualization Tool")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# Serve outputs as static so frontend can preview/download by URL
app.mount("/files", StaticFiles(directory=OUTPUTS_DIR), name="files")

# ---------------------------------------------------------------- in-memory state
_metadata_store: Dict[str, Dict] = {}  # metadata_id -> {mapping, columns}
_batches: Dict[str, Dict] = {}         # batch_id -> {jobs:[...]}
_lock = threading.Lock()


# ---------------------------------------------------------------- helpers
def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _file_url(project_dir: str, rel: str) -> str:
    rel = rel.replace("\\", "/")
    return f"/files/{project_dir}/{rel}"


# ================================================================ METADATA
@app.post("/api/metadata/upload")
async def metadata_upload(csv_file: UploadFile = File(...)):
    raw = await csv_file.read()
    try:
        df = load_csv(raw)
    except Exception as e:
        raise HTTPException(400, f"Không đọc được CSV: {e}")
    id_col, label_col = detect_columns(df)
    mapping = build_mapping(df, id_col, label_col) if (id_col and label_col) else {}
    metadata_id = uuid.uuid4().hex
    _metadata_store[metadata_id] = {
        "filename": csv_file.filename,
        "columns": list(df.columns.astype(str)),
        "id_col": id_col,
        "label_col": label_col,
        "mapping": mapping,
    }
    return {
        "metadata_id": metadata_id,
        "filename": csv_file.filename,
        "detected_columns": {"id_col": id_col, "label_col": label_col},
        "all_columns": list(df.columns.astype(str)),
        "preview_rows": preview_rows(df),
        "mapping_status": "ok" if (id_col and label_col) else "needs_manual_columns",
        "mapping_size": len(mapping),
    }


@app.post("/api/metadata/{metadata_id}/columns")
def metadata_set_columns(metadata_id: str, payload: Dict = Body(...)):
    md = _metadata_store.get(metadata_id)
    if not md:
        raise HTTPException(404, "Metadata not found")
    md["id_col"] = payload.get("id_col") or md["id_col"]
    md["label_col"] = payload.get("label_col") or md["label_col"]
    return {"ok": True}


@app.get("/api/metadata/{metadata_id}/lookup")
def metadata_lookup(metadata_id: str, filename: str):
    md = _metadata_store.get(metadata_id)
    if not md:
        raise HTTPException(404, "Metadata not found")
    vid, lbl = lookup_label(md["mapping"], filename)
    return {"video_id": vid, "label": lbl}


# ================================================================ EXTRACT
class ExtractOverride(BaseModel):
    original_filename: Optional[str] = None
    video_id: Optional[str] = None
    label: Optional[str] = None


def _run_batch(batch_id: str, jobs: List[Dict], cfg: ExtractConfig):
    for job in jobs:
        with _lock:
            job["status"] = "processing"
            job["progress"] = 0.0
        try:
            def cb(p):
                with _lock:
                    job["progress"] = p

            manifest = extract_video(
                video_path=job["video_path"],
                video_name=job["video_id"],
                label=job["label"],
                outputs_root=OUTPUTS_DIR,
                config=cfg,
                progress_cb=cb,
            )
            project_dir = manifest["project_dir"]
            out_urls = {k: _file_url(project_dir, v) for k, v in manifest["outputs"].items()}
            with _lock:
                job["status"] = "completed"
                job["progress"] = 1.0
                job["manifest"] = manifest
                job["project_dir"] = project_dir
                job["output_urls"] = out_urls
                job["quality_report_summary"] = manifest.get("quality_summary", {})
        except Exception as e:
            with _lock:
                job["status"] = "failed"
                job["error"] = str(e)


@app.post("/api/extract/batch")
async def extract_batch(
    videos: List[UploadFile] = File(...),
    config: str = Form("{}"),
    metadata_id: Optional[str] = Form(None),
):
    if len(videos) == 0 or len(videos) > 5:
        raise HTTPException(400, "Số video phải từ 1 tới 5.")
    try:
        cfg_dict = json.loads(config) if config else {}
    except Exception:
        cfg_dict = {}
    overrides = {o["original_filename"]: o for o in cfg_dict.pop("per_video_overrides", [])} if "per_video_overrides" in cfg_dict else {}
    cfg = ExtractConfig(**{k: v for k, v in cfg_dict.items() if k in ExtractConfig.__dataclass_fields__})

    batch_id = uuid.uuid4().hex
    sess_dir = os.path.join(UPLOADS_DIR, batch_id)
    os.makedirs(sess_dir, exist_ok=True)

    md = _metadata_store.get(metadata_id) if metadata_id else None
    mapping = md["mapping"] if md else {}

    jobs = []
    for v in videos:
        fname = v.filename or "video.mp4"
        dst = os.path.join(sess_dir, fname)
        with open(dst, "wb") as f:
            shutil.copyfileobj(v.file, f)

        ov = overrides.get(fname, {})
        vid = ov.get("video_id")
        lbl = ov.get("label")
        if (not vid or not lbl) and mapping:
            m_vid, m_lbl = lookup_label(mapping, fname)
            if not vid:
                vid = m_vid or os.path.splitext(fname)[0].split("_")[0]
            if not lbl:
                lbl = m_lbl or os.path.splitext(fname)[0]
        if not vid:
            vid = os.path.splitext(fname)[0].split("_")[0]
        if not lbl:
            lbl = os.path.splitext(fname)[0]

        jobs.append({
            "job_id": uuid.uuid4().hex,
            "original_filename": fname,
            "video_id": vid,
            "label": lbl,
            "video_path": dst,
            "status": "queued",
            "progress": 0.0,
        })

    _batches[batch_id] = {"jobs": jobs, "created_at": _now()}
    threading.Thread(target=_run_batch, args=(batch_id, jobs, cfg), daemon=True).start()

    return {
        "batch_id": batch_id,
        "jobs": [
            {"job_id": j["job_id"], "original_filename": j["original_filename"],
             "video_id": j["video_id"], "label": j["label"]}
            for j in jobs
        ],
    }


@app.get("/api/extract/batch/{batch_id}")
def extract_batch_status(batch_id: str):
    b = _batches.get(batch_id)
    if not b:
        raise HTTPException(404, "Batch not found")
    with _lock:
        statuses = [j["status"] for j in b["jobs"]]
        if all(s == "completed" for s in statuses):
            batch_status = "completed"
        elif any(s == "failed" for s in statuses) and all(s in ("completed", "failed") for s in statuses):
            batch_status = "completed_with_errors"
        elif any(s == "processing" for s in statuses):
            batch_status = "processing"
        else:
            batch_status = "queued"
        return {
            "batch_id": batch_id,
            "batch_status": batch_status,
            "jobs": [
                {
                    "job_id": j["job_id"],
                    "status": j["status"],
                    "progress": j["progress"],
                    "original_filename": j["original_filename"],
                    "video_id": j["video_id"],
                    "label": j["label"],
                    "error": j.get("error"),
                    "manifest": j.get("manifest"),
                    "project_dir": j.get("project_dir"),
                    "output_urls": j.get("output_urls"),
                    "quality_report_summary": j.get("quality_report_summary"),
                }
                for j in b["jobs"]
            ],
        }


# ================================================================ OUTPUTS
@app.get("/api/outputs")
def list_outputs():
    items = []
    for name in sorted(os.listdir(OUTPUTS_DIR)):
        if name.startswith("_") or name.startswith("."):
            continue
        p = os.path.join(OUTPUTS_DIR, name)
        if not os.path.isdir(p):
            continue
        manifest = None
        for fn in os.listdir(p):
            if fn.startswith("manifest_") and fn.endswith(".json"):
                try:
                    with open(os.path.join(p, fn), encoding="utf-8") as f:
                        manifest = json.load(f)
                except Exception:
                    pass
                break
        created = datetime.fromtimestamp(os.path.getctime(p)).isoformat(timespec="seconds")
        items.append({
            "project_dir": name,
            "created_at": created,
            "video_name": manifest.get("video_name") if manifest else name,
            "label": manifest.get("label") if manifest else "",
            "safe_label": manifest.get("safe_label") if manifest else "",
            "grid_url": _file_url(name, manifest["outputs"]["grid"]) if manifest else None,
            "zip_url": _file_url(name, f"outputs_{name}.zip") if os.path.exists(os.path.join(p, f"outputs_{name}.zip")) else None,
            "manifest": manifest,
        })
    return {"items": items}


@app.delete("/api/outputs/{project_dir}")
def delete_output(project_dir: str):
    if "/" in project_dir or ".." in project_dir:
        raise HTTPException(400, "Invalid path")
    p = os.path.join(OUTPUTS_DIR, project_dir)
    if not os.path.isdir(p):
        raise HTTPException(404, "Not found")
    shutil.rmtree(p, ignore_errors=True)
    return {"ok": True}


# ================================================================ COMPARE
@app.post("/api/compare")
async def create_comparison(payload: Dict = Body(...)):
    """payload = {
        groups: [{video_name, label, safe_label?, source?,
                  selected_frames:[{sample_index, original_frame_index,
                                    rgb_path?, pose_path?, pair_path?}]}],
        layout: {...}, caption_en?, caption_vi?,
        include_quality_report: bool
    }
    Paths are relative to backend/outputs/ (or absolute).
    """
    groups = payload.get("groups", [])
    if len(groups) < 2 or len(groups) > 5:
        raise HTTPException(400, "Cần 2 đến 5 nhóm video để so sánh.")
    layout = LayoutSettings(**{k: v for k, v in payload.get("layout", {}).items()
                                if k in LayoutSettings.__dataclass_fields__})

    labels = [g.get("label", "") for g in groups]
    cap_en = payload.get("caption_en") or _cap_en(labels)
    cap_vi = payload.get("caption_vi") or _cap_vi(labels)

    safe_labels = [_safe_label(l) for l in labels]
    comparison_id = "_vs_".join(safe_labels) + "_" + uuid.uuid4().hex[:6]
    out_dir = os.path.join(COMPARISONS_DIR, comparison_id)
    os.makedirs(out_dir, exist_ok=True)

    # Render image. base_dir = OUTPUTS_DIR so paths like "A0009_doc_ac/frames/pair/..." resolve.
    img = render_comparison(groups, layout, base_dir=OUTPUTS_DIR)
    img_name = "_vs_".join(safe_labels) + ".jpg"
    png_name = "_vs_".join(safe_labels) + ".png"
    pdf_name = "_vs_".join(safe_labels) + ".pdf"
    cfg_name = "config.json"
    img_path = os.path.join(out_dir, img_name)
    png_path = os.path.join(out_dir, png_name)
    pdf_path = os.path.join(out_dir, pdf_name)
    cfg_path = os.path.join(out_dir, cfg_name)
    img.save(img_path, "JPEG", quality=92)
    img.save(png_path, "PNG")

    # Collect quality reports if requested
    quality_reports = {}
    if payload.get("include_quality_report", True):
        for g in groups:
            sv = _safe_vid(g.get("video_name", ""))
            sl = _safe_label(g.get("label", ""))
            qp = os.path.join(OUTPUTS_DIR, f"{sv}_{sl}", "reports", f"quality_report_{sv}_{sl}.json")
            if os.path.exists(qp):
                with open(qp, encoding="utf-8") as f:
                    quality_reports[g.get("video_name", "")] = json.load(f)

    build_pdf(
        out_path=pdf_path,
        comparison_image_path=img_path,
        caption_en=cap_en, caption_vi=cap_vi,
        groups=[{**g, "safe_label": _safe_label(g.get("label", ""))} for g in groups],
        layout=payload.get("layout", {}),
        quality_reports=quality_reports,
        created_at=_now(),
    )

    config_full = {
        "comparison_id": comparison_id,
        "labels": labels,
        "safe_labels": safe_labels,
        "caption_en": cap_en, "caption_vi": cap_vi,
        "layout": layout.__dict__,
        "groups": groups,
    }
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(config_full, f, ensure_ascii=False, indent=2)

    # zip
    zip_path = os.path.join(out_dir, "comparison_outputs.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for fn in (img_name, png_name, pdf_name, cfg_name):
            zf.write(os.path.join(out_dir, fn), fn)

    base_url = f"/files/_comparisons/{comparison_id}"
    return {
        "comparison_id": comparison_id,
        "comparison_image_url": f"{base_url}/{img_name}",
        "comparison_png_url": f"{base_url}/{png_name}",
        "comparison_pdf_url": f"{base_url}/{pdf_name}",
        "comparison_config_json_url": f"{base_url}/{cfg_name}",
        "comparison_zip_url": f"{base_url}/comparison_outputs.zip",
        "caption_en": cap_en,
        "caption_vi": cap_vi,
    }


@app.get("/api/compare/{comparison_id}")
def get_comparison(comparison_id: str):
    out_dir = os.path.join(COMPARISONS_DIR, comparison_id)
    if not os.path.isdir(out_dir):
        raise HTTPException(404, "Comparison not found")
    cfg_path = os.path.join(out_dir, "config.json")
    cfg = None
    if os.path.exists(cfg_path):
        with open(cfg_path, encoding="utf-8") as f:
            cfg = json.load(f)
    files = os.listdir(out_dir)
    img = next((f for f in files if f.endswith(".jpg")), None)
    pdf = next((f for f in files if f.endswith(".pdf")), None)
    base_url = f"/files/_comparisons/{comparison_id}"
    return {
        "comparison_id": comparison_id,
        "config": cfg,
        "image_url": f"{base_url}/{img}" if img else None,
        "pdf_url": f"{base_url}/{pdf}" if pdf else None,
    }


# ================================================================ UPLOAD frames for manual comparison
@app.post("/api/compare/upload-frames")
async def compare_upload_frames(files: List[UploadFile] = File(...)):
    """Stash uploaded extracted-frame images under outputs/_uploads/<session>/ so the
    comparison endpoint can reference them by relative path."""
    sess = uuid.uuid4().hex[:10]
    dest = os.path.join(OUTPUTS_DIR, "_uploads", sess)
    os.makedirs(dest, exist_ok=True)
    parsed = []
    for f in files:
        p = os.path.join(dest, f.filename)
        with open(p, "wb") as fp:
            shutil.copyfileobj(f.file, fp)
        meta = parse_filename(f.filename) or {"filename": f.filename}
        meta["path"] = os.path.relpath(p, OUTPUTS_DIR).replace("\\", "/")
        meta["url"] = f"/files/{meta['path']}"
        parsed.append(meta)
    return {"session": sess, "files": parsed}


@app.get("/")
def root():
    return {"app": "KLTN VSL Visualization Tool", "docs": "/docs"}
