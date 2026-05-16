"""MediaPipe Holistic extraction service.

Extracts 13 upper-body pose + 21 left hand + 21 right hand landmarks (x,y only),
normalized to [-1, 1]. Total dim = 110.

Produces per-video output folder under backend/outputs/{video_name}_{safe_label}/.
"""
from __future__ import annotations
import json
import os
import shutil
import zipfile
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Callable

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

try:
    import mediapipe as mp  # type: ignore
    _HAS_MP = True
except Exception:  # pragma: no cover
    mp = None
    _HAS_MP = False

from .filename_parser import parse_filename  # noqa: F401
from . import safe_label as _safe_label, safe_video_name as _safe_vid

POSE_INDICES = [0, 2, 5, 7, 8, 11, 12, 13, 14, 15, 16, 23, 24]
N_POSE = len(POSE_INDICES)
N_HAND = 21
KP_DIM = (N_POSE + N_HAND + N_HAND) * 2  # 110


# --------------------------------------------------------------- sampling
def sample_indices(total: int, timesteps: int, mode: str = "iter") -> List[int]:
    if total <= 0:
        return [0] * timesteps
    if mode == "iter":
        return [int(round(i * (total - 1) / max(1, timesteps - 1))) for i in range(timesteps)]
    if mode == "mid":
        center = total / 2
        half = timesteps / 2
        start = max(0, int(center - half))
        end = min(total, start + timesteps)
        idxs = list(range(start, end))
        while len(idxs) < timesteps:
            idxs.append(min(total - 1, idxs[-1] + 1) if idxs else 0)
        return idxs[:timesteps]
    if mode == "mix":
        half = timesteps // 2
        a = [int(round(i * (total - 1) / max(1, half - 1))) for i in range(half)]
        center = total / 2
        b = [min(total - 1, max(0, int(center - (timesteps - half) / 2 + j))) for j in range(timesteps - half)]
        return a + b
    return [int(round(i * (total - 1) / max(1, timesteps - 1))) for i in range(timesteps)]


# --------------------------------------------------------------- normalization
def _norm(v: float) -> float:
    v = max(0.0, min(1.0, float(v)))
    return (v - 0.5) * 2.0


def _landmarks_to_vec(results) -> np.ndarray:
    vec = np.zeros(KP_DIM, dtype=np.float32)
    has_pose = has_lh = has_rh = False

    if results.pose_landmarks is not None:
        for j, idx in enumerate(POSE_INDICES):
            lm = results.pose_landmarks.landmark[idx]
            vec[j * 2 + 0] = _norm(lm.x)
            vec[j * 2 + 1] = _norm(lm.y)
        has_pose = True

    off = N_POSE * 2
    if results.left_hand_landmarks is not None:
        for j in range(N_HAND):
            lm = results.left_hand_landmarks.landmark[j]
            vec[off + j * 2 + 0] = _norm(lm.x)
            vec[off + j * 2 + 1] = _norm(lm.y)
        has_lh = True

    off = (N_POSE + N_HAND) * 2
    if results.right_hand_landmarks is not None:
        for j in range(N_HAND):
            lm = results.right_hand_landmarks.landmark[j]
            vec[off + j * 2 + 0] = _norm(lm.x)
            vec[off + j * 2 + 1] = _norm(lm.y)
        has_rh = True

    return vec, has_pose, has_lh, has_rh


def _draw_pose_image(results, w: int, h: int, frame_bgr=None) -> np.ndarray:
    """Render landmarks on a black canvas (or over the frame if provided)."""
    if frame_bgr is None:
        canvas = np.zeros((h, w, 3), dtype=np.uint8)
    else:
        canvas = cv2.resize(frame_bgr, (w, h)).copy()
        canvas = (canvas * 0.25).astype(np.uint8)

    if not _HAS_MP:
        return canvas
    drawing = mp.solutions.drawing_utils
    styles = mp.solutions.drawing_styles
    holistic = mp.solutions.holistic
    if results.pose_landmarks:
        drawing.draw_landmarks(
            canvas, results.pose_landmarks, holistic.POSE_CONNECTIONS,
            landmark_drawing_spec=styles.get_default_pose_landmarks_style())
    if results.left_hand_landmarks:
        drawing.draw_landmarks(
            canvas, results.left_hand_landmarks, holistic.HAND_CONNECTIONS,
            landmark_drawing_spec=styles.get_default_hand_landmarks_style())
    if results.right_hand_landmarks:
        drawing.draw_landmarks(
            canvas, results.right_hand_landmarks, holistic.HAND_CONNECTIONS,
            landmark_drawing_spec=styles.get_default_hand_landmarks_style())
    return canvas


# --------------------------------------------------------------- config
@dataclass
class ExtractConfig:
    timesteps: int = 64
    sampling_mode: str = "iter"
    timeout: int = 120
    tile_w: int = 160
    tile_h: int = 120
    grid_cols: int = 8
    save_rgb: bool = True
    save_pose: bool = True
    save_pair: bool = True
    save_grid: bool = True
    save_pose_video: bool = True
    save_pair_video: bool = True
    generate_npz: bool = True
    generate_quality_report: bool = True
    overwrite: bool = True


