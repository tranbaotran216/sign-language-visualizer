import { useEffect, useMemo, useState } from "react";

type Row = {
  project_dir: string;
  video_name: string;
  label: string;
  timesteps: number;
  total_original_frames?: number;
  pose_missing_rate: number | null;
  left_hand_missing_rate: number | null;
  right_hand_missing_rate: number | null;
  all_zero_rate: number | null;
  quality_status: "good" | "warning" | "bad" | "critical" | "missing";
  grid_url?: string | null;
  worst_score?: number;
};

const STATUS_COLOR: Record<string, string> = {
  good: "bg-green-100 text-green-700",
  warning: "bg-amber-100 text-amber-700",
  bad: "bg-red-100 text-red-700",
  critical: "bg-red-200 text-red-800",
  missing: "bg-gray-200 text-gray-600",
};

export default function DatasetQAPage() {
  const [summary, setSummary] = useState<any>(null);
  const [rows, setRows] = useState<Row[]>([]);
  const [q, setQ] = useState("");
  const [statusF, setStatusF] = useState<string>("all");
  const [sort, setSort] = useState<"worst" | "name">("worst");
  const [detail, setDetail] = useState<any>(null);
  const [busy, setBusy] = useState(false);

  async function reload() {
    setBusy(true);
    try {
      const r = await fetch("/api/dataset-qa/summary");
      const d = await r.json();
      setSummary(d.summary);
      setRows(d.rows || []);
    } finally { setBusy(false); }
  }
  useEffect(() => { reload(); }, []);

  const filtered = useMemo(() => {
    let xs = rows.filter(r =>
      (!q || r.video_name?.toLowerCase().includes(q.toLowerCase())
         || r.label?.toLowerCase().includes(q.toLowerCase()))
      && (statusF === "all" || r.quality_status === statusF));
    if (sort === "worst") xs = [...xs].sort((a, b) => (b.worst_score || 0) - (a.worst_score || 0));
    else xs = [...xs].sort((a, b) => (a.video_name || "").localeCompare(b.video_name || ""));
    return xs;
  }, [rows, q, statusF, sort]);

  const worst = useMemo(() => [...rows]
    .filter(r => r.quality_status !== "missing")
    .sort((a, b) => (b.worst_score || 0) - (a.worst_score || 0))
    .slice(0, 10), [rows]);

  async function openDetail(pdir: string) {
    const r = await fetch(`/api/dataset-qa/video/${encodeURIComponent(pdir)}`);
    setDetail(await r.json());
  }

  return (
    <div>
      <h1 className="text-2xl font-bold">Phân tích chất lượng dataset</h1>
      <p className="text-sm text-gray-600 mt-1">
        Quét toàn bộ video đã extract dưới <code className="bg-gray-100 px-1 rounded">backend/outputs/</code> để đánh giá chất lượng MediaPipe ở mức dataset.
      </p>

      <div className="mt-3 flex gap-2 flex-wrap">
        <button className="btn-ghost" onClick={reload} disabled={busy}>{busy ? "Đang quét…" : "↻ Quét lại"}</button>
        <a className="btn-ghost" href="/api/dataset-qa/export/csv" download>⬇ Export CSV</a>
        <a className="btn-ghost" href="/api/dataset-qa/export/pdf" download>⬇ Export PDF</a>
      </div>

      {/* Summary cards */}
      {summary && (
        <div className="grid sm:grid-cols-2 md:grid-cols-4 gap-3 mt-5">
          <Card t="Tổng số video đã extract" v={summary.total_videos} />
          <Card t="Tổng số sampled frames" v={summary.total_sampled_frames} />
          <Card t="Trung bình Pose missing" v={fmt(summary.avg_pose_missing_rate)} />
          <Card t="Trung bình LH missing" v={fmt(summary.avg_left_hand_missing_rate)} />
          <Card t="Trung bình RH missing" v={fmt(summary.avg_right_hand_missing_rate)} />
          <Card t="Trung bình all-zero" v={fmt(summary.avg_all_zero_rate)} />
          <Card t="Video chất lượng kém" v={(summary.n_bad || 0) + (summary.n_critical || 0)} bad />
          <Card t="Thiếu metadata/report" v={summary.videos_missing_metadata} bad />
        </div>
      )}

      {/* Worst examples */}
      {worst.length > 0 && (
        <div className="card mt-6">
          <h2 className="font-semibold mb-3">Videos cần kiểm tra lại (top 10 worst)</h2>
          <div className="grid sm:grid-cols-2 md:grid-cols-5 gap-3">
            {worst.map(r => (
              <button key={r.project_dir} className="text-left border rounded-md p-2 hover:border-brand-300"
                      onClick={() => openDetail(r.project_dir)}>
                {r.grid_url && <img src={r.grid_url} className="w-full h-20 object-cover rounded" />}
                <div className="text-xs font-semibold mt-1 truncate">{r.video_name}</div>
                <div className="text-[11px] text-gray-500 truncate">{r.label}</div>
                <div className={`chip mt-1 ${STATUS_COLOR[r.quality_status]}`}>{r.quality_status}</div>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Filters + Table */}
      <div className="card mt-6">
        <div className="flex flex-wrap gap-2 items-end">
          <input className="input max-w-xs" placeholder="Tìm video / label" value={q} onChange={e => setQ(e.target.value)} />
          <select className="input max-w-[180px]" value={statusF} onChange={e => setStatusF(e.target.value)}>
            <option value="all">Tất cả status</option>
            <option value="good">Good</option>
            <option value="warning">Warning</option>
            <option value="bad">Bad</option>
            <option value="critical">Critical</option>
            <option value="missing">Missing metadata</option>
          </select>
          <select className="input max-w-[160px]" value={sort} onChange={e => setSort(e.target.value as any)}>
            <option value="worst">Sort: worst</option>
            <option value="name">Sort: name</option>
          </select>
          <span className="text-xs text-gray-500 ml-auto">{filtered.length} / {rows.length} videos</span>
        </div>

        <div className="mt-4 overflow-x-auto">
          <table className="text-sm w-full">
            <thead className="bg-gray-100 text-left">
              <tr>
                <th className="px-2 py-1">Video</th>
                <th className="px-2 py-1">Label</th>
                <th className="px-2 py-1">T</th>
                <th className="px-2 py-1">Pose%</th>
                <th className="px-2 py-1">LH%</th>
                <th className="px-2 py-1">RH%</th>
                <th className="px-2 py-1">Zero%</th>
                <th className="px-2 py-1">Status</th>
                <th className="px-2 py-1"></th>
              </tr>
            </thead>
            <tbody>
              {filtered.map(r => (
                <tr key={r.project_dir} className="border-t hover:bg-gray-50">
                  <td className="px-2 py-1 font-medium">{r.video_name}</td>
                  <td className="px-2 py-1">{r.label}</td>
                  <td className="px-2 py-1">{r.timesteps}</td>
                  <td className="px-2 py-1">{fmt(r.pose_missing_rate)}</td>
                  <td className="px-2 py-1">{fmt(r.left_hand_missing_rate)}</td>
                  <td className="px-2 py-1">{fmt(r.right_hand_missing_rate)}</td>
                  <td className="px-2 py-1">{fmt(r.all_zero_rate)}</td>
                  <td className="px-2 py-1"><span className={`chip ${STATUS_COLOR[r.quality_status]}`}>{r.quality_status}</span></td>
                  <td className="px-2 py-1"><button className="text-brand-600 text-xs" onClick={() => openDetail(r.project_dir)}>Xem</button></td>
                </tr>
              ))}
              {filtered.length === 0 && (
                <tr><td colSpan={9} className="text-center py-6 text-gray-500">Không có dữ liệu phù hợp.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {detail && <DetailModal d={detail} onClose={() => setDetail(null)} />}
    </div>
  );
}

function fmt(v: number | null | undefined) {
  if (v == null) return "—";
  return `${(v * 100).toFixed(1)}%`;
}

function Card({ t, v, bad }: { t: string; v: any; bad?: boolean }) {
  return (
    <div className={`card ${bad && Number(v) > 0 ? "border-red-200 bg-red-50" : ""}`}>
      <div className="text-xs text-gray-500">{t}</div>
      <div className="text-xl font-bold mt-1">{v ?? "—"}</div>
    </div>
  );
}

function DetailModal({ d, onClose }: { d: any; onClose: () => void }) {
  const qr = d.quality_report || {};
  const frames: any[] = qr.frames || qr.per_frame || [];
  return (
    <div className="fixed inset-0 z-50 bg-black/40 grid place-items-center p-4" onClick={onClose}>
      <div className="bg-white rounded-xl max-w-5xl w-full max-h-[90vh] overflow-auto p-6" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-bold">{d.manifest?.video_name} · {d.manifest?.label}</h2>
          <button className="btn-ghost" onClick={onClose}>Đóng</button>
        </div>
        {d.grid_url && <img src={d.grid_url} className="w-full mt-3 rounded border" />}
        <div className="grid sm:grid-cols-4 gap-2 mt-3 text-xs">
          <Stat l="Pose missing" v={fmt(qr.pose_missing_rate)} />
          <Stat l="LH missing" v={fmt(qr.left_hand_missing_rate)} />
          <Stat l="RH missing" v={fmt(qr.right_hand_missing_rate)} />
          <Stat l="All-zero" v={fmt(qr.all_zero_rate)} />
        </div>
        {frames.length > 0 && (
          <div className="mt-4 overflow-x-auto">
            <table className="text-xs w-full">
              <thead className="bg-gray-100 text-left"><tr>
                <th className="px-2 py-1">#</th><th className="px-2 py-1">orig</th>
                <th className="px-2 py-1">pose</th><th className="px-2 py-1">LH</th>
                <th className="px-2 py-1">RH</th><th className="px-2 py-1">zero</th>
              </tr></thead>
              <tbody>
                {frames.map((f: any) => (
                  <tr key={f.sample_index} className="border-t">
                    <td className="px-2 py-1">{f.sample_index}</td>
                    <td className="px-2 py-1">{f.original_frame_index}</td>
                    <td className="px-2 py-1">{f.has_pose ? "✓" : "✗"}</td>
                    <td className="px-2 py-1">{f.has_left_hand ? "✓" : "✗"}</td>
                    <td className="px-2 py-1">{f.has_right_hand ? "✓" : "✗"}</td>
                    <td className="px-2 py-1">{f.is_all_zero ? "yes" : "no"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function Stat({ l, v }: { l: string; v: any }) {
  return <div className="rounded border p-2"><div className="text-gray-500">{l}</div><div className="font-bold">{v}</div></div>;
}
