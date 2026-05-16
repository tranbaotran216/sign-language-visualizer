"""PDF report generator for comparison results using ReportLab."""
from __future__ import annotations
import os
from typing import List, Dict, Optional
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image as RLImage,
    Table, TableStyle, PageBreak,
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# Try register a Unicode font for Vietnamese
_FONT_NAME = "Helvetica"
for _p in (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "C:/Windows/Fonts/arial.ttf",
):
    if os.path.exists(_p):
        try:
            pdfmetrics.registerFont(TTFont("AppFont", _p))
            _FONT_NAME = "AppFont"
            break
        except Exception:
            pass


def build_pdf(
    out_path: str,
    comparison_image_path: str,
    caption_en: str,
    caption_vi: str,
    groups: List[Dict],
    layout: Dict,
    quality_reports: Optional[Dict[str, Dict]] = None,
    created_at: str = "",
):
    doc = SimpleDocTemplate(
        out_path, pagesize=A4,
        leftMargin=1.5 * cm, rightMargin=1.5 * cm,
        topMargin=1.5 * cm, bottomMargin=1.5 * cm,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("Title", parent=styles["Title"], fontName=_FONT_NAME, fontSize=18)
    body = ParagraphStyle("Body", parent=styles["Normal"], fontName=_FONT_NAME, fontSize=10, leading=14)
    h2 = ParagraphStyle("H2", parent=styles["Heading2"], fontName=_FONT_NAME, fontSize=13)

    story = []
    story.append(Paragraph("Vietnamese Isolated Sign Language Comparison Report", title_style))
    story.append(Spacer(1, 8))

    if comparison_image_path and os.path.exists(comparison_image_path):
        # fit width
        from PIL import Image as PILImage
        with PILImage.open(comparison_image_path) as im:
            iw, ih = im.size
        max_w = 17 * cm
        scale = min(1.0, max_w / iw)
        story.append(RLImage(comparison_image_path, width=iw * scale, height=ih * scale))
        story.append(Spacer(1, 8))

    story.append(Paragraph(f"<b>Caption (EN):</b> {caption_en}", body))
    story.append(Paragraph(f"<b>Chú thích (VI):</b> {caption_vi}", body))
    story.append(Spacer(1, 8))

    # Summary
    story.append(Paragraph("Comparison summary", h2))
    summary_data = [
        ["Number of videos", str(len(groups))],
        ["Frames per video", ", ".join(str(len(g.get("selected_frames", []))) for g in groups)],
        ["Created at", created_at or ""],
        ["Layout tile_width", str(layout.get("tile_width"))],
        ["Layout rgb_height", str(layout.get("rgb_height"))],
        ["Layout pose_height", str(layout.get("pose_height"))],
    ]
    t = Table(summary_data, colWidths=[5 * cm, 11 * cm])
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), _FONT_NAME),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
    ]))
    story.append(t)
    story.append(Spacer(1, 12))

    # Per-video metadata
    story.append(Paragraph("Per-video metadata", h2))
    for g in groups:
        story.append(Paragraph(
            f"<b>{g.get('video_name', '')}</b> — ground truth: {g.get('label', '')} "
            f"(safe: {g.get('safe_label', '')}) — source: {g.get('source', '?')}",
            body,
        ))
    story.append(Spacer(1, 10))

    # Per-frame metadata table
    story.append(Paragraph("Per-frame metadata", h2))
    rows = [["Video", "Label", "sample_idx", "orig_idx", "rgb", "pose", "pair"]]
    for g in groups:
        for f in g.get("selected_frames", []):
            rows.append([
                g.get("video_name", ""), g.get("label", ""),
                str(f.get("sample_index", "")), str(f.get("original_frame_index", "")),
                os.path.basename(f.get("rgb_path", "") or ""),
                os.path.basename(f.get("pose_path", "") or ""),
                os.path.basename(f.get("pair_path", "") or ""),
            ])
    t = Table(rows, colWidths=[2 * cm, 3 * cm, 1.6 * cm, 1.6 * cm, 3 * cm, 3 * cm, 3 * cm])
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), _FONT_NAME),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
    ]))
    story.append(t)
    story.append(Spacer(1, 12))

    if quality_reports:
        story.append(PageBreak())
        story.append(Paragraph("MediaPipe quality report", h2))
        for vname, qr in quality_reports.items():
            story.append(Paragraph(f"<b>{vname}</b>", body))
            data = [
                ["total_original_frames", str(qr.get("total_original_frames", ""))],
                ["timesteps", str(qr.get("timesteps", ""))],
                ["pose_missing_rate", f"{qr.get('pose_missing_rate', 0):.3f}"],
                ["left_hand_missing_rate", f"{qr.get('left_hand_missing_rate', 0):.3f}"],
                ["right_hand_missing_rate", f"{qr.get('right_hand_missing_rate', 0):.3f}"],
                ["all_zero_rate", f"{qr.get('all_zero_rate', 0):.3f}"],
                ["all_zero", str(qr.get("all_zero", ""))],
            ]
            t = Table(data, colWidths=[5 * cm, 11 * cm])
            t.setStyle(TableStyle([
                ("FONTNAME", (0, 0), (-1, -1), _FONT_NAME),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
            ]))
            story.append(t)
            story.append(Spacer(1, 8))

    story.append(Spacer(1, 12))
    story.append(Paragraph("Notes", h2))
    story.append(Paragraph("• Missing landmarks are filled with zeros in the NPZ output.", body))
    story.append(Paragraph("• Coordinates are normalized to [-1, 1] (per-axis).", body))

    doc.build(story)
