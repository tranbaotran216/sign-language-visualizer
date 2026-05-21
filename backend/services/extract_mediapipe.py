"""MediaPipe Holistic extraction service.

Extracts 13 upper-body pose + 21 left hand + 21 right hand landmarks (x,y only),
normalized to [-1, 1]. Total dim = 110.

Produces per-video output folder under backend/outputs/{video_name}_{safe_label}/.
"""
from __future__ import annotations
import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field, asdict
from pathlib import Path
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
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_VITPOSE_WORKER = PROJECT_ROOT / "vitpose_worker.py"
DEFAULT_VITPOSE_CONFIG = (
    PROJECT_ROOT
    / "ViTPose"
    / "configs"
    / "wholebody"
    / "2d_kpt_sview_rgb_img"
    / "topdown_heatmap"
    / "coco-wholebody"
    / "ViTPose_large_wholebody_256x192.py"
)
DEFAULT_VITPOSE_CKPT = PROJECT_ROOT / "source_code" / "weights_config" / "vitpose-l-wholebody.pth"


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


def sample_indices_vitpose(total: int, timesteps: int, mode: str = "iter") -> List[int]:
    """Mirror vitpose_worker.py sampling so frame previews match the saved NPZ."""
    if total <= 0:
        return [0] * timesteps
    if mode == "mid":
        stride = 3 if total >= 160 else 2 if total >= 96 else 1
        span = timesteps * stride
        start = (total - span) // 2 if total > span else 0
        return [min(total - 1, start + i * stride) for i in range(timesteps)]
    if mode == "mix":
        mid = int(timesteps * 0.75)
        side = (timesteps - mid) // 2
        if total >= mid:
            start = (total - mid) // 2
            end = start + mid - 1
            middle = np.arange(start, end + 1, dtype=int)
            head = np.rint(np.linspace(0, start - 1, side)).astype(int) if start > 0 and side > 0 else np.array([], dtype=int)
            tail = (
                np.rint(np.linspace(end + 1, total - 1, side)).astype(int)
                if end + 1 <= total - 1 and side > 0
                else np.array([], dtype=int)
            )
            idx = np.concatenate([head, middle, tail])
            if idx.size < timesteps:
                idx = np.concatenate([idx, np.full((timesteps - idx.size,), idx[-1], dtype=int)])
            elif idx.size > timesteps:
                idx = idx[np.rint(np.linspace(0, idx.size - 1, timesteps)).astype(int)]
            return np.clip(idx, 0, total - 1).astype(int).tolist()
    if total >= timesteps:
        return np.rint(np.linspace(0, total - 1, timesteps)).astype(int).tolist()
    return list(range(total)) + [total - 1] * (timesteps - total)


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


def _norm_landmarks_to_xy(landmarks, width: int, height: int):
    if landmarks is None:
        return None
    return np.array(
        [[lm.x * width, lm.y * height] for lm in landmarks.landmark],
        dtype=np.float32
    )


POSE_CONNECTIONS_LOCAL = [
    (0, 1), (0, 2),        # nose -> eyes
    (1, 3), (2, 4),        # eyes -> ears
    (5, 6),                # shoulders
    (5, 7), (7, 9),        # left arm
    (6, 8), (8, 10),       # right arm
    (5, 11), (6, 12),      # shoulder -> hip
    (11, 12)               # hips
]


