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
from services import dataset_qa as dsqa
from services import model_results as mres

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
def _render_and_persist(payload: Dict, comparison_id: Optional[str] = None) -> Dict:
    groups = payload.get("groups", [])
    if len(groups) < 2 or len(groups) > 5:
        raise HTTPException(400, "Cần 2 đến 5 nhóm video để so sánh.")
    layout = LayoutSettings(**{k: v for k, v in payload.get("layout", {}).items()
                                if k in LayoutSettings.__dataclass_fields__})

    labels = [g.get("label", "") for g in groups]
    cap_en = payload.get("caption_en") or _cap_en(labels)
    cap_vi = payload.get("caption_vi") or _cap_vi(labels)
    safe_labels = [_safe_label(l) for l in labels]
    annotations = payload.get("annotations", []) or []

    if not comparison_id:
        comparison_id = "_vs_".join(safe_labels) + "_" + uuid.uuid4().hex[:6]
    out_dir = os.path.join(COMPARISONS_DIR, comparison_id)
    os.makedirs(out_dir, exist_ok=True)

    img = render_comparison(groups, layout, base_dir=OUTPUTS_DIR)
    img = apply_annotations(img, annotations)
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
        out_path=pdf_path, comparison_image_path=img_path,
        caption_en=cap_en, caption_vi=cap_vi,
        groups=[{**g, "safe_label": _safe_label(g.get("label", ""))} for g in groups],
        layout=payload.get("layout", {}),
        quality_reports=quality_reports, created_at=_now(),
    )

    config_full = {
        "comparison_id": comparison_id, "labels": labels, "safe_labels": safe_labels,
        "caption_en": cap_en, "caption_vi": cap_vi,
        "layout": layout.__dict__, "groups": groups,
        "annotations": annotations,
        "created_at": _now(),
    }
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(config_full, f, ensure_ascii=False, indent=2)

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
        "caption_en": cap_en, "caption_vi": cap_vi,
        "config": config_full,
    }


@app.post("/api/compare")
async def create_comparison(payload: Dict = Body(...)):
    return _render_and_persist(payload)


@app.post("/api/compare/{comparison_id}/rerender")
async def rerender_comparison(comparison_id: str, payload: Dict = Body(...)):
    out_dir = os.path.join(COMPARISONS_DIR, comparison_id)
    if not os.path.isdir(out_dir):
        raise HTTPException(404, "Comparison not found")
    return _render_and_persist(payload, comparison_id=comparison_id)


@app.get("/api/comparisons")
def list_comparisons():
    items = []
    if not os.path.isdir(COMPARISONS_DIR):
        return {"items": []}
    for name in sorted(os.listdir(COMPARISONS_DIR), reverse=True):
        p = os.path.join(COMPARISONS_DIR, name)
        if not os.path.isdir(p):
            continue
        cfg_path = os.path.join(p, "config.json")
        cfg = None
        if os.path.exists(cfg_path):
            try:
                with open(cfg_path, encoding="utf-8") as f:
                    cfg = json.load(f)
            except Exception:
                pass
        files = os.listdir(p)
        img = next((f for f in files if f.endswith(".jpg")), None)
        pdf = next((f for f in files if f.endswith(".pdf")), None)
        base_url = f"/files/_comparisons/{name}"
        items.append({
            "comparison_id": name,
            "created_at": (cfg or {}).get("created_at") or datetime.fromtimestamp(os.path.getctime(p)).isoformat(timespec="seconds"),
            "labels": (cfg or {}).get("labels", []),
            "image_url": f"{base_url}/{img}" if img else None,
            "pdf_url": f"{base_url}/{pdf}" if pdf else None,
            "config_url": f"{base_url}/config.json" if os.path.exists(cfg_path) else None,
            "zip_url": f"{base_url}/comparison_outputs.zip" if os.path.exists(os.path.join(p, "comparison_outputs.zip")) else None,
            "n_groups": len((cfg or {}).get("groups", [])),
        })
    return {"items": items}


