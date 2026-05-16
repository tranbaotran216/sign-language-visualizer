import { useEffect, useState } from "react";
import { safeLabel } from "../lib/api";

type Output = {
  project_dir: string;
  video_name: string;
  label: string;
  safe_label: string;
  grid_url?: string | null;
  manifest?: any;
};

type SelFrame = {
  sample_index: number;
  original_frame_index: number;
  rgb_path?: string;
  pose_path?: string;
  pair_path?: string;
  thumb?: string;
};

type Group = {
  video_name: string;
  label: string;
  source: "extraction" | "upload";
  project_dir?: string;
  all_frames: SelFrame[];
  selected_idx: number[]; // indices into all_frames
};

const DEFAULT_LAYOUT = {
  tile_width: 240, rgb_height: 145, pose_height: 150,
  cell_gap: 12, row_gap: 42, top_margin: 30, bottom_margin: 30,
  title_font_size: 28, frame_label_font_size: 18,
  background_color: "#ffffff", text_color: "#000000",
  include_titles: true, include_frame_labels: true,
};

export default function ComparePage() {
  const [outputs, setOutputs] = useState<Output[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [layout, setLayout] = useState({ ...DEFAULT_LAYOUT });
  const [frameCount, setFrameCount] = useState(5);
  const [selectMode, setSelectMode] = useState<"first" | "even" | "manual">("even");
  const [capEn, setCapEn] = useState("");
  const [capVi, setCapVi] = useState("");
  const [result, setResult] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => { reloadOutputs(); }, []);
  async function reloadOutputs() {
    const r = await fetch("/api/outputs");
    const d = await r.json();
    setOutputs(d.items || []);
  }

  function addFromExtraction(o: Output) {
    if (groups.length >= 5) return;
    const m = o.manifest;
    if (!m) return;
    const frames: SelFrame[] = (m.frames || []).map((f: any) => ({
      sample_index: f.sample_index,
      original_frame_index: f.original_frame_index,
      rgb_path: `${o.project_dir}/${f.rgb_file}`,
      pose_path: `${o.project_dir}/${f.pose_file}`,
      pair_path: `${o.project_dir}/${f.pair_file}`,
      thumb: `/files/${o.project_dir}/${f.pair_file}`,
    }));
    const sel = pickFrames(frames.length, frameCount, selectMode);
    setGroups(g => [...g, {
      video_name: o.video_name, label: o.label, source: "extraction",
      project_dir: o.project_dir, all_frames: frames, selected_idx: sel,
    }]);
  }

  async function addFromUpload(files: FileList | null) {
    if (!files || files.length === 0 || groups.length >= 5) return;
    const fd = new FormData();
    Array.from(files).forEach(f => fd.append("files", f));
    const r = await fetch("/api/compare/upload-frames", { method: "POST", body: fd });
    if (!r.ok) { setErr(await r.text()); return; }
    const d = await r.json();

    // group by sample_index
    const byIdx = new Map<string, any>();
    for (const fm of d.files) {
      if (!fm.sample_index && fm.sample_index !== 0) continue;
      const k = String(fm.sample_index) + "_" + String(fm.original_frame_index);
      const cur = byIdx.get(k) || {
        sample_index: fm.sample_index, original_frame_index: fm.original_frame_index,
      };
      if (fm.kind === "rgb") cur.rgb_path = fm.path;
      if (fm.kind === "pose") cur.pose_path = fm.path;
      if (fm.kind === "pair") { cur.pair_path = fm.path; cur.thumb = fm.url; }
      if (!cur.thumb) cur.thumb = fm.url;
      byIdx.set(k, cur);
    }
    const frames: SelFrame[] = Array.from(byIdx.values()).sort((a, b) => a.sample_index - b.sample_index);
    const first = d.files.find((x: any) => x.video_name);
    setGroups(g => [...g, {
      video_name: first?.video_name || "video",
      label: first?.safe_label || "label",
      source: "upload",
      all_frames: frames,
      selected_idx: pickFrames(frames.length, frameCount, selectMode),
    }]);
  }

  function patchGroup(i: number, p: Partial<Group>) {
    setGroups(gs => gs.map((g, k) => k === i ? { ...g, ...p } : g));
  }
  function toggleFrame(gi: number, fi: number) {
    setGroups(gs => gs.map((g, k) => {
      if (k !== gi) return g;
      const s = new Set(g.selected_idx);
      s.has(fi) ? s.delete(fi) : s.add(fi);
      return { ...g, selected_idx: Array.from(s).sort((a, b) => a - b) };
    }));
  }
  function resample(gi: number) {
    setGroups(gs => gs.map((g, k) => k === gi
      ? { ...g, selected_idx: pickFrames(g.all_frames.length, frameCount, selectMode) } : g));
  }
  function resampleAll() {
    setGroups(gs => gs.map(g => ({ ...g, selected_idx: pickFrames(g.all_frames.length, frameCount, selectMode) })));
  }

  async function generate() {
    if (groups.length < 2) { setErr("Cần 2 đến 5 video."); return; }
    setBusy(true); setErr(null); setResult(null);
    try {
      const payload = {
        layout, caption_en: capEn || undefined, caption_vi: capVi || undefined,
        include_quality_report: true,
        groups: groups.map(g => ({
          video_name: g.video_name, label: g.label, source: g.source,
          selected_frames: g.selected_idx.map(i => g.all_frames[i]).filter(Boolean),
        })),
      };
      const r = await fetch("/api/compare", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!r.ok) throw new Error(await r.text());
      setResult(await r.json());
    } catch (e: any) { setErr(e.message); }
    finally { setBusy(false); }
  }

  return (
    <div>
      <h1 className="text-2xl font-bold">So sánh frames đã trích xuất</h1>
      <p className="text-sm text-gray-600 mt-1">Chọn 2–5 video. Mỗi video một dòng, mỗi cột là một frame (RGB trên, pose dưới).</p>

      {/* Source picker */}
      <div className="grid md:grid-cols-2 gap-5 mt-6">
        <div className="card">
          <h2 className="font-semibold mb-3">A. Chọn từ extraction outputs</h2>
          {outputs.length === 0 && <div className="text-sm text-gray-500">Chưa có output nào. Trích xuất video trước.</div>}
          <div className="grid sm:grid-cols-2 gap-3 max-h-80 overflow-auto pr-1">
            {outputs.map(o => (
              <button key={o.project_dir}
                onClick={() => addFromExtraction(o)}
                disabled={groups.length >= 5}
                className="text-left border rounded-md p-2 hover:border-brand-300 hover:shadow-sm disabled:opacity-40">
                {o.grid_url && <img src={o.grid_url} className="w-full h-20 object-cover rounded" />}
                <div className="text-sm font-medium mt-1 truncate">{o.video_name}</div>
                <div className="text-xs text-gray-500 truncate">{o.label}</div>
              </button>
            ))}
          </div>
        </div>
        <div className="card">
          <h2 className="font-semibold mb-3">B. Upload ảnh thủ công</h2>
          <p className="text-xs text-gray-500 mb-2">
            Tên file kỳ vọng: <code>pair_VID_label_000_000000.jpg</code> hoặc rgb/pose tương ứng.
          </p>
          <input type="file" multiple accept="image/*" className="input"
                 onChange={e => addFromUpload(e.target.files)} disabled={groups.length >= 5} />
        </div>
      </div>

      {/* Frame selection settings */}
      <div className="card mt-6 grid sm:grid-cols-4 gap-3 items-end">
        <Field label="Số frame hiển thị">
          <input type="number" className="input" value={frameCount}
                 onChange={e => setFrameCount(Math.max(1, +e.target.value))} />
        </Field>
        <Field label="Chế độ chọn">
          <select className="input" value={selectMode} onChange={e => setSelectMode(e.target.value as any)}>
            <option value="even">Evenly sampled</option>
            <option value="first">First N</option>
            <option value="manual">Manual</option>
          </select>
        </Field>
        <button className="btn-ghost" onClick={resampleAll} disabled={groups.length === 0}>Áp dụng cho tất cả</button>
      </div>

      {/* Groups */}
      <div className="mt-6 space-y-4">
        {groups.map((g, i) => (
          <div key={i} className="card">
            <div className="flex flex-wrap items-end gap-3">
              <Field label="Video name"><input className="input" value={g.video_name} onChange={e => patchGroup(i, { video_name: e.target.value })} /></Field>
              <Field label="Ground truth"><input className="input" value={g.label} onChange={e => patchGroup(i, { label: e.target.value })} /></Field>
              <div className="text-xs text-gray-500">Source: {g.source} · {g.all_frames.length} frames</div>
              <button className="btn-ghost ml-auto" onClick={() => resample(i)}>Resample</button>
              <button className="btn-ghost text-red-600" onClick={() => setGroups(gs => gs.filter((_, k) => k !== i))}>Xoá</button>
            </div>
            <div className="mt-3 flex gap-2 overflow-x-auto pb-2">
              {g.all_frames.map((f, fi) => {
                const sel = g.selected_idx.includes(fi);
                return (
                  <button key={fi} onClick={() => toggleFrame(i, fi)}
                    className={`shrink-0 border rounded p-1 ${sel ? "border-brand-500 ring-2 ring-brand-200" : "border-gray-200"}`}>
                    {f.thumb ? <img src={f.thumb} className="w-20 h-24 object-cover rounded" />
                      : <div className="w-20 h-24 bg-gray-100 rounded grid place-items-center text-xs text-gray-400">no thumb</div>}
                    <div className="text-[10px] text-center mt-1">F{f.sample_index}</div>
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      {/* Layout settings */}
      <details className="card mt-6">
        <summary className="font-semibold cursor-pointer">Layout settings</summary>
        <div className="grid sm:grid-cols-3 md:grid-cols-6 gap-3 mt-3">
          {(["tile_width", "rgb_height", "pose_height", "cell_gap", "row_gap", "title_font_size", "frame_label_font_size"] as const).map(k => (
            <Field key={k} label={k}>
              <input type="number" className="input" value={(layout as any)[k]}
                onChange={e => setLayout({ ...layout, [k]: +e.target.value })} />
            </Field>
          ))}
          <Field label="background_color">
            <input type="color" className="input h-10" value={layout.background_color}
              onChange={e => setLayout({ ...layout, background_color: e.target.value })} />
          </Field>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={layout.include_titles} onChange={e => setLayout({ ...layout, include_titles: e.target.checked })} />Include titles
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={layout.include_frame_labels} onChange={e => setLayout({ ...layout, include_frame_labels: e.target.checked })} />Frame labels
          </label>
        </div>
      </details>

      <div className="card mt-6">
        <div className="grid sm:grid-cols-2 gap-3">
          <Field label="Caption (EN) — để trống để tự sinh"><input className="input" value={capEn} onChange={e => setCapEn(e.target.value)} /></Field>
          <Field label="Caption (VI) — để trống để tự sinh"><input className="input" value={capVi} onChange={e => setCapVi(e.target.value)} /></Field>
        </div>
      </div>

      <div className="mt-6 flex items-center gap-3">
        <button className="btn-primary" onClick={generate} disabled={busy || groups.length < 2}>
          {busy ? "Đang render…" : "Tạo ảnh so sánh + PDF"}
        </button>
        {err && <span className="text-sm text-red-600">{err}</span>}
      </div>

      {result && (
        <div className="card mt-6">
          <h2 className="font-semibold">Kết quả · {result.comparison_id}</h2>
          <img src={result.comparison_image_url} className="w-full border rounded mt-3" />
          <p className="text-sm text-gray-700 mt-3"><b>EN:</b> {result.caption_en}</p>
          <p className="text-sm text-gray-700"><b>VI:</b> {result.caption_vi}</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <a className="btn-ghost" href={result.comparison_image_url} download>⬇ JPG</a>
            <a className="btn-ghost" href={result.comparison_png_url} download>⬇ PNG</a>
            <a className="btn-ghost" href={result.comparison_pdf_url} download>⬇ PDF report</a>
            <a className="btn-ghost" href={result.comparison_config_json_url} download>⬇ config.json</a>
            <a className="btn-ghost" href={result.comparison_zip_url} download>⬇ ZIP</a>
          </div>
        </div>
      )}
    </div>
  );
}

function Field({ label, children }: any) {
  return <div><label className="label">{label}</label>{children}</div>;
}

function pickFrames(total: number, n: number, mode: "first" | "even" | "manual"): number[] {
  if (total === 0) return [];
  n = Math.min(n, total);
  if (mode === "first") return Array.from({ length: n }, (_, i) => i);
  if (mode === "manual") return [];
  // even
  if (n === 1) return [0];
  return Array.from({ length: n }, (_, i) => Math.round((i * (total - 1)) / (n - 1)));
}
