"""Phase 8 — Overlay (temporal motion) renderer.

Generates overlay visualizations from already-extracted MediaPipe outputs:
  - skeleton overlay (pose over time)
  - wrist trajectory
  - fingertip trajectory
  - RGB + overlay (RGB background + skeleton/trajectories)

NPZ layout (T, 110): 55 keypoints * (x,y) normalized to [-1, 1]
  [0:13]   upper-body pose (idx 9 = left_wrist, idx 10 = right_wrist,
                            idx 7 = left_elbow, idx 8 = right_elbow,
                            idx 5 = left_shoulder, idx 6 = right_shoulder)
  [13:34]  left hand  (0=wrist, 4=thumb_tip, 8=index_tip, 12=middle_tip)
  [34:55]  right hand (same offsets)
"""
from __future__ import annotations
import json
import os
import uuid
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import safe_label as _safe_label, safe_video_name as _safe_vid


# ---------------------- landmark catalog ----------------------
LM_POSE_BASE = 0
LM_LH_BASE = 13
LM_RH_BASE = 34

LANDMARKS: Dict[str, int] = {
    "left_shoulder": LM_POSE_BASE + 5,
    "right_shoulder": LM_POSE_BASE + 6,
    "left_elbow": LM_POSE_BASE + 7,
    "right_elbow": LM_POSE_BASE + 8,
    "left_wrist": LM_POSE_BASE + 9,
    "right_wrist": LM_POSE_BASE + 10,
    "left_thumb_tip": LM_LH_BASE + 4,
    "left_index_tip": LM_LH_BASE + 8,
    "left_middle_tip": LM_LH_BASE + 12,
    "right_thumb_tip": LM_RH_BASE + 4,
    "right_index_tip": LM_RH_BASE + 8,
    "right_middle_tip": LM_RH_BASE + 12,
}

POSE_EDGES = [
    (0, 1), (0, 2), (1, 3), (2, 4), (5, 6), (5, 7), (7, 9),
    (6, 8), (8, 10), (5, 11), (6, 12), (11, 12),
]
HAND_EDGES = [
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (0, 9), (9, 10), (10, 11), (11, 12),
    (0, 13), (13, 14), (14, 15), (15, 16),
    (0, 17), (17, 18), (18, 19), (19, 20),
]

LANDMARK_PRESETS: Dict[str, List[str]] = {
    "large_trajectory": ["left_wrist", "right_wrist", "left_elbow", "right_elbow"],
    "fine_temporal": ["left_wrist", "right_wrist",
                       "left_index_tip", "right_index_tip",
                       "left_thumb_tip", "right_thumb_tip"],
    "occlusion_hand": ["left_wrist", "right_wrist"],  # + full hand drawn from skeleton
    "full_pose": ["left_shoulder", "right_shoulder",
                   "left_elbow", "right_elbow",
                   "left_wrist", "right_wrist"],
}

GRADIENTS: Dict[str, List[Tuple[int, int, int]]] = {
    "warm":  [(255, 255, 180), (255, 200, 80), (255, 120, 40), (220, 30, 30)],
    "cool":  [(60, 120, 220), (60, 200, 160), (220, 220, 60), (220, 60, 60)],
    "viridis": [(68, 1, 84), (59, 82, 139), (33, 145, 140), (94, 201, 98), (253, 231, 37)],
    "left_blue_right_red": [(80, 130, 230), (220, 80, 80)],  # used per-hand
}


@dataclass
class OverlayStyle:
    color_mode: str = "gradient"            # gradient | single | lr_split
    gradient_name: str = "warm"
    single_color: Tuple[int, int, int] = (220, 30, 30)
    alpha_start: float = 0.25
    alpha_end: float = 1.0
    show_start_marker: bool = True
    show_end_marker: bool = True
    show_arrow_direction: bool = True
    line_width: int = 3
    trajectory_width: int = 3
    point_radius: int = 4
    marker_radius: int = 8
    background_mode: str = "rgb_middle"      # rgb_middle | rgb_first | rgb_index | white | dark | transparent
    background_rgb_index: int = -1            # used when background_mode == rgb_index
    background_opacity: float = 0.85          # for RGB backgrounds
    show_title: bool = True
    show_legend: bool = True
    show_temporal_legend: bool = True