@app.delete("/api/comparisons/{comparison_id}")
def delete_comparison(comparison_id: str):
    if "/" in comparison_id or ".." in comparison_id:
        raise HTTPException(400, "Invalid")
    p = os.path.join(COMPARISONS_DIR, comparison_id)
    if not os.path.isdir(p):
        raise HTTPException(404, "Not found")
    shutil.rmtree(p, ignore_errors=True)
    return {"ok": True}


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
        "comparison_id": comparison_id, "config": cfg,
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


# ================================================================ DELETE ALL HISTORY (Task A)
@app.delete("/api/history/all")
def delete_all_history():
    """Safely wipe all generated outputs inside backend/outputs/.

    Only removes directories whose resolved absolute path lives strictly
    inside OUTPUTS_DIR. Does not touch source code, env files, uploads,
    or anything outside backend/outputs.
    """
    outputs_abs = os.path.realpath(OUTPUTS_DIR)
    deleted = 0
    errors: List[str] = []
    if not os.path.isdir(outputs_abs):
        return {"success": True, "deleted_count": 0, "message": "Outputs folder is empty."}

    for name in os.listdir(outputs_abs):
        target = os.path.join(outputs_abs, name)
        try:
            real = os.path.realpath(target)
            # safety: must remain inside outputs_abs
            if not real.startswith(outputs_abs + os.sep) and real != outputs_abs:
                errors.append(f"skip unsafe: {name}")
                continue
            if real == outputs_abs:
                continue
            if os.path.isdir(real):
                shutil.rmtree(real, ignore_errors=True)
            else:
                os.remove(real)
            deleted += 1
        except Exception as e:
            errors.append(f"{name}: {e}")

    # recreate the conventional sub-folder for next comparisons
    os.makedirs(COMPARISONS_DIR, exist_ok=True)
    return {
        "success": True,
        "deleted_count": deleted,
        "errors": errors,
        "message": "Deleted all local history outputs.",
    }


# ================================================================ DATASET QA (Phase 5)
@app.get("/api/dataset-qa/summary")
def dataset_qa_summary():
    return dsqa.scan_dataset(OUTPUTS_DIR)


@app.get("/api/dataset-qa/video/{project_dir}")
def dataset_qa_video(project_dir: str):
    if "/" in project_dir or ".." in project_dir:
        raise HTTPException(400, "Invalid path")
    detail = dsqa.video_detail(OUTPUTS_DIR, project_dir)
    if not detail:
        raise HTTPException(404, "Not found")
    return detail


@app.get("/api/dataset-qa/export/csv")
def dataset_qa_export_csv():
    data = dsqa.scan_dataset(OUTPUTS_DIR)
    csv_bytes = dsqa.export_csv(data["rows"])
    path = os.path.join(OUTPUTS_DIR, "_qa_dataset_quality_summary.csv")
    with open(path, "wb") as f:
        f.write(csv_bytes)
    return FileResponse(path, media_type="text/csv", filename="dataset_quality_summary.csv")