def _draw_pose_image(results, w: int, h: int, frame_bgr=None) -> np.ndarray:
    """
    Draw pose giống notebook:
    - nền đen
    - chỉ vẽ 13 upper-body pose landmarks
    - vẽ 2 bàn tay
    """
    canvas = np.zeros((h, w, 3), dtype=np.uint8)

    if not _HAS_MP:
        return canvas

    holistic = mp.solutions.holistic
    hand_connections = holistic.HAND_CONNECTIONS

    # Pose upper body 13 points
    if results.pose_landmarks:
        all_pose_xy = _norm_landmarks_to_xy(results.pose_landmarks, w, h)
        pose_xy = all_pose_xy[POSE_INDICES]

        for a, b in POSE_CONNECTIONS_LOCAL:
            pa, pb = pose_xy[a], pose_xy[b]
            cv2.line(
                canvas,
                tuple(pa.astype(int)),
                tuple(pb.astype(int)),
                (180, 180, 180),
                2,
                cv2.LINE_AA
            )

        for p in pose_xy:
            cv2.circle(
                canvas,
                tuple(p.astype(int)),
                3,
                (0, 255, 255),
                -1,
                cv2.LINE_AA
            )

    # Hands
    for hand_lms, color in [
        (results.left_hand_landmarks, (255, 180, 0)),
        (results.right_hand_landmarks, (0, 220, 255)),
    ]:
        hand_xy = _norm_landmarks_to_xy(hand_lms, w, h)
        if hand_xy is None:
            continue

        for a, b in hand_connections:
            pa, pb = hand_xy[a], hand_xy[b]
            cv2.line(
                canvas,
                tuple(pa.astype(int)),
                tuple(pb.astype(int)),
                color,
                2,
                cv2.LINE_AA
            )

        for p in hand_xy:
            cv2.circle(
                canvas,
                tuple(p.astype(int)),
                2,
                color,
                -1,
                cv2.LINE_AA
            )

    return canvas


def _pose55_valid_mask(seq_frame: np.ndarray) -> np.ndarray:
    pts = seq_frame.reshape(55, 2)
    normalized = (pts + 1.0) * 0.5
    return ~((normalized[:, 0] <= 1e-4) & (normalized[:, 1] <= 1e-4))


def _pose55_to_points(seq_frame: np.ndarray, width: int, height: int) -> np.ndarray:
    pts = seq_frame.reshape(55, 2)
    pts = (pts + 1.0) * 0.5
    pts = np.nan_to_num(np.clip(pts, 0.0, 1.0))
    out = np.empty_like(pts, dtype=np.int32)
    out[:, 0] = np.rint(pts[:, 0] * (width - 1)).astype(np.int32)
    out[:, 1] = np.rint(pts[:, 1] * (height - 1)).astype(np.int32)
    return out


def _draw_pose55_image(seq_frame: np.ndarray, w: int, h: int) -> np.ndarray:
    canvas = np.zeros((h, w, 3), dtype=np.uint8)
    valid = _pose55_valid_mask(seq_frame)
    if np.allclose(seq_frame, 0.0) or not np.any(valid):
        return canvas

    pts = _pose55_to_points(seq_frame, w, h)
    body_edges = [
        (0, 1), (0, 2), (1, 3), (2, 4), (5, 6), (5, 7), (7, 9),
        (6, 8), (8, 10), (5, 11), (6, 12), (11, 12),
    ]
    hand_edges = [
        (0, 1), (1, 2), (2, 3), (3, 4),
        (0, 5), (5, 6), (6, 7), (7, 8),
        (0, 9), (9, 10), (10, 11), (11, 12),
        (0, 13), (13, 14), (14, 15), (15, 16),
        (0, 17), (17, 18), (18, 19), (19, 20),
    ]

    def draw_edges(offset: int, edges, color):
        for a, b in edges:
            ia, ib = offset + a, offset + b
            if valid[ia] and valid[ib]:
                cv2.line(canvas, tuple(pts[ia]), tuple(pts[ib]), color, 2, cv2.LINE_AA)

    draw_edges(0, body_edges, (180, 180, 180))
    draw_edges(13, hand_edges, (255, 180, 0))
    draw_edges(34, hand_edges, (0, 220, 255))
    for idx, point in enumerate(pts):
        if not valid[idx]:
            continue
        color = (0, 255, 255) if idx < 13 else (255, 180, 0) if idx < 34 else (0, 220, 255)
        cv2.circle(canvas, tuple(point), 3 if idx < 13 else 2, color, -1, cv2.LINE_AA)
    return canvas


def _pose55_detection_flags(seq_frame: np.ndarray):
    valid = _pose55_valid_mask(seq_frame)
    return bool(valid[:13].any()), bool(valid[13:34].any()), bool(valid[34:55].any())