@dataclass
class FrameSelection:
    mode: str = "evenly"                     # evenly | preset | manual
    count: int = 9
    sample_indices: List[int] = field(default_factory=list)


@dataclass
class OverlayConfig:
    overlay_type: str = "skeleton"            # skeleton | wrist_path | fingertip_path | rgb_overlay
    layout_mode: str = "single"               # single | multi_row | side_by_side | hybrid
    landmark_preset: str = "fine_temporal"
    selected_landmarks: List[str] = field(default_factory=list)
    frame_selection: FrameSelection = field(default_factory=FrameSelection)
    style: OverlayStyle = field(default_factory=OverlayStyle)
    title: str = ""
    caption_en: str = ""
    caption_vi: str = ""


# ---------------------- helpers ----------------------
def _interp_color(grad: List[Tuple[int, int, int]], t: float) -> Tuple[int, int, int]:
    if len(grad) == 1:
        return grad[0]
    t = max(0.0, min(1.0, t))
    pos = t * (len(grad) - 1)
    i = int(pos)
    f = pos - i
    if i >= len(grad) - 1:
        return grad[-1]
    a, b = grad[i], grad[i + 1]
    return (int(a[0] + (b[0] - a[0]) * f),
            int(a[1] + (b[1] - a[1]) * f),
            int(a[2] + (b[2] - a[2]) * f))


def _color_for(style: OverlayStyle, t: float, side: Optional[str] = None) -> Tuple[int, int, int]:
    if style.color_mode == "single":
        return style.single_color
    if style.color_mode == "lr_split" and side in ("left", "right"):
        if side == "left":
            return _interp_color([(180, 210, 255), (30, 80, 220)], t)
        return _interp_color([(255, 200, 200), (200, 30, 30)], t)
    grad = GRADIENTS.get(style.gradient_name, GRADIENTS["warm"])
    return _interp_color(grad, t)


def _alpha_for(style: OverlayStyle, t: float) -> int:
    a = style.alpha_start + (style.alpha_end - style.alpha_start) * t
    return max(0, min(255, int(round(a * 255))))


def _denormalize(seq_frame: np.ndarray, w: int, h: int) -> np.ndarray:
    """(110,) -> (55,2) int px in image space. (-1,1) -> (0,1) -> px."""
    pts = seq_frame.reshape(55, 2).astype(np.float32)
    pts = (pts + 1.0) * 0.5
    pts = np.clip(np.nan_to_num(pts), 0.0, 1.0)
    out = np.empty_like(pts, dtype=np.int32)
    out[:, 0] = np.rint(pts[:, 0] * (w - 1)).astype(np.int32)
    out[:, 1] = np.rint(pts[:, 1] * (h - 1)).astype(np.int32)
    return out


def _valid_mask(seq_frame: np.ndarray) -> np.ndarray:
    pts = seq_frame.reshape(55, 2)
    n = (pts + 1.0) * 0.5
    return ~((n[:, 0] <= 1e-4) & (n[:, 1] <= 1e-4))


# ---------------------- data loading ----------------------
def load_source(outputs_root: str, project_dir: str) -> Dict:
    """Load manifest, NPZ and useful paths for one extracted video folder."""
    p = os.path.join(outputs_root, project_dir)
    if not os.path.isdir(p):
        raise FileNotFoundError(f"Project not found: {project_dir}")
    manifest = None
    for fn in os.listdir(p):
        if fn.startswith("manifest_") and fn.endswith(".json"):
            with open(os.path.join(p, fn), encoding="utf-8") as f:
                manifest = json.load(f)
            break
    if not manifest:
        raise FileNotFoundError(f"manifest not found in {project_dir}")

    npz_rel = manifest["outputs"].get("npz")
    if not npz_rel:
        raise FileNotFoundError("npz not in manifest outputs")
    npz = np.load(os.path.join(p, npz_rel))
    x = np.asarray(npz["x"])  # (T, 110)

    # quality report
    qr = None
    qr_rel = manifest["outputs"].get("quality_report_json")
    if qr_rel:
        try:
            with open(os.path.join(p, qr_rel), encoding="utf-8") as f:
                qr = json.load(f)
        except Exception:
            pass

    return {
        "project_dir": project_dir,
        "abs_dir": p,
        "manifest": manifest,
        "kp": x,
        "T": int(x.shape[0]),
        "quality_report": qr,
    }