def _ensure(path: str):
    os.makedirs(path, exist_ok=True)


def _write_jpg(path: str, img_bgr: np.ndarray):
    cv2.imwrite(path, img_bgr, [cv2.IMWRITE_JPEG_QUALITY, 92])


def _make_pair(rgb_bgr: np.ndarray, pose_bgr: np.ndarray, w: int, h: int) -> np.ndarray:
    rgb_r = cv2.resize(rgb_bgr, (w, h))
    pose_r = cv2.resize(pose_bgr, (w, h))
    return np.vstack([rgb_r, pose_r])


def _make_grid(imgs: List[np.ndarray], cols: int) -> np.ndarray:
    if not imgs:
        return np.zeros((10, 10, 3), dtype=np.uint8)
    h, w = imgs[0].shape[:2]
    rows = (len(imgs) + cols - 1) // cols
    canvas = np.full((rows * h, cols * w, 3), 255, dtype=np.uint8)
    for i, im in enumerate(imgs):
        r, c = i // cols, i % cols
        if im.shape[:2] != (h, w):
            im = cv2.resize(im, (w, h))
        canvas[r * h:(r + 1) * h, c * w:(c + 1) * w] = im
    return canvas


# --------------------------------------------------------------- main entry
def extract_video(
    video_path: str,
    video_name: str,
    label: str,
    outputs_root: str,
    config: ExtractConfig,
    progress_cb: Optional[Callable[[float], None]] = None,
) -> Dict:
    """Run extraction on a single video. Returns manifest dict."""
    safe_lbl = _safe_label(label)
    safe_vid = _safe_vid(video_name)
    base = os.path.join(outputs_root, f"{safe_vid}_{safe_lbl}")
    if config.overwrite and os.path.isdir(base):
        shutil.rmtree(base, ignore_errors=True)
    _ensure(base)
    _ensure(os.path.join(base, "npz"))
    _ensure(os.path.join(base, "frames", "rgb"))
    _ensure(os.path.join(base, "frames", "pose"))
    _ensure(os.path.join(base, "frames", "pair"))
    _ensure(os.path.join(base, "preview"))
    _ensure(os.path.join(base, "videos"))
    _ensure(os.path.join(base, "reports"))

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Không thể mở video: {video_path}")
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    sampled = sample_indices(total, config.timesteps, config.sampling_mode)

    # read sampled frames (sequentially for reliability)
    wanted = sorted(set(sampled))
    frames_map: Dict[int, np.ndarray] = {}
    i = 0
    wi = 0
    while wi < len(wanted):
        target = wanted[wi]
        while i < target:
            ok, _ = cap.read()
            if not ok:
                break
            i += 1
        ok, frame = cap.read()
        if not ok:
            break
        frames_map[target] = frame
        i += 1
        wi += 1
    cap.release()

    # Mediapipe
    if _HAS_MP:
        holistic = mp.solutions.holistic.Holistic(
            static_image_mode=False, model_complexity=1,
            enable_segmentation=False, refine_face_landmarks=False,
        )
    else:
        holistic = None

    keypoints = np.zeros((config.timesteps, KP_DIM), dtype=np.float32)
    frame_records: List[Dict] = []
    pair_imgs: List[np.ndarray] = []
    pose_imgs_for_vid: List[np.ndarray] = []
    pair_imgs_for_vid: List[np.ndarray] = []

    for si, orig_idx in enumerate(sampled):
        frame = frames_map.get(orig_idx)
        if frame is None:
            # blank fallback
            frame = np.zeros((config.tile_h, config.tile_w, 3), dtype=np.uint8)
            has_pose = has_lh = has_rh = False
            pose_img = np.zeros_like(frame)
        else:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            if holistic is not None:
                res = holistic.process(rgb)
                vec, has_pose, has_lh, has_rh = _landmarks_to_vec(res)
                keypoints[si] = vec
                pose_img = _draw_pose_image(res, config.tile_w, config.tile_h, frame_bgr=frame)
            else:
                has_pose = has_lh = has_rh = False
                pose_img = np.zeros((config.tile_h, config.tile_w, 3), dtype=np.uint8)

        rgb_resized = cv2.resize(frame, (config.tile_w, config.tile_h))
        pair_img = _make_pair(frame, pose_img, config.tile_w, config.tile_h)

        suffix = f"{safe_vid}_{safe_lbl}_{si:03d}_{orig_idx:06d}"
        rgb_file = f"frames/rgb/rgb_{suffix}.jpg"
        pose_file = f"frames/pose/pose_{suffix}.jpg"
        pair_file = f"frames/pair/pair_{suffix}.jpg"

        if config.save_rgb:
            _write_jpg(os.path.join(base, rgb_file), rgb_resized)
        if config.save_pose:
            _write_jpg(os.path.join(base, pose_file), pose_img)
        if config.save_pair:
            _write_jpg(os.path.join(base, pair_file), pair_img)

        pair_imgs.append(pair_img)
        pose_imgs_for_vid.append(pose_img)
        pair_imgs_for_vid.append(pair_img)

        is_zero = bool(np.all(keypoints[si] == 0))
        frame_records.append({
            "sample_index": si,
            "original_frame_index": int(orig_idx),
            "has_pose": has_pose,
            "has_left_hand": has_lh,
            "has_right_hand": has_rh,
            "is_all_zero": is_zero,
            "rgb_file": rgb_file,
            "pose_file": pose_file,
            "pair_file": pair_file,
        })

        if progress_cb and config.timesteps:
            progress_cb((si + 1) / config.timesteps)

    if holistic is not None:
        holistic.close()

    # grid preview
    grid_rel = f"preview/grid_{safe_vid}_{safe_lbl}.jpg"
    if config.save_grid:
        grid_img = _make_grid(pair_imgs, config.grid_cols)
        _write_jpg(os.path.join(base, grid_rel), grid_img)

    # videos
    pose_video_rel = f"videos/pose_{safe_vid}_{safe_lbl}.mp4"
    pair_video_rel = f"videos/pair_{safe_vid}_{safe_lbl}.mp4"
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    if config.save_pose_video and pose_imgs_for_vid:
        h, w = pose_imgs_for_vid[0].shape[:2]
        vw = cv2.VideoWriter(os.path.join(base, pose_video_rel), fourcc, max(1.0, fps / max(1, total // max(1, config.timesteps))), (w, h))
        for im in pose_imgs_for_vid:
            vw.write(im)
        vw.release()
    if config.save_pair_video and pair_imgs_for_vid:
        h, w = pair_imgs_for_vid[0].shape[:2]
        vw = cv2.VideoWriter(os.path.join(base, pair_video_rel), fourcc, max(1.0, fps / max(1, total // max(1, config.timesteps))), (w, h))
        for im in pair_imgs_for_vid:
            vw.write(im)
        vw.release()

    # npz
    npz_rel = f"npz/keypoints_{safe_vid}_{safe_lbl}_T{config.timesteps}_{config.sampling_mode}.npz"
    if config.generate_npz:
        np.savez(
            os.path.join(base, npz_rel),
            x=keypoints,
            frame_indices=np.array(sampled, dtype=np.int32),
            video=video_name,
            label=label,
            sampling_mode=config.sampling_mode,
            timesteps=config.timesteps,
            original_filename=os.path.basename(video_path),
        )

    # quality report
    pose_missing = sum(1 for r in frame_records if not r["has_pose"])
    lh_missing = sum(1 for r in frame_records if not r["has_left_hand"])
    rh_missing = sum(1 for r in frame_records if not r["has_right_hand"])
    zero_cnt = sum(1 for r in frame_records if r["is_all_zero"])
    T = max(1, len(frame_records))
    quality = {
        "total_original_frames": total,
        "timesteps": config.timesteps,
        "sampled_frame_indices": sampled,
        "pose_missing": pose_missing,
        "left_hand_missing": lh_missing,
        "right_hand_missing": rh_missing,
        "all_zero": zero_cnt,
        "pose_missing_rate": pose_missing / T,
        "left_hand_missing_rate": lh_missing / T,
        "right_hand_missing_rate": rh_missing / T,
        "all_zero_rate": zero_cnt / T,
        "per_frame": frame_records,
    }
    qr_json_rel = f"reports/quality_report_{safe_vid}_{safe_lbl}.json"
    if config.generate_quality_report:
        with open(os.path.join(base, qr_json_rel), "w", encoding="utf-8") as f:
            json.dump(quality, f, ensure_ascii=False, indent=2)

    manifest = {
        "original_filename": os.path.basename(video_path),
        "video_name": video_name,
        "label": label,
        "safe_label": safe_lbl,
        "safe_video": safe_vid,
        "timesteps": config.timesteps,
        "sampling_mode": config.sampling_mode,
        "total_original_frames": total,
        "sampled_frame_indices": sampled,
        "npz_shape": [config.timesteps, KP_DIM],
        "outputs": {
            "npz": npz_rel,
            "grid": grid_rel,
            "pose_video": pose_video_rel,
            "pair_video": pair_video_rel,
            "quality_report_json": qr_json_rel,
        },
        "frames": frame_records,
    }
    manifest_rel = f"manifest_{safe_vid}_{safe_lbl}.json"
    with open(os.path.join(base, manifest_rel), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    # zip
    zip_rel = f"outputs_{safe_vid}_{safe_lbl}.zip"
    zip_abs = os.path.join(base, zip_rel)
    with zipfile.ZipFile(zip_abs, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(base):
            for fn in files:
                if fn == zip_rel:
                    continue
                p = os.path.join(root, fn)
                zf.write(p, os.path.relpath(p, base))

    manifest["outputs"]["manifest"] = manifest_rel
    manifest["outputs"]["zip"] = zip_rel
    manifest["project_dir"] = f"{safe_vid}_{safe_lbl}"
    manifest["quality_summary"] = {
        k: quality[k] for k in (
            "pose_missing_rate", "left_hand_missing_rate",
            "right_hand_missing_rate", "all_zero_rate",
        )
    }
    return manifest
