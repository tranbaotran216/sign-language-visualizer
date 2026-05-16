import { Link } from "react-router-dom";

const cards = [
  { to: "/extract", title: "Trích xuất MediaPipe từ video", desc: "Batch tới 5 video, sinh RGB/pose/pair frames, NPZ, grid, MP4, manifest và quality report.", icon: "🎬" },
  { to: "/compare", title: "So sánh frames đã trích xuất", desc: "Tạo ảnh so sánh 2–5 video. Mỗi video một dòng, mỗi cột là một frame. Xuất ảnh + PDF.", icon: "🔬" },
  { to: "/metadata", title: "Quản lý metadata CSV", desc: "Nhập file như ISLR_promax.csv với cột ID_video và Meaning để auto-fill ground truth.", icon: "📄" },
  { to: "/history", title: "Lịch sử outputs local", desc: "Duyệt lại các project đã trích xuất, tải ZIP, hoặc xoá folder local.", icon: "🗂️" },
];

export default function Dashboard() {
  return (
    <div>
      <header className="mb-8">
        <h1 className="text-3xl font-bold tracking-tight">KLTN VSL Visualization Tool</h1>
        <p className="text-gray-600 mt-2 max-w-3xl">
          Công cụ local hỗ trợ trích xuất MediaPipe keypoints và visualize dữ liệu Vietnamese Isolated Sign Language cho KLTN.
        </p>
      </header>
      <div className="grid sm:grid-cols-2 gap-5">
        {cards.map(c => (
          <Link key={c.to} to={c.to} className="card hover:shadow-md hover:border-brand-200 transition">
            <div className="flex items-start gap-4">
              <div className="text-3xl">{c.icon}</div>
              <div>
                <h3 className="font-semibold text-lg">{c.title}</h3>
                <p className="text-sm text-gray-600 mt-1">{c.desc}</p>
              </div>
            </div>
          </Link>
        ))}
      </div>

      <section className="mt-10 card">
        <h2 className="font-semibold mb-2">Hướng dẫn nhanh</h2>
        <ol className="text-sm text-gray-700 list-decimal pl-5 space-y-1">
          <li>Tải file CSV metadata (vd <code className="bg-gray-100 px-1 rounded">ISLR_promax.csv</code>) ở trang <strong>Metadata CSV</strong>.</li>
          <li>Sang trang <strong>Trích xuất MediaPipe</strong>, upload 1–5 video, kiểm tra label, bấm <strong>Bắt đầu trích xuất</strong>.</li>
          <li>Khi xong, sang <strong>So sánh frames</strong> để chọn các frame và tạo ảnh + PDF so sánh.</li>
        </ol>
      </section>
    </div>
  );
}