def select_frames(T: int, fs: FrameSelection) -> List[int]:
    if fs.mode == "manual" and fs.sample_indices:
        return [int(i) for i in fs.sample_indices if 0 <= int(i) < T]
    if fs.mode == "preset":
        preset = fs.sample_indices or [0, 8, 16, 24, 32, 40, 48, 56, 63]
        return [int(i) for i in preset if 0 <= int(i) < T]
    # evenly
    n = max(2, min(int(fs.count or 9), T))
    return [int(round(i * (T - 1) / (n - 1))) for i in range(n)]


# ---------------------- canvas / background ----------------------
def _frame_path(source: Dict, sample_idx: int, kind: str = "rgb") -> Optional[str]:
    frames = source["manifest"].get("frames", [])
    if not (0 <= sample_idx < len(frames)):
        return None
    rel = frames[sample_idx].get(f"{kind}_file")
    if not rel:
        return None
    p = os.path.join(source["abs_dir"], rel)
    return p if os.path.exists(p) else None


def _make_background(source: Dict, sel_idx: List[int], style: OverlayStyle,
                      w: int, h: int) -> Image.Image:
    mode = style.background_mode
    rgb_path = None
    if mode == "rgb_middle":
        rgb_path = _frame_path(source, sel_idx[len(sel_idx) // 2])
    elif mode == "rgb_first":
        rgb_path = _frame_path(source, sel_idx[0])
    elif mode == "rgb_index":
        idx = style.background_rgb_index
        if idx < 0 or idx >= source["T"]:
            idx = sel_idx[len(sel_idx) // 2]
        rgb_path = _frame_path(source, idx)
    if rgb_path:
        try:
            img = Image.open(rgb_path).convert("RGB").resize((w, h))
            if style.background_opacity < 1.0:
                # blend with white
                white = Image.new("RGB", (w, h), (255, 255, 255))
                img = Image.blend(white, img, style.background_opacity)
            return img
        except Exception:
            pass
    if mode == "dark":
        return Image.new("RGB", (w, h), (18, 18, 24))
    if mode == "transparent":
        return Image.new("RGBA", (w, h), (255, 255, 255, 0)).convert("RGB")
    return Image.new("RGB", (w, h), (255, 255, 255))


# ---------------------- drawing primitives ----------------------
def _draw_arrow(draw: ImageDraw.ImageDraw, p1, p2, color, width):
    import math
    draw.line([p1, p2], fill=color, width=width)
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    ang = math.atan2(dy, dx)
    size = max(10, width * 3)
    for off in (math.pi - 0.4, math.pi + 0.4):
        ex = p2[0] + size * math.cos(ang + off)
        ey = p2[1] + size * math.sin(ang + off)
        draw.line([p2, (ex, ey)], fill=color, width=width)


def _draw_marker(draw: ImageDraw.ImageDraw, p, color, r, filled):
    bb = [p[0] - r, p[1] - r, p[0] + r, p[1] + r]
    if filled:
        draw.ellipse(bb, fill=color, outline=(0, 0, 0))
    else:
        draw.ellipse(bb, outline=color, width=max(2, r // 2))


def _draw_skeleton(overlay: Image.Image, pts: np.ndarray, valid: np.ndarray,
                    color: Tuple[int, int, int], alpha: int, lw: int, pr: int,
                    draw_hands: bool = True):
    layer = Image.new("RGBA", overlay.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    rgba = (*color, alpha)

    def _line(a, b):
        if valid[a] and valid[b]:
            d.line([tuple(pts[a]), tuple(pts[b])], fill=rgba, width=lw)

    for a, b in POSE_EDGES:
        _line(a, b)
    if draw_hands:
        for a, b in HAND_EDGES:
            _line(LM_LH_BASE + a, LM_LH_BASE + b)
            _line(LM_RH_BASE + a, LM_RH_BASE + b)
    for i in range(55):
        if not valid[i]:
            continue
        r = pr if i < 13 else max(1, pr - 1)
        d.ellipse([pts[i][0] - r, pts[i][1] - r,
                   pts[i][0] + r, pts[i][1] + r], fill=rgba)
    overlay.alpha_composite(layer)


# ---------------------- per-mode renderers ----------------------
def render_single_overlay(source: Dict, cfg: OverlayConfig,
                           w: int = 960, h: int = 720) -> Image.Image:
    sel_idx = select_frames(source["T"], cfg.frame_selection)
    bg = _make_background(source, sel_idx, cfg.style, w, h).convert("RGBA")
    n = max(1, len(sel_idx))

    if cfg.overlay_type in ("skeleton", "rgb_overlay"):
        for i, fidx in enumerate(sel_idx):
            t = i / max(1, n - 1)
            color = _color_for(cfg.style, t)
            alpha = _alpha_for(cfg.style, t)
            frame = source["kp"][fidx]
            pts = _denormalize(frame, w, h)
            valid = _valid_mask(frame)
            draw_hands = "hand" in (cfg.landmark_preset or "") or cfg.overlay_type == "rgb_overlay" or \
                          any("hand" in lm or "tip" in lm for lm in cfg.selected_landmarks)
            _draw_skeleton(bg, pts, valid, color, alpha,
                           cfg.style.line_width, cfg.style.point_radius,
                           draw_hands=draw_hands)

    if cfg.overlay_type in ("wrist_path", "fingertip_path", "rgb_overlay"):
        # choose which landmarks to trace
        if cfg.overlay_type == "wrist_path":
            trace_names = ["left_wrist", "right_wrist"]
        elif cfg.overlay_type == "fingertip_path":
            trace_names = ["left_index_tip", "right_index_tip",
                           "left_thumb_tip", "right_thumb_tip"]
        else:
            trace_names = cfg.selected_landmarks or ["left_wrist", "right_wrist"]

        layer = Image.new("RGBA", bg.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        for name in trace_names:
            if name not in LANDMARKS:
                continue
            lm = LANDMARKS[name]
            side = "left" if name.startswith("left") else "right"
            pts_seq: List[Tuple[int, int]] = []
            for fidx in sel_idx:
                frame = source["kp"][fidx]
                valid = _valid_mask(frame)
                if not valid[lm]:
                    continue
                p = _denormalize(frame, w, h)[lm]
                pts_seq.append((int(p[0]), int(p[1])))
            if len(pts_seq) < 2:
                continue
            # draw path with per-segment gradient
            for i in range(len(pts_seq) - 1):
                t = (i + 1) / (len(pts_seq) - 1)
                color = _color_for(cfg.style, t, side=side)
                alpha = _alpha_for(cfg.style, t)
                d.line([pts_seq[i], pts_seq[i + 1]],
                       fill=(*color, alpha), width=cfg.style.trajectory_width)
            # markers
            if cfg.style.show_start_marker:
                _draw_marker(d, pts_seq[0],
                              (*_color_for(cfg.style, 0.0, side=side), 255),
                              cfg.style.marker_radius, filled=False)
            if cfg.style.show_end_marker:
                _draw_marker(d, pts_seq[-1],
                              (*_color_for(cfg.style, 1.0, side=side), 255),
                              cfg.style.marker_radius, filled=True)
            if cfg.style.show_arrow_direction and len(pts_seq) >= 2:
                _draw_arrow(d, pts_seq[-2], pts_seq[-1],
                            (*_color_for(cfg.style, 1.0, side=side), 255),
                            cfg.style.trajectory_width)
        bg.alpha_composite(layer)

    # title + legend
    bg = _annotate(bg, source, cfg, sel_idx)
    return bg.convert("RGB")


def _annotate(canvas: Image.Image, source: Dict, cfg: OverlayConfig,
               sel_idx: List[int]) -> Image.Image:
    d = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 18)
        font_sm = ImageFont.truetype("DejaVuSans.ttf", 12)
    except Exception:
        font = ImageFont.load_default()
        font_sm = ImageFont.load_default()

    title = cfg.title or f"{source['manifest'].get('video_name', '')} — {source['manifest'].get('label', '')}"
    if cfg.style.show_title and title:
        d.rectangle([0, 0, canvas.width, 32], fill=(0, 0, 0, 160))
        d.text((10, 6), title, fill=(255, 255, 255, 255), font=font)

    if cfg.style.show_legend:
        legend = f"type: {cfg.overlay_type} • frames: {len(sel_idx)} ({','.join(str(i) for i in sel_idx[:9])}{'…' if len(sel_idx) > 9 else ''})"
        d.text((10, canvas.height - 22), legend, fill=(0, 0, 0, 200), font=font_sm)

    if cfg.style.show_temporal_legend:
        # small bar: Early -> Late
        bar_w, bar_h = 220, 10
        x0 = canvas.width - bar_w - 14
        y0 = canvas.height - 28
        for i in range(bar_w):
            t = i / (bar_w - 1)
            c = _color_for(cfg.style, t)
            a = _alpha_for(cfg.style, t)
            d.line([(x0 + i, y0), (x0 + i, y0 + bar_h)], fill=(*c, a))
        d.text((x0, y0 - 14), "Early", fill=(0, 0, 0, 200), font=font_sm)
        d.text((x0 + bar_w - 28, y0 - 14), "Late", fill=(0, 0, 0, 200), font=font_sm)
    return canvas


# ---------------------- multi-source layouts ----------------------
def render_multi_row(sources: List[Dict], cfg: OverlayConfig,
                      tile_w: int = 880, tile_h: int = 640, pad: int = 16) -> Image.Image:
    tiles = [render_single_overlay(s, cfg, w=tile_w, h=tile_h).convert("RGB") for s in sources]
    W = tile_w + 2 * pad
    H = pad + sum(t.height + pad for t in tiles)
    canvas = Image.new("RGB", (W, H), (245, 245, 248))
    y = pad
    for t in tiles:
        canvas.paste(t, (pad, y))
        y += t.height + pad
    return canvas


def render_side_by_side_variants(source: Dict, cfg: OverlayConfig,
                                  types: List[str], tile_w: int = 640,
                                  tile_h: int = 480, pad: int = 14) -> Image.Image:
    tiles = []
    for t in types:
        c2 = OverlayConfig(**{**asdict(cfg), "overlay_type": t})
        # cast back nested dataclasses
        c2.style = OverlayStyle(**asdict(cfg.style))
        c2.frame_selection = FrameSelection(**asdict(cfg.frame_selection))
        tiles.append(render_single_overlay(source, c2, w=tile_w, h=tile_h).convert("RGB"))
    cols = min(2, len(tiles))
    rows = (len(tiles) + cols - 1) // cols
    W = pad + cols * (tile_w + pad)
    H = pad + rows * (tile_h + pad)
    canvas = Image.new("RGB", (W, H), (245, 245, 248))
    for i, t in enumerate(tiles):
        r, c = divmod(i, cols)
        canvas.paste(t, (pad + c * (tile_w + pad), pad + r * (tile_h + pad)))
    return canvas


# ---------------------- project save / output ----------------------
def overlay_root(outputs_root: str) -> str:
    p = os.path.join(outputs_root, "_overlays")
    os.makedirs(p, exist_ok=True)
    return p


def make_project_id(sources: List[Dict], cfg: OverlayConfig) -> str:
    if len(sources) == 1:
        s = sources[0]
        base = f"overlay_{_safe_vid(s['manifest'].get('video_name',''))}_{_safe_label(s['manifest'].get('label',''))}_{cfg.overlay_type}"
    else:
        labels = "_vs_".join(_safe_label(s["manifest"].get("label", "")) for s in sources[:4])
        base = f"overlay_{labels}_{cfg.overlay_type}"
    return base + "_" + uuid.uuid4().hex[:6]


def save_outputs(outputs_root: str, project_id: str, img: Image.Image,
                  cfg: OverlayConfig, sources: List[Dict]) -> Dict:
    out_dir = os.path.join(overlay_root(outputs_root), project_id)
    os.makedirs(out_dir, exist_ok=True)
    png_path = os.path.join(out_dir, "overlay.png")
    jpg_path = os.path.join(out_dir, "overlay.jpg")
    img.save(png_path, "PNG")
    img.convert("RGB").save(jpg_path, "JPEG", quality=92)
    cfg_path = os.path.join(out_dir, "overlay_config.json")
    payload = {
        "overlay_project_id": project_id,
        "overlay_type": cfg.overlay_type,
        "layout_mode": cfg.layout_mode,
        "landmark_preset": cfg.landmark_preset,
        "selected_landmarks": cfg.selected_landmarks,
        "frame_selection": asdict(cfg.frame_selection),
        "style": asdict(cfg.style),
        "title": cfg.title,
        "caption_en": cfg.caption_en,
        "caption_vi": cfg.caption_vi,
        "source_items": [
            {
                "project_dir": s["project_dir"],
                "video_name": s["manifest"].get("video_name"),
                "label": s["manifest"].get("label"),
                "safe_label": s["manifest"].get("safe_label"),
            } for s in sources
        ],
    }
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    # metadata sidecar
    meta_path = os.path.join(out_dir, "overlay_metadata.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump({
            "size": img.size,
            "n_sources": len(sources),
            "sample_indices": select_frames(sources[0]["T"], cfg.frame_selection) if sources else [],
        }, f, indent=2)
    return {
        "overlay_project_id": project_id,
        "png_url": f"/files/_overlays/{project_id}/overlay.png",
        "jpg_url": f"/files/_overlays/{project_id}/overlay.jpg",
        "config_url": f"/files/_overlays/{project_id}/overlay_config.json",
        "config": payload,
    }


def build_pdf(outputs_root: str, project_id: str, sources: List[Dict],
               cfg: OverlayConfig) -> str:
    """Thesis-friendly PDF: title + figure + captions + settings + sources + QR."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.lib import colors as _c
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                     Image as RLImage, Table, TableStyle)
    from reportlab.lib.styles import getSampleStyleSheet

    out_dir = os.path.join(overlay_root(outputs_root), project_id)
    pdf_path = os.path.join(out_dir, "overlay.pdf")
    img_path = os.path.join(out_dir, "overlay.png")
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(pdf_path, pagesize=A4,
                            leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                            topMargin=1.5 * cm, bottomMargin=1.5 * cm)
    story = []
    title = cfg.title or f"Overlay — {cfg.overlay_type}"
    story.append(Paragraph(title, styles["Title"]))
    story.append(Spacer(1, 8))
    if os.path.exists(img_path):
        from PIL import Image as PI
        with PI.open(img_path) as im:
            iw, ih = im.size
        max_w = 17 * cm
        scale = min(1.0, max_w / iw)
        story.append(RLImage(img_path, width=iw * scale, height=ih * scale))
        story.append(Spacer(1, 8))
    if cfg.caption_en:
        story.append(Paragraph(f"<b>Caption (EN):</b> {cfg.caption_en}", styles["Normal"]))
    if cfg.caption_vi:
        story.append(Paragraph(f"<b>Chú thích (VI):</b> {cfg.caption_vi}", styles["Normal"]))
    story.append(Spacer(1, 8))
    sel_idx = select_frames(sources[0]["T"], cfg.frame_selection) if sources else []
    cfg_rows = [
        ["overlay_type", cfg.overlay_type],
        ["layout_mode", cfg.layout_mode],
        ["landmark_preset", cfg.landmark_preset],
        ["selected_landmarks", ", ".join(cfg.selected_landmarks) or "(default)"],
        ["sample_indices", ", ".join(str(i) for i in sel_idx)],
        ["color_mode", cfg.style.color_mode],
        ["gradient", cfg.style.gradient_name],
        ["alpha", f"{cfg.style.alpha_start} → {cfg.style.alpha_end}"],
        ["background", cfg.style.background_mode],
    ]
    t = Table(cfg_rows, colWidths=[5 * cm, 11 * cm])
    t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, _c.grey),
                            ("INNERGRID", (0, 0), (-1, -1), 0.25, _c.lightgrey),
                            ("FONTSIZE", (0, 0), (-1, -1), 9)]))
    story += [Paragraph("Overlay settings", styles["Heading2"]), t, Spacer(1, 10)]

    src_rows = [["video_name", "label", "T", "pose_miss", "lh_miss", "rh_miss"]]
    for s in sources:
        qr = s.get("quality_report") or {}
        src_rows.append([
            s["manifest"].get("video_name"), s["manifest"].get("label"),
            str(s["T"]),
            f"{(qr.get('pose_missing_rate') or 0):.3f}",
            f"{(qr.get('left_hand_missing_rate') or 0):.3f}",
            f"{(qr.get('right_hand_missing_rate') or 0):.3f}",
        ])
    t2 = Table(src_rows, repeatRows=1,
               colWidths=[3.5 * cm, 4 * cm, 1.5 * cm, 2.5 * cm, 2.5 * cm, 2.5 * cm])
    t2.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), _c.lightgrey),
                             ("FONTSIZE", (0, 0), (-1, -1), 8),
                             ("BOX", (0, 0), (-1, -1), 0.5, _c.grey),
                             ("INNERGRID", (0, 0), (-1, -1), 0.25, _c.lightgrey)]))
    story += [Paragraph("Source metadata + quality", styles["Heading2"]), t2]
    doc.build(story)
    return pdf_path


# ---------------------- top-level orchestration ----------------------
def _cfg_from_dict(d: Dict) -> OverlayConfig:
    style_d = d.get("style", {}) or {}
    fs_d = d.get("frame_selection", {}) or {}
    return OverlayConfig(
        overlay_type=d.get("overlay_type", "skeleton"),
        layout_mode=d.get("layout_mode", "single"),
        landmark_preset=d.get("landmark_preset", "fine_temporal"),
        selected_landmarks=list(d.get("selected_landmarks") or
                                LANDMARK_PRESETS.get(d.get("landmark_preset", "fine_temporal"), [])),
        frame_selection=FrameSelection(**{k: v for k, v in fs_d.items()
                                            if k in FrameSelection.__dataclass_fields__}),
        style=OverlayStyle(**{k: v for k, v in style_d.items()
                              if k in OverlayStyle.__dataclass_fields__}),
        title=d.get("title", ""),
        caption_en=d.get("caption_en", ""),
        caption_vi=d.get("caption_vi", ""),
    )


def create_overlay(outputs_root: str, payload: Dict) -> Dict:
    project_dirs = payload.get("project_dirs") or []
    if not project_dirs:
        raise ValueError("project_dirs required")
    cfg = _cfg_from_dict(payload.get("config", {}))
    sources = [load_source(outputs_root, pd) for pd in project_dirs]

    if cfg.layout_mode == "side_by_side":
        types = payload.get("variant_types") or ["skeleton", "wrist_path",
                                                    "fingertip_path", "rgb_overlay"]
        img = render_side_by_side_variants(sources[0], cfg, types)
    elif cfg.layout_mode == "multi_row" and len(sources) >= 2:
        img = render_multi_row(sources, cfg)
    else:
        img = render_single_overlay(sources[0], cfg)

    project_id = payload.get("overlay_project_id") or make_project_id(sources, cfg)
    out = save_outputs(outputs_root, project_id, img, cfg, sources)
    try:
        pdf_path = build_pdf(outputs_root, project_id, sources, cfg)
        out["pdf_url"] = f"/files/_overlays/{project_id}/overlay.pdf"
    except Exception as e:
        out["pdf_error"] = str(e)
    return out


def list_overlays(outputs_root: str) -> List[Dict]:
    root = overlay_root(outputs_root)
    items = []
    if not os.path.isdir(root):
        return items
    for name in sorted(os.listdir(root), reverse=True):
        p = os.path.join(root, name)
        if not os.path.isdir(p):
            continue
        cfg_path = os.path.join(p, "overlay_config.json")
        cfg = None
        if os.path.exists(cfg_path):
            try:
                with open(cfg_path, encoding="utf-8") as f:
                    cfg = json.load(f)
            except Exception:
                pass
        items.append({
            "overlay_project_id": name,
            "png_url": f"/files/_overlays/{name}/overlay.png",
            "jpg_url": f"/files/_overlays/{name}/overlay.jpg",
            "pdf_url": f"/files/_overlays/{name}/overlay.pdf" if os.path.exists(os.path.join(p, "overlay.pdf")) else None,
            "config_url": f"/files/_overlays/{name}/overlay_config.json" if os.path.exists(cfg_path) else None,
            "config": cfg,
        })
    return items


def load_project(outputs_root: str, project_id: str) -> Optional[Dict]:
    p = os.path.join(overlay_root(outputs_root), project_id, "overlay_config.json")
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def delete_project(outputs_root: str, project_id: str) -> bool:
    import shutil
    p = os.path.join(overlay_root(outputs_root), project_id)
    if not os.path.isdir(p):
        return False
    shutil.rmtree(p, ignore_errors=True)
    return True