@app.get("/api/dataset-qa/export/pdf")
def dataset_qa_export_pdf():
    """Minimal PDF report listing summary + per-video rates."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.lib import colors as _c
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet

    data = dsqa.scan_dataset(OUTPUTS_DIR)
    s = data["summary"]
    path = os.path.join(OUTPUTS_DIR, "_qa_dataset_quality_report.pdf")
    doc = SimpleDocTemplate(path, pagesize=A4, leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                            topMargin=1.5 * cm, bottomMargin=1.5 * cm)
    styles = getSampleStyleSheet()
    story = [Paragraph("Dataset Quality Report", styles["Title"]), Spacer(1, 10)]
    rows = [[k, str(v)] for k, v in s.items()]
    t = Table(rows, colWidths=[7 * cm, 9 * cm])
    t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, _c.grey),
                            ("INNERGRID", (0, 0), (-1, -1), 0.25, _c.lightgrey),
                            ("FONTSIZE", (0, 0), (-1, -1), 9)]))
    story += [t, Spacer(1, 14), Paragraph("Per-video quality", styles["Heading2"])]
    header = ["video_name", "label", "pose%", "LH%", "RH%", "zero%", "status"]
    body = [header]
    for r in data["rows"]:
        body.append([
            r.get("video_name"), r.get("label"),
            f"{(r.get('pose_missing_rate') or 0) * 100:.1f}",
            f"{(r.get('left_hand_missing_rate') or 0) * 100:.1f}",
            f"{(r.get('right_hand_missing_rate') or 0) * 100:.1f}",
            f"{(r.get('all_zero_rate') or 0) * 100:.1f}",
            r.get("quality_status"),
        ])
    t2 = Table(body, repeatRows=1, colWidths=[4 * cm, 4 * cm, 1.5 * cm, 1.5 * cm, 1.5 * cm, 1.5 * cm, 2 * cm])
    t2.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 7),
                             ("BOX", (0, 0), (-1, -1), 0.5, _c.grey),
                             ("INNERGRID", (0, 0), (-1, -1), 0.25, _c.lightgrey),
                             ("BACKGROUND", (0, 0), (-1, 0), _c.lightgrey)]))
    story.append(t2)
    doc.build(story)
    return FileResponse(path, media_type="application/pdf", filename="dataset_quality_report.pdf")


# ================================================================ MODEL RESULTS (Phase 6)
@app.post("/api/model-results/import")
async def model_results_import(csv_file: UploadFile = File(...)):
    raw = await csv_file.read()
    try:
        return mres.import_csv(raw, csv_file.filename or "predictions.csv")
    except Exception as e:
        raise HTTPException(400, f"Không đọc được CSV: {e}")


@app.post("/api/model-results/{ds_id}/map-columns")
def model_results_map(ds_id: str, payload: Dict = Body(...)):
    try:
        return mres.apply_mapping(ds_id, payload.get("mapping", {}), OUTPUTS_DIR)
    except KeyError:
        raise HTTPException(404, "Dataset not found")


@app.get("/api/model-results/{ds_id}/summary")
def model_results_summary(ds_id: str):
    if not mres.get_dataset(ds_id):
        raise HTTPException(404, "Dataset not found")
    return mres.summary(ds_id)


@app.get("/api/model-results/{ds_id}/rows")
def model_results_rows(ds_id: str, filter: str = "all", q: str = ""):
    if not mres.get_dataset(ds_id):
        raise HTTPException(404, "Dataset not found")
    return {"rows": mres.filter_rows(ds_id, filter, q)}


@app.get("/api/model-results/{ds_id}/class-report")
def model_results_class_report(ds_id: str):
    if not mres.get_dataset(ds_id):
        raise HTTPException(404, "Dataset not found")
    return mres.class_report(ds_id)


@app.get("/api/model-results/{ds_id}/export/csv")
def model_results_export_csv(ds_id: str, filter: str = "all"):
    if not mres.get_dataset(ds_id):
        raise HTTPException(404, "Dataset not found")
    data = mres.export_csv(ds_id, filter)
    path = os.path.join(OUTPUTS_DIR, f"_predictions_{ds_id[:8]}_{filter}.csv")
    with open(path, "wb") as f:
        f.write(data)
    return FileResponse(path, media_type="text/csv", filename=f"predictions_{filter}.csv")


@app.post("/api/model-results/{ds_id}/generate-error-analysis")
def model_results_error_analysis(ds_id: str, payload: Dict = Body(...)):
    """Use comparison renderer to generate an error-analysis figure for a wrong prediction.

    payload: { row_id: int, gt_project_dir?: str, pred_project_dir?: str }

    The frontend resolves which extraction folders to pair (one ground-truth
    sample, one predicted-class sample). Backend re-uses the comparison
    pipeline to render the figure + PDF.
    """
    ds = mres.get_dataset(ds_id)
    if not ds:
        raise HTTPException(404, "Dataset not found")
    rows = {r["row_id"]: r for r in ds.get("rows", [])}
    row = rows.get(int(payload.get("row_id", -1)))
    if not row:
        raise HTTPException(404, "Row not found")
    groups = []
    for pdir, lbl in [
        (payload.get("gt_project_dir") or row["matched_output"], f"GT: {row['ground_truth']}"),
        (payload.get("pred_project_dir"), f"Pred: {row['prediction']}"),
    ]:
        if not pdir:
            continue
        # load manifest to grab first few frames
        p = os.path.join(OUTPUTS_DIR, pdir)
        if not os.path.isdir(p):
            continue
        manifest = None
        for fn in os.listdir(p):
            if fn.startswith("manifest_") and fn.endswith(".json"):
                with open(os.path.join(p, fn), encoding="utf-8") as f:
                    manifest = json.load(f)
                break
        if not manifest:
            continue
        frames = manifest.get("frames", [])[:6]
        sel = [{
            "sample_index": f["sample_index"],
            "original_frame_index": f["original_frame_index"],
            "rgb_path": f"{pdir}/{f['rgb_file']}",
            "pose_path": f"{pdir}/{f['pose_file']}",
            "pair_path": f"{pdir}/{f['pair_file']}",
        } for f in frames]
        groups.append({
            "video_name": manifest.get("video_name"),
            "label": lbl,
            "source": "extraction",
            "project_dir": pdir,
            "selected_frames": sel,
        })
    if len(groups) < 2:
        raise HTTPException(400, "Cần cả ground-truth và predicted folders đã extract.")
    cap_vi = f"Phân tích lỗi: mô hình dự đoán '{row['prediction']}' thay vì '{row['ground_truth']}'."
    cap_en = f"Error analysis: model predicted '{row['prediction']}' instead of '{row['ground_truth']}'."
    payload_render = {"groups": groups, "caption_en": cap_en, "caption_vi": cap_vi,
                      "layout": {}, "include_quality_report": True, "annotations": []}
    return _render_and_persist(payload_render)


# ============================================================
# Phase 7 — Editor projects (annotated comparison editor)
# ============================================================
from services import editor_projects as _editor

@app.post("/api/editor/save-project")
def editor_save_project(project: dict = Body(...)):
    return _editor.save_project(OUTPUTS_DIR, project)

@app.get("/api/editor/load-project/{project_id}")
def editor_load_project(project_id: str):
    p = _editor.load_project(OUTPUTS_DIR, project_id)
    if not p:
        raise HTTPException(404, "project not found")
    return p

@app.post("/api/editor/export")
def editor_export(payload: dict = Body(...)):
    """Persist a client-rendered annotated image. Body: {project_id, data_url, format}.
    PDF export is done client-side; here we only mirror the PNG/JPG into outputs."""
    pid = payload.get("project_id") or "ad_hoc"
    fmt = payload.get("format", "png")
    data_url = payload.get("data_url")
    if not data_url:
        raise HTTPException(400, "data_url required")
    return _editor.export_image_from_dataurl(OUTPUTS_DIR, pid, data_url, fmt)


# ============================================================
# Phase 8 — Overlay (temporal motion visualization)
# ============================================================
from services import overlay_renderer as _ov


@app.get("/api/overlay/presets")
def overlay_presets():
    return {
        "landmark_presets": _ov.LANDMARK_PRESETS,
        "gradients": list(_ov.GRADIENTS.keys()),
        "all_landmarks": list(_ov.LANDMARKS.keys()),
        "overlay_types": ["skeleton", "wrist_path", "fingertip_path", "rgb_overlay"],
        "layout_modes": ["single", "multi_row", "side_by_side"],
        "background_modes": ["rgb_middle", "rgb_first", "rgb_index", "white", "dark", "transparent"],
    }


@app.post("/api/overlay/create")
def overlay_create(payload: Dict = Body(...)):
    try:
        return _ov.create_overlay(OUTPUTS_DIR, payload)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/overlay/{project_id}/rerender")
def overlay_rerender(project_id: str, payload: Dict = Body(...)):
    payload = {**payload, "overlay_project_id": project_id}
    return _ov.create_overlay(OUTPUTS_DIR, payload)


@app.get("/api/overlay")
def overlay_list():
    return {"items": _ov.list_overlays(OUTPUTS_DIR)}


@app.get("/api/overlay/{project_id}")
def overlay_get(project_id: str):
    cfg = _ov.load_project(OUTPUTS_DIR, project_id)
    if not cfg:
        raise HTTPException(404, "overlay not found")
    return cfg


@app.delete("/api/overlay/{project_id}")
def overlay_delete(project_id: str):
    if "/" in project_id or ".." in project_id:
        raise HTTPException(400, "invalid id")
    if not _ov.delete_project(OUTPUTS_DIR, project_id):
        raise HTTPException(404, "not found")
    return {"ok": True}
