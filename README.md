# KLTN VSL Visualization Tool

Công cụ **local** hỗ trợ trích xuất MediaPipe keypoints và visualize dữ liệu **Vietnamese Isolated Sign Language** cho khóa luận tốt nghiệp (KLTN).

App này chạy **hoàn toàn local** trên máy bạn: backend FastAPI (Python) + frontend React (Vite + TypeScript + Tailwind).
Không phải SaaS, không gửi dữ liệu đi đâu cả.

---

## 1. Cấu trúc thư mục

```
project-root/
  backend/
    environment.yml
    requirements.txt
    main.py
    services/
      extract_mediapipe.py
      compare_renderer.py
      pdf_report.py
      csv_metadata.py
      filename_parser.py
    outputs/          # kết quả trích xuất (mỗi video 1 folder)
    uploads/          # video gốc tạm thời theo session
  frontend/
    package.json
    src/
      pages/
      components/
      lib/
  README.md
```

---

## 2. Chạy Backend (FastAPI + MediaPipe)

### 2.1 Tạo conda env

```bash
cd backend
conda env create -f environment.yml
conda activate kltn-vsl
```

Nếu không dùng conda, có thể dùng venv:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # macOS / Linux
# .venv\Scripts\activate           # Windows
pip install -r requirements.txt
```

> Lưu ý: MediaPipe yêu cầu **Python 3.10 hoặc 3.11**. Trên Python 3.12+ có thể chưa hỗ trợ.

### 2.2 Khởi động backend

```bash
cd backend
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

API docs tự động tại: <http://127.0.0.1:8000/docs>

---

## 3. Chạy Frontend (React + Vite)
để chạy được "npm" cần install [nodejs](https://nodejs.org/en)

```bash
cd frontend
npm install
npm run dev
```

Mặc định mở tại <http://localhost:5173>. Frontend đã được cấu hình proxy `/api` → `http://127.0.0.1:8000`.

---

## 4. Các phase đã build

- **Phase 1** ✅ — CSV metadata, batch upload tới 5 video, trích xuất MediaPipe Holistic (13 pose + 21 + 21 hands, dim = 110), output RGB / pose / pair / NPZ / grid / pose MP4 / pair MP4 / manifest / quality report / ZIP.
- **Phase 2** ✅ — So sánh 2–5 video (chọn từ extraction result hoặc upload thủ công), parse tên file, render ảnh so sánh JPG/PNG, PDF report đầy đủ metadata + quality report, auto caption EN + VI.
- **Phase 3** ✅ — Editor đơn giản (reorder / remove / annotation).
- **Phase 4** ✅ — Output history manager nâng cao + reload config + nút "Xoá toàn bộ lịch sử" (`DELETE /api/history/all`).
- **Phase 5** ✅ — Trang **Phân tích chất lượng dataset** (`/dataset-qa`): quét toàn bộ outputs, dashboard cards (avg pose / LH / RH / all-zero missing), bảng filter theo Good / Warning / Bad / Critical, top 10 worst videos, export CSV + PDF.
- **Phase 6** ✅ — Trang **Visualize kết quả model** (`/model-results`): import prediction CSV, auto-detect + manual column mapping, ghép prediction row với extraction folder, tabs Correct/Wrong/Low-conf/High-conf-wrong + RGB/Pose/Fusion wins (khi có nhiều modality), modal chi tiết và nút **Tạo ảnh phân tích lỗi** dùng lại comparison renderer.

### Ghi chú quan trọng về LH / RH

`LH` = left hand, `RH` = right hand. MediaPipe label `left_hand_landmarks` / `right_hand_landmarks` theo **anatomical** của signer, không theo trái/phải trên màn hình. Trang `/extract` có bảng debug "Chi tiết detection theo frame" để đối chiếu trực tiếp với ảnh pose đã vẽ.

---

## 5. CSV metadata format

Bắt buộc 2 cột (các cột khác giữ nguyên):

| Cột       | Mô tả                                |
|-----------|---------------------------------------|
| ID_video  | Khớp với tên file video (vd `B0262`)  |
| Meaning   | Ground truth label (vd `môn tiếng việt`) |

Ví dụ file: `ISLR_promax.csv`.

## Phase 7 — Comparison Image Editor (draw.io-like)

Route: `/comparison-editor` (sidebar: "Chỉnh sửa ảnh so sánh").

From the comparison page, click **"Chỉnh sửa với editor"** on a generated result to open it in the editor. The editor uses **Fabric.js** with the comparison image locked as the background layer.

Supported objects: mũi tên, đường thẳng, hình chữ nhật, hình tròn, hình oval, text box.

Features:
- Select / move / resize / rotate / delete
- Stroke + fill color, stroke width, font size, opacity
- Bring forward / send backward (background stays locked at the bottom)
- Undo / redo (Ctrl+Z / Ctrl+Y, also via toolbar)
- Zoom in / out / fit to screen
- Export annotated image as **PNG / JPG**
- Export annotated **PDF** (image + captions + metadata) using `jsPDF`
- Save / load **editor project JSON**

Backend endpoints (Phase 7):
- `POST /api/editor/save-project` — store editor project JSON under `backend/outputs/_editor_projects/<id>/project.json`
- `GET  /api/editor/load-project/{project_id}`
- `POST /api/editor/export` — mirror a client-rendered annotated image into outputs

## Session persistence (Task A)

All page state (extraction config, comparison groups, selected frames, annotations,
dataset QA filters, model-results mapping/filters, editor canvas) is autosaved to
`localStorage` under the `kltn:` prefix. After reload you see the toast
**"Đã khôi phục phiên làm việc trước đó."**.

- Raw uploaded video/image File objects cannot be restored after reload — a notice is shown if missing.
- Generated backend outputs in `backend/outputs/` remain available.
- Sidebar button **"Xoá phiên làm việc hiện tại"** clears only the browser-side
  session (it does NOT delete backend outputs). Use `/history` to delete outputs.
- Navigation between sidebar tabs uses React Router (no full page reload).