def _run_subprocess(cmd: List[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(cmd, cwd=str(PROJECT_ROOT), text=True, capture_output=True, check=False)
    except FileNotFoundError:
        if cmd and cmd[0] == "conda":
            return subprocess.run(["conda.bat", *cmd[1:]], cwd=str(PROJECT_ROOT), text=True, capture_output=True, check=False)
        raise


def _extract_pose_vitpose_subprocess(video_path: str, config: "ExtractConfig") -> np.ndarray:
    worker = Path(config.vitpose_worker or str(DEFAULT_VITPOSE_WORKER))
    pose_config = Path(config.vitpose_config or str(DEFAULT_VITPOSE_CONFIG))
    checkpoint = Path(config.vitpose_ckpt or str(DEFAULT_VITPOSE_CKPT))
    if not worker.exists():
        raise FileNotFoundError(f"ViTPose worker not found: {worker}")
    if not pose_config.exists():
        raise FileNotFoundError(f"ViTPose config not found: {pose_config}")
    if not checkpoint.exists():
        raise FileNotFoundError(f"ViTPose checkpoint not found: {checkpoint}")

    with tempfile.NamedTemporaryFile(suffix=".npy", delete=False) as f:
        out_path = Path(f.name)
    out_path.unlink(missing_ok=True)

    conda_env = config.vitpose_conda_env or os.environ.get("VITPOSE_CONDA_ENV", "kltn_vitpose")
    cmd = [
        "conda", "run", "-n", conda_env, "python", str(worker),
        "--video", str(video_path),
        "--config", str(pose_config),
        "--checkpoint", str(checkpoint),
        "--out", str(out_path),
        "--clip-len", str(int(config.timesteps)),
        "--sampling-mode", config.sampling_mode,
        "--device", config.vitpose_device or os.environ.get("VITPOSE_DEVICE", "cuda:0"),
        "--project-root", str(PROJECT_ROOT),
    ]
    try:
        try:
            result = _run_subprocess(cmd)
        except FileNotFoundError as exc:
            raise RuntimeError(
                "ViTPose subprocess could not start because conda was not found. "
                f"Set VITPOSE_CONDA_ENV to a valid env or install Conda on PATH. Target env: {conda_env}. {exc}"
            ) from exc
        if result.returncode != 0:
            raise RuntimeError(
                "ViTPose subprocess failed.\n"
                f"Conda env: {conda_env}\nReturn code: {result.returncode}\n"
                f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
            )
        if not out_path.exists():
            raise RuntimeError(f"ViTPose did not create output file.\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
        seq = np.load(str(out_path))
        if seq.ndim != 2 or seq.shape[1] != KP_DIM:
            raise ValueError(f"Invalid ViTPose output shape: {seq.shape}; expected (T, {KP_DIM}).")
        return seq.astype(np.float32)
    finally:
        try:
            out_path.unlink(missing_ok=True)
        except Exception:
            pass


# --------------------------------------------------------------- config
@dataclass
class ExtractConfig:
    extractor: str = "mediapipe"
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
    vitpose_config: str = str(DEFAULT_VITPOSE_CONFIG)
    vitpose_ckpt: str = str(DEFAULT_VITPOSE_CKPT)
    vitpose_conda_env: str = "kltn_vitpose"
    vitpose_device: str = "cuda:0"
    vitpose_worker: str = str(DEFAULT_VITPOSE_WORKER)


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
    extractor = (config.extractor or "mediapipe").lower()
    if extractor not in ("mediapipe", "vitpose"):
        raise ValueError(f"Unsupported extractor: {config.extractor}")

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
    sampled = (
        sample_indices_vitpose(total, config.timesteps, config.sampling_mode)
        if extractor == "vitpose"
        else sample_indices(total, config.timesteps, config.sampling_mode)
    )

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

    vitpose_seq: Optional[np.ndarray] = None
    if extractor == "vitpose":
        if progress_cb:
            progress_cb(0.02)
        vitpose_seq = _extract_pose_vitpose_subprocess(video_path, config)
        if vitpose_seq.shape[0] != config.timesteps:
            raise ValueError(f"Invalid ViTPose timestep count: {vitpose_seq.shape[0]}; expected {config.timesteps}.")
        if progress_cb:
            progress_cb(0.35)

    # Mediapipe
    if extractor == "mediapipe" and _HAS_MP:
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
            if extractor == "vitpose" and vitpose_seq is not None:
                vec = vitpose_seq[si]
                keypoints[si] = vec
                has_pose, has_lh, has_rh = _pose55_detection_flags(vec)
                pose_img = _draw_pose55_image(vec, frame.shape[1], frame.shape[0])
            elif holistic is not None:
                res = holistic.process(rgb)
                vec, has_pose, has_lh, has_rh = _landmarks_to_vec(res)
                keypoints[si] = vec
                pose_img = _draw_pose_image(res, frame.shape[1], frame.shape[0])
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

        is_zero = bool(not np.any(_pose55_valid_mask(keypoints[si]))) if extractor == "vitpose" else bool(np.all(keypoints[si] == 0))
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
            if extractor == "vitpose":
                progress_cb(0.35 + 0.65 * ((si + 1) / config.timesteps))
            else:
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
            extractor=extractor,
            sampling_mode=config.sampling_mode,
            timesteps=config.timesteps,
            original_filename=os.path.basename(video_path),
        )

    # ---- Quality report.
    # NOTE on LH/RH: `left_hand_landmarks` / `right_hand_landmarks` are the
    # signer's anatomical left/right hand as labelled by MediaPipe Holistic,
    # NOT the left/right side of the image. `has_left_hand` is True iff
    # MediaPipe returned non-None left_hand_landmarks AND the extracted
    # 21-landmark vector contains any non-zero coordinate. The same `results`
    # object is used for both drawing pose images and the report, so the
    # report cannot disagree with what is drawn.
    pose_det = sum(1 for r in frame_records if r["has_pose"])
    lh_det = sum(1 for r in frame_records if r["has_left_hand"])
    rh_det = sum(1 for r in frame_records if r["has_right_hand"])
    pose_missing = len(frame_records) - pose_det
    lh_missing = len(frame_records) - lh_det
    rh_missing = len(frame_records) - rh_det
    zero_cnt = sum(1 for r in frame_records if r["is_all_zero"])
    T = max(1, len(frame_records))
    quality = {
        "total_original_frames": total,
        "timesteps": config.timesteps,
        "sampled_frame_indices": sampled,
        "pose_detected_count": pose_det,
        "left_hand_detected_count": lh_det,
        "right_hand_detected_count": rh_det,
        "pose_missing_count": pose_missing,
        "left_hand_missing_count": lh_missing,
        "right_hand_missing_count": rh_missing,
        "all_zero_count": zero_cnt,
        # legacy keys (kept for backward compatibility)
        "pose_missing": pose_missing,
        "left_hand_missing": lh_missing,
        "right_hand_missing": rh_missing,
        "all_zero": zero_cnt,
        "pose_detected_rate": pose_det / T,
        "left_hand_detected_rate": lh_det / T,
        "right_hand_detected_rate": rh_det / T,
        "pose_missing_rate": pose_missing / T,
        "left_hand_missing_rate": lh_missing / T,
        "right_hand_missing_rate": rh_missing / T,
        "all_zero_rate": zero_cnt / T,
        "frames": frame_records,
        # legacy
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
        "extractor": extractor,
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
            "timesteps",
            "pose_detected_count", "left_hand_detected_count", "right_hand_detected_count",
            "pose_missing_count", "left_hand_missing_count", "right_hand_missing_count",
            "all_zero_count",
            "pose_missing_rate", "left_hand_missing_rate",
            "right_hand_missing_rate", "all_zero_rate",
            "pose_detected_rate", "left_hand_detected_rate", "right_hand_detected_rate",
        )
    }
    manifest["quality_frames"] = frame_records
    return manifest
