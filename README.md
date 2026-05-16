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
- **Phase 3** (sau) — Editor đơn giản (reorder / remove / annotation).
- **Phase 4** (sau) — Output history manager nâng cao + reload config.

---

## 5. CSV metadata format

Bắt buộc 2 cột (các cột khác giữ nguyên):

| Cột       | Mô tả                                |
|-----------|---------------------------------------|
| ID_video  | Khớp với tên file video (vd `B0262`)  |
| Meaning   | Ground truth label (vd `môn tiếng việt`) |

Ví dụ file: `ISLR_promax.csv`.
