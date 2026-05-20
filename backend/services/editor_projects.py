"""Phase 7 — Editor project storage (stubs).

Saves editor project JSON locally under backend/outputs/_editor_projects/.
PNG/JPG/PDF export is handled client-side by Fabric.js + jsPDF for the MVP;
this module is kept as a hook for future server-side rendering.
"""
from __future__ import annotations
import os, json, uuid, base64
from datetime import datetime
from typing import Optional

EDITOR_DIR_NAME = "_editor_projects"


def _editor_dir(base_outputs: str) -> str:
    p = os.path.join(base_outputs, EDITOR_DIR_NAME)
    os.makedirs(p, exist_ok=True)
    return p


def save_project(base_outputs: str, project: dict) -> dict:
    pid = project.get("comparison_id") or uuid.uuid4().hex[:10]
    folder = os.path.join(_editor_dir(base_outputs), pid)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "project.json")
    project["_saved_at"] = datetime.utcnow().isoformat()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(project, f, ensure_ascii=False, indent=2)
    return {"project_id": pid, "path": path, "url": f"/files/{EDITOR_DIR_NAME}/{pid}/project.json"}


def load_project(base_outputs: str, project_id: str) -> Optional[dict]:
    path = os.path.join(_editor_dir(base_outputs), project_id, "project.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def export_image_from_dataurl(base_outputs: str, project_id: str, data_url: str, fmt: str = "png") -> dict:
    """Persist a client-rendered annotated image (data:image/...;base64,...)."""
    folder = os.path.join(_editor_dir(base_outputs), project_id)
    os.makedirs(folder, exist_ok=True)
    if "," in data_url:
        _, b64 = data_url.split(",", 1)
    else:
        b64 = data_url
    fname = f"annotated_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.{fmt}"
    path = os.path.join(folder, fname)
    with open(path, "wb") as f:
        f.write(base64.b64decode(b64))
    return {"path": path, "url": f"/files/{EDITOR_DIR_NAME}/{project_id}/{fname}"}


# TODO Phase 8: server-side PDF assembly with annotated image + metadata table.
