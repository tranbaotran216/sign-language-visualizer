import { useEffect, useState } from "react";

export default function HistoryPage() {
  const [items, setItems] = useState<any[]>([]);
  const [q, setQ] = useState("");

  async function reload() {
    const r = await fetch("/api/outputs");
    const d = await r.json();
    setItems(d.items || []);
  }
  useEffect(() => { reload(); }, []);

  async function del(name: string) {
    if (!confirm(`Xoá folder local ${name}?`)) return;
    await fetch(`/api/outputs/${encodeURIComponent(name)}`, { method: "DELETE" });
    reload();
  }

  const filtered = items.filter(it =>
    !q || it.video_name?.toLowerCase().includes(q.toLowerCase())
       || it.label?.toLowerCase().includes(q.toLowerCase())
       || it.project_dir?.toLowerCase().includes(q.toLowerCase()));

  return (
    <div>
      <h1 className="text-2xl font-bold">Lịch sử outputs local</h1>
      <p className="text-sm text-gray-600 mt-1">Tất cả nằm dưới <code className="bg-gray-100 px-1 rounded">backend/outputs/</code>.</p>
      <div className="mt-4 flex gap-2">
        <input className="input max-w-sm" placeholder="Tìm theo tên / label / folder" value={q} onChange={e => setQ(e.target.value)} />
        <button className="btn-ghost" onClick={reload}>↻ Reload</button>
      </div>
      <div className="mt-4 grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {filtered.map(it => (
          <div key={it.project_dir} className="card">
            {it.grid_url && <img src={it.grid_url} className="w-full h-32 object-cover rounded border" />}
            <div className="mt-2 font-semibold">{it.video_name}</div>
            <div className="text-sm text-gray-600 truncate">{it.label}</div>
            <div className="text-xs text-gray-400 font-mono truncate">{it.project_dir}</div>
            <div className="text-xs text-gray-500 mt-1">{it.created_at}</div>
            <div className="mt-3 flex flex-wrap gap-2">
              {it.zip_url && <a href={it.zip_url} className="btn-ghost text-xs" download>⬇ ZIP</a>}
              <button className="btn-ghost text-xs text-red-600" onClick={() => del(it.project_dir)}>Xoá</button>
            </div>
          </div>
        ))}
        {filtered.length === 0 && <div className="text-sm text-gray-500">Chưa có output.</div>}
      </div>
    </div>
  );
}
