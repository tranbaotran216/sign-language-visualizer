"""Render comparison image from groups of frames using Pillow."""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
import math
from PIL import Image, ImageDraw, ImageFont


@dataclass
class LayoutSettings:
    tile_width: int = 240
    rgb_height: int = 145
    pose_height: int = 150
    cell_gap: int = 12
    row_gap: int = 42
    top_margin: int = 30
    bottom_margin: int = 30
    side_margin: int = 30
    title_font_size: int = 28
    frame_label_font_size: int = 18
    background_color: str = "#ffffff"
    text_color: str = "#000000"
    include_titles: bool = True
    include_frame_labels: bool = True


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def _resolve_path(file: str, base_dir: Optional[str]) -> Optional[str]:
    if os.path.isabs(file) and os.path.exists(file):
        return file
    if base_dir:
        p = os.path.join(base_dir, file)
        if os.path.exists(p):
            return p
    return file if os.path.exists(file) else None


def _build_cell(frame: Dict, layout: LayoutSettings, base_dir: Optional[str]) -> Image.Image:
    """Build a single cell containing RGB on top + pose on bottom.

    Accepts either a 'pair_path' (already vertically stacked) or 'rgb_path' + 'pose_path'.
    """
    w = layout.tile_width
    rgb_h, pose_h = layout.rgb_height, layout.pose_height
    cell = Image.new("RGB", (w, rgb_h + pose_h), layout.background_color)

    pair_path = _resolve_path(frame.get("pair_path", ""), base_dir) if frame.get("pair_path") else None
    if pair_path:
        try:
            im = Image.open(pair_path).convert("RGB")
            # split top/bottom
            iw, ih = im.size
            half = ih // 2
            top = im.crop((0, 0, iw, half)).resize((w, rgb_h))
            bot = im.crop((0, half, iw, ih)).resize((w, pose_h))
            cell.paste(top, (0, 0))
            cell.paste(bot, (0, rgb_h))
            return cell
        except Exception:
            pass

    rgb_path = _resolve_path(frame.get("rgb_path", ""), base_dir) if frame.get("rgb_path") else None
    pose_path = _resolve_path(frame.get("pose_path", ""), base_dir) if frame.get("pose_path") else None
    if rgb_path:
        try:
            cell.paste(Image.open(rgb_path).convert("RGB").resize((w, rgb_h)), (0, 0))
        except Exception:
            pass
    if pose_path:
        try:
            cell.paste(Image.open(pose_path).convert("RGB").resize((w, pose_h)), (0, rgb_h))
        except Exception:
            pass
    return cell


def render_comparison(
    groups: List[Dict],
    layout: LayoutSettings,
    base_dir: Optional[str] = None,
    title_template: str = "{video_name} - Ground truth: {label}",
) -> Image.Image:
    """groups = [{video_name, label, title?, selected_frames:[{rgb_path|pose_path|pair_path, sample_index, original_frame_index}]}]"""
    if not groups:
        return Image.new("RGB", (100, 100), layout.background_color)

    n_cols = max(len(g.get("selected_frames", [])) for g in groups)
    cell_w = layout.tile_width
    cell_h = layout.rgb_height + layout.pose_height
    title_font = _load_font(layout.title_font_size)
    label_font = _load_font(layout.frame_label_font_size)

    title_h = layout.title_font_size + 12 if layout.include_titles else 0
    flabel_h = layout.frame_label_font_size + 8 if layout.include_frame_labels else 0

    row_h = title_h + cell_h + flabel_h
    total_w = layout.side_margin * 2 + n_cols * cell_w + (n_cols - 1) * layout.cell_gap
    total_h = layout.top_margin + len(groups) * row_h + (len(groups) - 1) * layout.row_gap + layout.bottom_margin

    canvas = Image.new("RGB", (total_w, total_h), layout.background_color)
    draw = ImageDraw.Draw(canvas)

    y = layout.top_margin
    for g in groups:
        title = g.get("title") or title_template.format(
            video_name=g.get("video_name", ""), label=g.get("label", "")
        )
        if layout.include_titles:
            tw = draw.textlength(title, font=title_font)
            draw.text(((total_w - tw) / 2, y), title, fill=layout.text_color, font=title_font)

        cy = y + title_h
        x = layout.side_margin
        for f in g.get("selected_frames", []):
            cell = _build_cell(f, layout, base_dir)
            canvas.paste(cell, (x, cy))
            if layout.include_frame_labels:
                lbl = f"Frame {f.get('sample_index', '?')}"
                tw = draw.textlength(lbl, font=label_font)
                draw.text(
                    (x + (cell_w - tw) / 2, cy + cell_h + 4),
                    lbl, fill=layout.text_color, font=label_font,
                )
            x += cell_w + layout.cell_gap
        y += row_h + layout.row_gap

    return canvas


def caption_en(labels: List[str]) -> str:
    quoted = [f"'{l}'" for l in labels]
    if len(quoted) == 2:
        joined = " and ".join(quoted)
    else:
        joined = ", ".join(quoted[:-1]) + f", and {quoted[-1]}"
    return f"Comparison between signs {joined} using RGB and MediaPipe landmark visualization."


def caption_vi(labels: List[str]) -> str:
    quoted = [f"‘{l}’" for l in labels]
    joined = ", ".join(quoted[:-1]) + f" và {quoted[-1]}" if len(quoted) > 1 else quoted[0]
    return f"So sánh trực quan giữa các ký hiệu {joined} bằng ảnh RGB và landmark MediaPipe."
