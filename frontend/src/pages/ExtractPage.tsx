import { useEffect, useRef, useState } from "react";

type VideoRow = {
  file: File;
  original_filename: string;
  video_id: string;
  label: string;
  csv_label?: string;
};

type Config = {
  timesteps: number; sampling_mode: "iter" | "mid" | "mix"; timeout: number;
  tile_w: number; tile_h: number; grid_cols: number;
  save_rgb: boolean; save_pose: boolean; save_pair: boolean; save_grid: boolean;
  save_pose_video: boolean; save_pair_video: boolean;
  generate_npz: boolean; generate_quality_report: boolean; overwrite: boolean;
};

const DEFAULT_CFG: Config = {
  timesteps: 64, sampling_mode: "iter", timeout: 120,
  tile_w: 160, tile_h: 120, grid_cols: 8,
  save_rgb: true, save_pose: true, save_pair: true, save_grid: true,
  save_pose_video: true, save_pair_video: true,
  generate_npz: true, generate_quality_report: true, overwrite: true,
};

export default function ExtractPage() {
  const [rows, setRows] = useState<VideoRow[]>([]);
  const [cfg, setCfg] = useState<Config>(DEFAULT_CFG);
  const [batch, setBatch] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const metadataId = typeof window !== "undefined" ? localStorage.getItem("metadata_id") : null;
  const metadataName = typeof window !== "undefined" ? localStorage.getItem("metadata_filename") : null;
  const pollTimer = useRef<number | null>(null);

  async function onFiles(files: FileList | null) {
    if (!files) return;
    const arr = Array.from(files).slice(0, 5 - rows.length);
    const next: VideoRow[] = [];
    for (const f of arr) {
      const base = f.name.replace(/\.[^.]+$/, "");
      let vid = base.split("_")[0];
      let lbl = base;
      let csvLabel: string | undefined;
      if (metadataId) {
        try {
          const r = await fetch(`/api/metadata/${metadataId}/lookup?filename=${encodeURIComponent(f.name)}`);
          if (r.ok) {
            const d = await r.json();
            if (d.video_id) vid = d.video_id;
            if (d.label) { lbl = d.label; csvLabel = d.label; }
          }
        } catch {}
      }
      next.push({ file: f, original_filename: f.name, video_id: vid, label: lbl, csv_label: csvLabel });
    }
    setRows(r => [...r, ...next].slice(0, 5));
  }

  function patch(i: number, p: Partial<VideoRow>) {
    setRows(r => r.map((x, idx) => idx === i ? { ...x, ...p } : x));
  }

  async function start() {
    if (rows.length === 0) { setErr("Cần ít nhất 1 video."); return; }
    setBusy(true); setErr(null); setBatch(null);
    try {
      const fd = new FormData();
      for (const r of rows) fd.append("videos", r.file, r.original_filename);
      const cfgFull = {
        ...cfg,
        per_video_overrides: rows.map(r => ({
          original_filename: r.original_filename, video_id: r.video_id, label: r.label,
        })),
      };
      fd.append("config", JSON.stringify(cfgFull));
      if (metadataId) fd.append("metadata_id", metadataId);
      const res = await fetch("/api/extract/batch", { method: "POST", body: fd });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setBatch({ batch_id: data.batch_id, jobs: data.jobs });
      poll(data.batch_id);
    } catch (e: any) {
      setErr(e.message);
    } finally { setBusy(false); }
  }

  function poll(batchId: string) {
    if (pollTimer.current) window.clearInterval(pollTimer.current);
    pollTimer.current = window.setInterval(async () => {
      try {
        const r = await fetch(`/api/extract/batch/${batchId}`);
        if (!r.ok) return;
        const d = await r.json();
        setBatch(d);
        if (d.batch_status === "completed" || d.batch_status === "completed_with_errors") {
          if (pollTimer.current) { window.clearInterval(pollTimer.current); pollTimer.current = null; }
        }
      } catch {}
    }, 1500) as unknown as number;
  }

  useEffect(() => () => { if (pollTimer.current) window.clearInterval(pollTimer.current); }, []);

  return (
    <div>
      <h1 className="text-2xl font-bold">Trích xuất MediaPipe từ video</h1>
      <p className="text-sm text-gray-600 mt-1">
        Upload 1–5 video, MediaPipe Holistic sẽ trích xuất 13 pose + 21 + 21 hand landmarks (dim = 110).
      </p>
      {metadataName && (
        <div className="mt-2 chip bg-brand-50 text-brand-700">CSV: {metadataName}</div>
      )}

      <div className="card mt-6">
        <label className="label">Tải video lên (tối đa 5)</label>
        <input type="file" multiple accept=".mp4,.webm,.avi,.mov,.mkv,video/*" className="input"
               onChange={e => onFiles(e.target.files)} disabled={rows.length >= 5} />
        {rows.length > 0 && (
          <div className="mt-4 space-y-3">
            {rows.map((r, i) => (
              <div key={i} className="grid md:grid-cols-12 gap-2 items-end border rounded-md p-3 bg-gray-50">
                <div className="md:col-span-4">
                  <label className="label">Original filename</label>
                  <div className="text-sm truncate">{r.original_filename}</div>
                </div>
                <div className="md:col-span-3">
                  <label className="label">Video ID</label>
                  <input className="input" value={r.video_id} onChange={e => patch(i, { video_id: e.target.value })} />
                </div>
                <div className="md:col-span-4">
                  <label className="label">Ground truth label {r.csv_label && <span className="text-brand-600 normal-case">· từ CSV: {r.csv_label}</span>}</label>
                  <input className="input" value={r.label} onChange={e => patch(i, { label: e.target.value })} />
                </div>
                <div className="md:col-span-1">
                  <button className="btn-ghost w-full" onClick={() => setRows(rs => rs.filter((_, x) => x !== i))}>×</button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="card mt-6">
        <h2 className="font-semibold mb-3">Cấu hình trích xuất</h2>
        <div className="grid sm:grid-cols-3 md:grid-cols-6 gap-3">
          <Field label="Timesteps"><input type="number" className="input" value={cfg.timesteps}
            onChange={e => setCfg({ ...cfg, timesteps: +e.target.value })} /></Field>
          <Field label="Sampling">
            <select className="input" value={cfg.sampling_mode}
              onChange={e => setCfg({ ...cfg, sampling_mode: e.target.value as any })}>
              <option value="iter">iter</option><option value="mid">mid</option><option value="mix">mix</option>
            </select>
          </Field>
          <Field label="Timeout (s)"><input type="number" className="input" value={cfg.timeout}
            onChange={e => setCfg({ ...cfg, timeout: +e.target.value })} /></Field>
          <Field label="Tile W"><input type="number" className="input" value={cfg.tile_w}
            onChange={e => setCfg({ ...cfg, tile_w: +e.target.value })} /></Field>
          <Field label="Tile H"><input type="number" className="input" value={cfg.tile_h}
            onChange={e => setCfg({ ...cfg, tile_h: +e.target.value })} /></Field>
          <Field label="Grid cols"><input type="number" className="input" value={cfg.grid_cols}
            onChange={e => setCfg({ ...cfg, grid_cols: +e.target.value })} /></Field>
        </div>
        <div className="grid sm:grid-cols-3 md:grid-cols-5 gap-2 mt-4">
          {([
            ["save_rgb", "RGB frames"], ["save_pose", "Pose frames"], ["save_pair", "Pair frames"],
            ["save_grid", "Grid"], ["save_pose_video", "Pose MP4"], ["save_pair_video", "Pair MP4"],
            ["generate_npz", "NPZ"], ["generate_quality_report", "Quality report"], ["overwrite", "Overwrite"],
          ] as const).map(([k, lbl]) => (
            <label key={k} className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={(cfg as any)[k]} onChange={e => setCfg({ ...cfg, [k]: e.target.checked } as any)} />
              {lbl}
            </label>
          ))}
        </div>
      </div>

      <div className="mt-6 flex items-center gap-3">
        <button className="btn-primary" onClick={start} disabled={busy || rows.length === 0}>
          {busy ? "Đang gửi…" : "Bắt đầu trích xuất"}
        </button>
        {err && <span className="text-sm text-red-600">{err}</span>}
      </div>

      {batch?.jobs && (
        <div className="mt-8 space-y-4">
          <h2 className="font-semibold">Trạng thái batch · {batch.batch_status ?? "queued"}</h2>
          {batch.jobs.map((j: any) => <JobCard key={j.job_id} j={j} />)}
        </div>
      )}
    </div>
  );
}

function Field({ label, children }: any) {
  return <div><label className="label">{label}</label>{children}</div>;
}

function JobCard({ j }: { j: any }) {
  const m = j.manifest;
  const qs = j.quality_report_summary || {};
  const frames: any[] = m?.quality_frames || m?.frames || [];
  const T = qs.timesteps || frames.length || 0;
  const fileUrl = (rel: string) => `/files/${j.project_dir}/${rel}?t=${j.job_id}`;
  return (
    <div className="card">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="font-semibold">{j.video_id} <span className="text-gray-400">·</span> <span className="text-gray-600">{j.label}</span></div>
          <div className="text-xs text-gray-500">{j.original_filename}</div>
        </div>
        <span className={`chip ${
          j.status === "completed" ? "bg-green-100 text-green-700"
          : j.status === "failed" ? "bg-red-100 text-red-700"
          : j.status === "processing" ? "bg-blue-100 text-blue-700"
          : "bg-gray-100 text-gray-700"
        }`}>{j.status}</span>
      </div>
      <div className="mt-3 h-2 w-full bg-gray-100 rounded overflow-hidden">
        <div className="h-full bg-brand-500 transition-all" style={{ width: `${Math.round((j.progress || 0) * 100)}%` }} />
      </div>
      {j.error && <div className="text-sm text-red-600 mt-2">{j.error}</div>}

      {m && (
        <div className="mt-4 grid md:grid-cols-3 gap-4">
          <div>
            <img src={fileUrl(m.outputs.grid)} alt="grid" className="w-full rounded border" />
          </div>
          <div className="md:col-span-2 text-sm">
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1">
              <dt className="text-gray-500">Total frames</dt><dd>{m.total_original_frames}</dd>
              <dt className="text-gray-500">Timesteps</dt><dd>{m.timesteps}</dd>
              <dt className="text-gray-500">Sampling</dt><dd>{m.sampling_mode}</dd>
              <dt className="text-gray-500">NPZ shape</dt><dd>{JSON.stringify(m.npz_shape)}</dd>
              <dt className="text-gray-500">Folder</dt><dd className="font-mono text-xs">{m.project_dir}</dd>
            </dl>
            <p className="text-[11px] text-gray-500 mt-2 italic">
              LH/RH được tính theo quy ước anatomical left/right của MediaPipe, không phải trái/phải theo màn hình.
            </p>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mt-3">
              <D label="Pose detected" n={qs.pose_detected_count} T={T} />
              <D label="LH detected" n={qs.left_hand_detected_count} T={T} />
              <D label="RH detected" n={qs.right_hand_detected_count} T={T} />
              <D label="All-zero" n={qs.all_zero_count} T={T} danger />
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mt-2">
              <Q label="Pose missing" v={qs.pose_missing_rate} />
              <Q label="LH missing" v={qs.left_hand_missing_rate} />
              <Q label="RH missing" v={qs.right_hand_missing_rate} />
              <Q label="All-zero rate" v={qs.all_zero_rate} />
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              {Object.entries(j.output_urls || {}).map(([k, u]) => (
                <a key={k} href={u as string} target="_blank" rel="noreferrer" className="btn-ghost text-xs">⬇ {k}</a>
              ))}
            </div>
          </div>
        </div>
      )}

      {frames.length > 0 && (
        <details className="mt-4">
          <summary className="cursor-pointer text-sm font-semibold text-gray-700">
            Chi tiết detection theo frame ({frames.length})
          </summary>
          <div className="mt-2 overflow-x-auto">
            <table className="text-xs w-full border">
              <thead className="bg-gray-100 text-left">
                <tr>
                  <th className="px-2 py-1">#</th>
                  <th className="px-2 py-1">orig_idx</th>
                  <th className="px-2 py-1">pose</th>
                  <th className="px-2 py-1">LH</th>
                  <th className="px-2 py-1">RH</th>
                  <th className="px-2 py-1">all-zero</th>
                  <th className="px-2 py-1">files</th>
                </tr>
              </thead>
              <tbody>
                {frames.map((f: any) => (
                  <tr key={f.sample_index} className="border-t">
                    <td className="px-2 py-1">{f.sample_index}</td>
                    <td className="px-2 py-1">{f.original_frame_index}</td>
                    <td className="px-2 py-1"><Badge ok={f.has_pose} /></td>
                    <td className="px-2 py-1"><Badge ok={f.has_left_hand} /></td>
                    <td className="px-2 py-1"><Badge ok={f.has_right_hand} /></td>
                    <td className="px-2 py-1">{f.is_all_zero
                      ? <span className="chip bg-red-100 text-red-700">yes</span>
                      : <span className="chip bg-gray-100 text-gray-600">no</span>}</td>
                    <td className="px-2 py-1 font-mono text-[10px] text-gray-500 truncate max-w-[280px]">{f.pair_file}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </div>
  );
}

function Badge({ ok }: { ok: boolean }) {
  return ok
    ? <span className="chip bg-green-100 text-green-700">Detected</span>
    : <span className="chip bg-red-100 text-red-700">Missing</span>;
}

function D({ label, n, T, danger }: { label: string; n?: number; T: number; danger?: boolean }) {
  const has = n != null && T > 0;
  return (
    <div className={`rounded-md px-3 py-2 border text-xs ${danger && (n || 0) > 0 ? "bg-red-50 border-red-200" : "bg-gray-50 border-gray-200"}`}>
      <div className="text-gray-500">{label}</div>
      <div className="font-semibold">{has ? `${n} / ${T}` : "—"}</div>
    </div>
  );
}

function Q({ label, v }: { label: string; v?: number }) {
  const pct = ((v ?? 0) * 100);
  const warn = pct > 30;
  return (
    <div className={`rounded-md px-3 py-2 border text-xs ${warn ? "bg-amber-50 border-amber-200" : "bg-gray-50 border-gray-200"}`}>
      <div className="text-gray-500">{label}</div>
      <div className="font-semibold">{pct.toFixed(1)}%</div>
    </div>
  );
}

function Q({ label, v }: { label: string; v?: number }) {
  const pct = ((v ?? 0) * 100);
  const warn = pct > 30;
  return (
    <div className={`rounded-md px-3 py-2 border text-xs ${warn ? "bg-amber-50 border-amber-200" : "bg-gray-50 border-gray-200"}`}>
      <div className="text-gray-500">{label}</div>
      <div className="font-semibold">{pct.toFixed(1)}%</div>
    </div>
  );
}
