import { useState } from "react";

type Resp = {
  metadata_id: string;
  filename: string;
  detected_columns: { id_col: string | null; label_col: string | null };
  all_columns: string[];
  preview_rows: any[];
  mapping_status: string;
  mapping_size: number;
};

export default function MetadataPage() {
  const [resp, setResp] = useState<Resp | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function upload(file: File) {
    setBusy(true); setErr(null);
    try {
      const fd = new FormData();
      fd.append("csv_file", file);
      const r = await fetch("/api/metadata/upload", { method: "POST", body: fd });
      if (!r.ok) throw new Error(await r.text());
      const data: Resp = await r.json();
      setResp(data);
      // Persist for cross-page use
      localStorage.setItem("metadata_id", data.metadata_id);
      localStorage.setItem("metadata_filename", data.filename);
    } catch (e: any) {
      setErr(e.message);
    } finally { setBusy(false); }
  }

  async function setColumns(id_col: string, label_col: string) {
    if (!resp) return;
    await fetch(`/api/metadata/${resp.metadata_id}/columns`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id_col, label_col }),
    });
    setResp({ ...resp, detected_columns: { id_col, label_col } });
  }

  return (
    <div>
      <h1 className="text-2xl font-bold">Quản lý metadata CSV</h1>
      <p className="text-gray-600 text-sm mt-1">
        Bắt buộc các cột <code className="bg-gray-100 px-1 rounded">ID_video</code> và <code className="bg-gray-100 px-1 rounded">Meaning</code>.
        Ví dụ: <code className="bg-gray-100 px-1 rounded">ISLR_promax.csv</code>.
      </p>

      <div className="card mt-6">
        <label className="label">Tải CSV metadata</label>
        <input type="file" accept=".csv,text/csv" className="input"
          onChange={e => e.target.files?.[0] && upload(e.target.files[0])} disabled={busy} />
        {busy && <div className="text-sm text-gray-500 mt-2">Đang đọc CSV…</div>}
        {err && <div className="text-sm text-red-600 mt-2">{err}</div>}
      </div>

      {resp && (
        <>
          <div className="card mt-6">
            <div className="flex items-center justify-between">
              <h2 className="font-semibold">Cột phát hiện</h2>
              <span className={`chip ${resp.mapping_status === "ok" ? "bg-green-100 text-green-700" : "bg-amber-100 text-amber-700"}`}>
                {resp.mapping_status === "ok" ? `OK · ${resp.mapping_size} entries` : "Cần chọn cột thủ công"}
              </span>
            </div>
            <div className="grid sm:grid-cols-2 gap-4 mt-4">
              <div>
                <label className="label">Cột ID_video</label>
                <select className="input" value={resp.detected_columns.id_col ?? ""}
                  onChange={e => setColumns(e.target.value, resp.detected_columns.label_col ?? "")}>
                  <option value="">— chọn —</option>
                  {resp.all_columns.map(c => <option key={c} value={c}>{c}</option>)}
                </select>
              </div>
              <div>
                <label className="label">Cột Meaning (label)</label>
                <select className="input" value={resp.detected_columns.label_col ?? ""}
                  onChange={e => setColumns(resp.detected_columns.id_col ?? "", e.target.value)}>
                  <option value="">— chọn —</option>
                  {resp.all_columns.map(c => <option key={c} value={c}>{c}</option>)}
                </select>
              </div>
            </div>
          </div>

          <div className="card mt-6 overflow-x-auto">
            <h2 className="font-semibold mb-3">Xem trước 20 dòng đầu</h2>
            <table className="text-sm w-full">
              <thead><tr className="text-left border-b">
                {resp.all_columns.map(c => <th key={c} className="px-2 py-1 font-medium text-gray-600">{c}</th>)}
              </tr></thead>
              <tbody>
                {resp.preview_rows.map((row, i) => (
                  <tr key={i} className="border-b last:border-0">
                    {resp.all_columns.map(c => <td key={c} className="px-2 py-1 align-top">{String(row[c] ?? "")}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
