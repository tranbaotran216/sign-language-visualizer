import { useEffect, useMemo, useState } from "react";
import { usePersistedState } from "../lib/session";

type Mapping = {
  video_id?: string | null;
  ground_truth?: string | null;
  prediction?: string | null;
  confidence?: string | null;
  modality?: string | null;
  model_name?: string | null;
};

type Row = {
  row_id: number;
  video_id: string;
  ground_truth: string;
  prediction: string;
  confidence: number;
  modality: string;
  model_name: string;
  matched_output?: string | null;
  matched_grid_url?: string | null;
  correct: boolean;
};

type Summary = {
  total: number; correct: number; wrong: number; accuracy: number;
  mean_confidence: number; matched_count: number; unmatched_count: number;
  modalities: string[]; has_multi_modality: boolean;
};

export default function ModelResultsPage() {
  const [dsId, setDsId] = usePersistedState<string | null>("mr.dsId", null);
  const [columns, setColumns] = usePersistedState<string[]>("mr.columns", []);
  const [mapping, setMapping] = usePersistedState<Mapping>("mr.mapping", {});
  const [preview, setPreview] = useState<any[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [tab, setTab] = usePersistedState<string>("mr.tab", "all");
  const [q, setQ] = usePersistedState("mr.q", "");
  const [rows, setRows] = useState<Row[]>([]);
  const [detail, setDetail] = useState<Row | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [extractions, setExtractions] = useState<any[]>([]);
  const [errorResult, setErrorResult] = useState<any>(null);

  useEffect(() => {
    fetch("/api/outputs").then(r => r.json()).then(d => setExtractions(d.items || []));
  }, []);

  async function upload(f: File) {
    setErr(null);
    const fd = new FormData(); fd.append("csv_file", f);
    const r = await fetch("/api/model-results/import", { method: "POST", body: fd });
    if (!r.ok) { setErr(await r.text()); return; }
    const d = await r.json();
    setDsId(d.dataset_id);
    setColumns(d.columns);
    setMapping(d.suggested_mapping);
    setPreview(d.preview_rows || []);
    setSummary(null); setRows([]);
  }

  async function applyMapping() {
    if (!dsId) return;
    const r = await fetch(`/api/model-results/${dsId}/map-columns`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mapping }),
    });
    if (!r.ok) { setErr(await r.text()); return; }
    const d = await r.json();
    setSummary(d.summary);
    loadRows(tab, q);
  }

  async function loadRows(filter: string, query: string) {
    if (!dsId) return;
    const r = await fetch(`/api/model-results/${dsId}/rows?filter=${filter}&q=${encodeURIComponent(query)}`);
    const d = await r.json();
    setRows(d.rows || []);
  }

  useEffect(() => { if (summary) loadRows(tab, q); }, [tab, q, summary]);

  const tabs = useMemo(() => {
    const base = [
      { key: "all", label: "Tất cả" },
      { key: "correct", label: "Đúng" },
      { key: "wrong", label: "Sai" },
      { key: "low_conf", label: "Confidence thấp" },
      { key: "high_conf_wrong", label: "Confidence cao nhưng sai" },
    ];
    if (summary?.has_multi_modality) {
      base.push({ key: "rgb_wins", label: "RGB wins" });
      base.push({ key: "pose_wins", label: "Pose wins" });
      base.push({ key: "fusion_wins", label: "Fusion wins" });
    }
    return base;
  }, [summary]);

  async function genError(row: Row) {
    setErrorResult(null);
    // try auto-find pred sample from extractions matching predicted class
    const pred = extractions.find(o =>
      o.label?.toLowerCase() === row.prediction.toLowerCase() && o.project_dir !== row.matched_output
    );
    const r = await fetch(`/api/model-results/${dsId}/generate-error-analysis`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ row_id: row.row_id, gt_project_dir: row.matched_output, pred_project_dir: pred?.project_dir }),
    });
    if (!r.ok) { setErr(await r.text()); return; }
    setErrorResult(await r.json());
  }

  return (
    <div>
      <h1 className="text-2xl font-bold">Visualize kết quả model</h1>
      <p className="text-sm text-gray-600 mt-1">Import prediction CSV và phân tích lỗi dùng dữ liệu visualization đã extract.</p>

      {/* Step 1: upload */}
      <div className="card mt-5">
        <h2 className="font-semibold mb-2">1. Import prediction CSV</h2>
        <input type="file" accept=".csv,text/csv" className="input"
               onChange={e => e.target.files?.[0] && upload(e.target.files[0])} />
        {err && <div className="text-sm text-red-600 mt-2">{err}</div>}
        {preview.length > 0 && (
          <div className="mt-4 overflow-x-auto">
            <div className="text-xs text-gray-500 mb-1">Preview 20 dòng đầu</div>
            <table className="text-xs w-full border">
              <thead className="bg-gray-100"><tr>
                {columns.map(c => <th key={c} className="px-2 py-1 text-left">{c}</th>)}
              </tr></thead>
              <tbody>
                {preview.map((r, i) => (
                  <tr key={i} className="border-t">
                    {columns.map(c => <td key={c} className="px-2 py-1">{String(r[c] ?? "")}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Step 2: map columns */}
      {dsId && (
        <div className="card mt-5">
          <h2 className="font-semibold mb-3">2. Mapping cột (chỉnh nếu auto-detect sai)</h2>
          <div className="grid sm:grid-cols-3 gap-3">
            {(["video_id","ground_truth","prediction","confidence","modality","model_name"] as const).map(k => (
              <div key={k}>
                <label className="label">{k}</label>
                <select className="input" value={mapping[k] || ""} onChange={e => setMapping({ ...mapping, [k]: e.target.value || null })}>
                  <option value="">—</option>
                  {columns.map(c => <option key={c} value={c}>{c}</option>)}
                </select>
              </div>
            ))}
          </div>
          <button className="btn-primary mt-4" onClick={applyMapping}>Áp dụng mapping & phân tích</button>
        </div>
      )}

      {/* Step 3: summary */}
      {summary && (
        <>
          <div className="grid sm:grid-cols-2 md:grid-cols-4 gap-3 mt-5">
            <Card t="Tổng samples" v={summary.total} />
            <Card t="Đúng" v={summary.correct} />
            <Card t="Sai" v={summary.wrong} />
            <Card t="Accuracy" v={`${(summary.accuracy * 100).toFixed(2)}%`} />
            <Card t="Mean confidence" v={summary.mean_confidence.toFixed(3)} />
            <Card t="Matched outputs" v={summary.matched_count} />
            <Card t="Unmatched" v={summary.unmatched_count} />
            <Card t="Modalities" v={summary.modalities.join(", ") || "—"} />
          </div>
          {!summary.has_multi_modality && (
            <div className="text-xs text-gray-500 mt-2">
              Cần import kết quả của nhiều modality để phân tích RGB/Pose/Fusion wins.
            </div>
          )}

          <div className="mt-5 flex flex-wrap gap-2 items-end">
            <div className="inline-flex border rounded-md overflow-hidden flex-wrap">
              {tabs.map(t => (
                <button key={t.key}
                  className={`px-3 py-1.5 text-xs ${tab === t.key ? "bg-brand-500 text-white" : "bg-white"}`}
                  onClick={() => setTab(t.key)}>{t.label}</button>
              ))}
            </div>
            <input className="input max-w-xs" placeholder="Search video / class" value={q} onChange={e => setQ(e.target.value)} />
            <a className="btn-ghost text-xs" href={`/api/model-results/${dsId}/export/csv?filter=${tab}`} download>⬇ Export CSV (tab)</a>
            <span className="text-xs text-gray-500 ml-auto">{rows.length} rows</span>
          </div>

          <div className="card mt-3 overflow-x-auto">
            <table className="text-sm w-full">
              <thead className="bg-gray-100 text-left"><tr>
                <th className="px-2 py-1">Video</th>
                <th className="px-2 py-1">GT</th>
                <th className="px-2 py-1">Pred</th>
                <th className="px-2 py-1">✓/✗</th>
                <th className="px-2 py-1">Conf</th>
                <th className="px-2 py-1">Modality</th>
                <th className="px-2 py-1">Matched</th>
                <th className="px-2 py-1"></th>
              </tr></thead>
              <tbody>
                {rows.map(r => (
                  <tr key={r.row_id} className="border-t hover:bg-gray-50">
                    <td className="px-2 py-1 font-medium">{r.video_id}</td>
                    <td className="px-2 py-1">{r.ground_truth}</td>
                    <td className="px-2 py-1">{r.prediction}</td>
                    <td className="px-2 py-1">
                      <span className={`chip ${r.correct ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"}`}>
                        {r.correct ? "correct" : "wrong"}
                      </span>
                    </td>
                    <td className="px-2 py-1">{r.confidence.toFixed(3)}</td>
                    <td className="px-2 py-1">{r.modality}</td>
                    <td className="px-2 py-1 text-xs font-mono truncate max-w-[200px]">{r.matched_output || "—"}</td>
                    <td className="px-2 py-1"><button className="text-brand-600 text-xs" onClick={() => setDetail(r)}>Xem</button></td>
                  </tr>
                ))}
                {rows.length === 0 && <tr><td colSpan={8} className="text-center py-6 text-gray-500">Không có dữ liệu.</td></tr>}
              </tbody>
            </table>
          </div>
        </>
      )}

      {detail && (
        <div className="fixed inset-0 z-50 bg-black/40 grid place-items-center p-4" onClick={() => setDetail(null)}>
          <div className="bg-white rounded-xl max-w-3xl w-full max-h-[90vh] overflow-auto p-6" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold">{detail.video_id}</h2>
              <button className="btn-ghost" onClick={() => setDetail(null)}>Đóng</button>
            </div>
            <div className="grid grid-cols-2 gap-3 text-sm mt-3">
              <div><b>Ground truth:</b> {detail.ground_truth}</div>
              <div><b>Prediction:</b> {detail.prediction}</div>
              <div><b>Confidence:</b> {detail.confidence.toFixed(3)}</div>
              <div><b>Status:</b> {detail.correct ? "correct" : "wrong"}</div>
              <div><b>Modality:</b> {detail.modality}</div>
              <div><b>Model:</b> {detail.model_name}</div>
            </div>
            {detail.matched_grid_url && <img src={detail.matched_grid_url} className="w-full mt-3 rounded border" />}
            {!detail.correct && (
              <button className="btn-primary mt-4" onClick={() => genError(detail)}>Tạo ảnh phân tích lỗi</button>
            )}
            {errorResult && (
              <div className="mt-4 border-t pt-3">
                <div className="text-sm font-semibold">Phân tích lỗi đã tạo</div>
                <img src={errorResult.comparison_image_url} className="w-full rounded border mt-2" />
                <div className="mt-2 flex gap-2 flex-wrap">
                  <a className="btn-ghost text-xs" href={errorResult.comparison_image_url} download>⬇ JPG</a>
                  <a className="btn-ghost text-xs" href={errorResult.comparison_pdf_url} download>⬇ PDF</a>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function Card({ t, v }: { t: string; v: any }) {
  return <div className="card"><div className="text-xs text-gray-500">{t}</div><div className="text-xl font-bold mt-1">{v}</div></div>;
}
