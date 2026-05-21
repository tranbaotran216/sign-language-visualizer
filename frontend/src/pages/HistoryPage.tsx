import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

export default function HistoryPage() {
  const [tab, setTab] = useState<"extractions" | "comparisons">("extractions");
  const [items, setItems] = useState<any[]>([]);
  const [comps, setComps] = useState<any[]>([]);
  const [q, setQ] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<{ kind: "ok" | "err"; msg: string } | null>(null);

  function showToast(kind: "ok" | "err", msg: string) {
    setToast({ kind, msg });
    setTimeout(() => setToast(null), 3500);
  }

  async function reload() {
    const [r1, r2] = await Promise.all([fetch("/api/outputs"), fetch("/api/comparisons")]);
    setItems((await r1.json()).items || []);
    setComps((await r2.json()).items || []);
  }
  useEffect(() => { reload(); }, []);

  async function del(name: string) {
    if (!confirm(`Xoá folder local ${name}?`)) return;
    await fetch(`/api/outputs/${encodeURIComponent(name)}`, { method: "DELETE" });
    reload();
  }
  async function delComp(id: string) {
    if (!confirm(`Xoá comparison ${id}?`)) return;
    await fetch(`/api/comparisons/${encodeURIComponent(id)}`, { method: "DELETE" });
    reload();
  }

  async function deleteAll() {
    setBusy(true);
    try {
      const r = await fetch("/api/history/all", { method: "DELETE" });
      if (!r.ok) throw new Error(await r.text());
      const d = await r.json();
      showToast("ok", `Đã xoá toàn bộ lịch sử outputs. (${d.deleted_count} mục)`);
      setConfirming(false);
      await reload();
    } catch (e: any) {
      showToast("err", "Không thể xoá lịch sử outputs.");
    } finally { setBusy(false); }
  }

  const nav = useNavigate();
  async function reloadConfig(url: string) {
    const r = await fetch(url);
    const cfg = await r.json();
    sessionStorage.setItem("preload_comparison_config", JSON.stringify(cfg));
    nav("/compare");
  }

  const filtered = items.filter(it =>
    !q || it.video_name?.toLowerCase().includes(q.toLowerCase())
       || it.label?.toLowerCase().includes(q.toLowerCase())
       || it.project_dir?.toLowerCase().includes(q.toLowerCase()));
  const filteredComps = comps.filter(c =>
    !q || c.comparison_id?.toLowerCase().includes(q.toLowerCase())
       || (c.labels || []).some((l: string) => l.toLowerCase().includes(q.toLowerCase())));

  return (
    <div>
      <h1 className="text-2xl font-bold">Lịch sử outputs local</h1>
      <p className="text-sm text-gray-600 mt-1">Tất cả nằm dưới <code className="bg-gray-100 px-1 rounded">backend/outputs/</code>.</p>

      <div className="mt-4 flex gap-2 flex-wrap items-center">
        <div className="inline-flex border rounded-md overflow-hidden">
          <button className={`px-3 py-1.5 text-sm ${tab === "extractions" ? "bg-brand-500 text-white" : "bg-white"}`}
                  onClick={() => setTab("extractions")}>Extractions ({items.length})</button>
          <button className={`px-3 py-1.5 text-sm ${tab === "comparisons" ? "bg-brand-500 text-white" : "bg-white"}`}
                  onClick={() => setTab("comparisons")}>Comparisons ({comps.length})</button>
        </div>
        <input className="input max-w-sm" placeholder="Tìm theo tên / label" value={q} onChange={e => setQ(e.target.value)} />
        <button className="btn-ghost" onClick={reload}>↻ Reload</button>
        <button
          className="btn inline-flex items-center gap-2 bg-red-600 text-white hover:bg-red-700 disabled:opacity-50"
          onClick={() => setConfirming(true)}
          disabled={busy || (items.length === 0 && comps.length === 0)}
          title="Xoá toàn bộ outputs trong thư mục local"
        >
          🗑️ Xoá toàn bộ lịch sử
        </button>
      </div>

      {toast && (
        <div className={`mt-3 text-sm px-3 py-2 rounded-md ${toast.kind === "ok" ? "bg-green-50 text-green-700 border border-green-200" : "bg-red-50 text-red-700 border border-red-200"}`}>
          {toast.msg}
        </div>
      )}

      {tab === "extractions" ? (
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
                <button className="btn-ghost text-xs" onClick={() => {
                  sessionStorage.setItem("kltn:overlay:handoff", JSON.stringify({ project_dirs: [it.project_dir] }));
                  nav("/overlay");
                }}>🌀 Tạo overlay</button>
                <button className="btn-ghost text-xs text-red-600" onClick={() => del(it.project_dir)}>Xoá</button>
              </div>
            </div>
          ))}
          {filtered.length === 0 && <div className="text-sm text-gray-500">Chưa có output.</div>}
        </div>
      ) : (
        <div className="mt-4 grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredComps.map(c => (
            <div key={c.comparison_id} className="card">
              {c.image_url && <img src={c.image_url} className="w-full h-32 object-cover rounded border" />}
              <div className="mt-2 font-semibold truncate">{c.comparison_id}</div>
              <div className="text-xs text-gray-500 truncate">{(c.labels || []).join(" · ")}</div>
              <div className="text-xs text-gray-400 mt-1">{c.created_at} · {c.n_groups} videos</div>
              <div className="mt-3 flex flex-wrap gap-2">
                {c.image_url && <a href={c.image_url} className="btn-ghost text-xs" download>⬇ JPG</a>}
                {c.pdf_url && <a href={c.pdf_url} className="btn-ghost text-xs" download>⬇ PDF</a>}
                {c.zip_url && <a href={c.zip_url} className="btn-ghost text-xs" download>⬇ ZIP</a>}
                {c.config_url && <button className="btn-ghost text-xs" onClick={() => reloadConfig(c.config_url)}>↩ Mở lại config</button>}
                <button className="btn-ghost text-xs text-red-600" onClick={() => delComp(c.comparison_id)}>Xoá</button>
              </div>
            </div>
          ))}
          {filteredComps.length === 0 && <div className="text-sm text-gray-500">Chưa có comparison.</div>}
        </div>
      )}

      {/* Confirmation dialog */}
      {confirming && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 p-4" onClick={() => !busy && setConfirming(false)}>
          <div className="bg-white rounded-xl max-w-md w-full p-6 shadow-xl" onClick={e => e.stopPropagation()}>
            <h2 className="text-lg font-bold text-red-700">Xoá toàn bộ lịch sử outputs local?</h2>
            <p className="text-sm text-gray-700 mt-3">
              Hành động này sẽ xoá toàn bộ outputs đã tạo trong thư mục local, bao gồm kết quả extract và comparison.
              Hành động này không thể hoàn tác.
            </p>
            <div className="mt-5 flex justify-end gap-2">
              <button className="btn-ghost" onClick={() => setConfirming(false)} disabled={busy}>Huỷ</button>
              <button
                className="btn bg-red-600 text-white hover:bg-red-700 disabled:opacity-50"
                onClick={deleteAll} disabled={busy}
              >{busy ? "Đang xoá…" : "Xoá tất cả"}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
