import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { usePersistedState } from "../lib/session";

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
  title?: string;
  source: "extraction" | "upload";
  project_dir?: string;
  all_frames: SelFrame[];
  selected_idx: number[];
};

type Annotation =
  | { id: string; type: "text"; x: number; y: number; text: string; color: string; font_size: number }
  | { id: string; type: "rect"; x: number; y: number; w: number; h: number; color: string; stroke: number }
  | { id: string; type: "arrow"; x1: number; y1: number; x2: number; y2: number; color: string; stroke: number };

const DEFAULT_LAYOUT = {
  tile_width: 240, rgb_height: 145, pose_height: 150,
  cell_gap: 12, row_gap: 42, top_margin: 30, bottom_margin: 30, side_margin: 30,
  title_font_size: 28, frame_label_font_size: 18,
  background_color: "#ffffff", text_color: "#000000",
  include_titles: true, include_frame_labels: true,
};

export default function ComparePage() {
  const [outputs, setOutputs] = useState<Output[]>([]);
  const [groups, setGroups] = usePersistedState<Group[]>("compare.groups", []);
  const [layout, setLayout] = usePersistedState("compare.layout", { ...DEFAULT_LAYOUT });
  const [frameCount, setFrameCount] = usePersistedState("compare.frameCount", 5);
  const [selectMode, setSelectMode] = usePersistedState<"first" | "even" | "manual">("compare.selectMode", "even");
  const [capEn, setCapEn] = usePersistedState("compare.capEn", "");
  const [capVi, setCapVi] = usePersistedState("compare.capVi", "");
  const [annotations, setAnnotations] = usePersistedState<Annotation[]>("compare.annotations", []);
  const [result, setResult] = usePersistedState<any>("compare.result", null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const loadCfgInput = useRef<HTMLInputElement>(null);

  useEffect(() => { reloadOutputs(); }, []);
  useEffect(() => {
    const raw = sessionStorage.getItem("preload_comparison_config");
    if (!raw) return;
    sessionStorage.removeItem("preload_comparison_config");
    try { loadConfigFile(new File([raw], "preload.json", { type: "application/json" })); } catch {}
  }, []);
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
    const byIdx = new Map<string, any>();
    for (const fm of d.files) {
      if (fm.sample_index == null) continue;
      const k = `${fm.sample_index}_${fm.original_frame_index}`;
      const cur = byIdx.get(k) || { sample_index: fm.sample_index, original_frame_index: fm.original_frame_index };
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
      source: "upload", all_frames: frames,
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
  function moveSelected(gi: number, pos: number, dir: -1 | 1) {
    setGroups(gs => gs.map((g, k) => {
      if (k !== gi) return g;
      const arr = [...g.selected_idx];
      const j = pos + dir;
      if (j < 0 || j >= arr.length) return g;
      [arr[pos], arr[j]] = [arr[j], arr[pos]];
      return { ...g, selected_idx: arr };
    }));
  }
  function removeSelected(gi: number, pos: number) {
    setGroups(gs => gs.map((g, k) => k === gi
      ? { ...g, selected_idx: g.selected_idx.filter((_, i) => i !== pos) } : g));
  }
  async function replaceSelected(gi: number, pos: number, file: File) {
    const fd = new FormData(); fd.append("files", file);
    const r = await fetch("/api/compare/upload-frames", { method: "POST", body: fd });
    if (!r.ok) { setErr(await r.text()); return; }
    const d = await r.json(); const fm = d.files[0];
    setGroups(gs => gs.map((g, k) => {
      if (k !== gi) return g;
      const fi = g.selected_idx[pos];
      const newFrame: SelFrame = {
        ...g.all_frames[fi],
        ...(fm.kind === "rgb" ? { rgb_path: fm.path } :
            fm.kind === "pose" ? { pose_path: fm.path } :
            { pair_path: fm.path, thumb: fm.url }),
      };
      if (!newFrame.thumb) newFrame.thumb = fm.url;
      const all = [...g.all_frames]; all[fi] = newFrame;
      return { ...g, all_frames: all };
    }));
  }
  function resample(gi: number) {
    setGroups(gs => gs.map((g, k) => k === gi
      ? { ...g, selected_idx: pickFrames(g.all_frames.length, frameCount, selectMode) } : g));
  }
  function resampleAll() {
    setGroups(gs => gs.map(g => ({ ...g, selected_idx: pickFrames(g.all_frames.length, frameCount, selectMode) })));
  }

  function buildPayload() {
    return {
      layout, caption_en: capEn || undefined, caption_vi: capVi || undefined,
      include_quality_report: true,
      annotations,
      groups: groups.map(g => ({
        video_name: g.video_name, label: g.label, title: g.title, source: g.source,
        selected_frames: g.selected_idx.map(i => g.all_frames[i]).filter(Boolean),
      })),
    };
  }

  async function generate(rerenderId?: string) {
    if (groups.length < 2) { setErr("Cần 2 đến 5 video."); return; }
    setBusy(true); setErr(null);
    try {
      const url = rerenderId ? `/api/compare/${rerenderId}/rerender` : "/api/compare";
      const r = await fetch(url, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(buildPayload()),
      });
      if (!r.ok) throw new Error(await r.text());
      setResult(await r.json());
    } catch (e: any) { setErr(e.message); }
    finally { setBusy(false); }
  }

  function downloadConfig() {
    const blob = new Blob([JSON.stringify(buildPayload(), null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "comparison_config.json";
    a.click();
  }

  async function loadConfigFile(f: File) {
    try {
      const cfg = JSON.parse(await f.text());
      setLayout({ ...DEFAULT_LAYOUT, ...(cfg.layout || {}) });
      setCapEn(cfg.caption_en || "");
      setCapVi(cfg.caption_vi || "");
      setAnnotations(cfg.annotations || []);
      const gs: Group[] = (cfg.groups || []).map((g: any) => ({
        video_name: g.video_name, label: g.label, title: g.title,
        source: g.source || "upload", project_dir: g.project_dir,
        all_frames: g.selected_frames || [],
        selected_idx: (g.selected_frames || []).map((_: any, i: number) => i),
      }));
      setGroups(gs);
      setResult(null);
    } catch (e: any) { setErr("Config JSON không hợp lệ: " + e.message); }
  }

  // Annotation helpers
  function addAnnotation(type: Annotation["type"]) {
    const id = Math.random().toString(36).slice(2, 8);
    if (type === "text") setAnnotations(a => [...a, { id, type, x: 40, y: 40, text: "Chú thích", color: "#e11d48", font_size: 24 }]);
    if (type === "rect") setAnnotations(a => [...a, { id, type, x: 40, y: 40, w: 200, h: 120, color: "#e11d48", stroke: 3 }]);
    if (type === "arrow") setAnnotations(a => [...a, { id, type, x1: 40, y1: 40, x2: 200, y2: 120, color: "#e11d48", stroke: 3 }]);
  }
  function patchAnn(id: string, p: any) {
    setAnnotations(a => a.map(x => x.id === id ? { ...x, ...p } : x));
  }
  function removeAnn(id: string) { setAnnotations(a => a.filter(x => x.id !== id)); }

  return (
    <div>
      <h1 className="text-2xl font-bold">So sánh frames đã trích xuất</h1>
      <p className="text-sm text-gray-600 mt-1">Chọn 2–5 video. Mỗi video một dòng, mỗi cột là một frame (RGB trên, pose dưới).</p>

      <div className="mt-3 flex flex-wrap gap-2">
        <button className="btn-ghost text-xs" onClick={() => loadCfgInput.current?.click()}>📥 Mở lại config JSON</button>
        <input type="file" ref={loadCfgInput} accept="application/json" className="hidden"
               onChange={e => e.target.files && loadConfigFile(e.target.files[0])} />
        <button className="btn-ghost text-xs" onClick={downloadConfig} disabled={groups.length === 0}>💾 Lưu config JSON</button>
      </div>

      {/* Source picker */}
      <div className="grid md:grid-cols-2 gap-5 mt-4">
        <div className="card">
          <h2 className="font-semibold mb-3">A. Chọn từ extraction outputs</h2>
          {outputs.length === 0 && <div className="text-sm text-gray-500">Chưa có output nào. Trích xuất video trước.</div>}
          <div className="grid sm:grid-cols-2 gap-3 max-h-80 overflow-auto pr-1">
            {outputs.map(o => (
              <button key={o.project_dir} onClick={() => addFromExtraction(o)} disabled={groups.length >= 5}
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
          <p className="text-xs text-gray-500 mb-2">Tên file: <code>pair_VID_label_000_000000.jpg</code> hoặc rgb/pose.</p>
          <input type="file" multiple accept="image/*" className="input"
                 onChange={e => addFromUpload(e.target.files)} disabled={groups.length >= 5} />
        </div>
      </div>

      {/* Frame selection */}
      <div className="card mt-6 grid sm:grid-cols-4 gap-3 items-end">
        <Field label="Số frame hiển thị"><input type="number" className="input" value={frameCount}
          onChange={e => setFrameCount(Math.max(1, +e.target.value))} /></Field>
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
              <Field label="Row title (ghi đè)"><input className="input" value={g.title || ""} placeholder="auto" onChange={e => patchGroup(i, { title: e.target.value })} /></Field>
              <div className="text-xs text-gray-500">Source: {g.source} · {g.all_frames.length} frames · chọn {g.selected_idx.length}</div>
              <button className="btn-ghost ml-auto" onClick={() => resample(i)}>Resample</button>
              <button className="btn-ghost text-red-600" onClick={() => setGroups(gs => gs.filter((_, k) => k !== i))}>Xoá</button>
            </div>

            {/* All frames picker */}
            <div className="mt-3 text-xs text-gray-500">Tick để chọn frames:</div>
            <div className="mt-1 flex gap-2 overflow-x-auto pb-2">
              {g.all_frames.map((f, fi) => {
                const sel = g.selected_idx.includes(fi);
                return (
                  <button key={fi} onClick={() => toggleFrame(i, fi)}
                    className={`shrink-0 border rounded p-1 ${sel ? "border-brand-500 ring-2 ring-brand-200" : "border-gray-200"}`}>
                    {f.thumb ? <img src={f.thumb} className="w-20 h-24 object-cover rounded" />
                      : <div className="w-20 h-24 bg-gray-100 rounded grid place-items-center text-[10px] text-gray-400">no thumb</div>}
                    <div className="text-[10px] text-center mt-1">F{f.sample_index}</div>
                  </button>
                );
              })}
            </div>

            {/* Ordered selected frames with reorder/remove/replace */}
            {g.selected_idx.length > 0 && (
              <div className="mt-3">
                <div className="text-xs text-gray-500 mb-1">Thứ tự hiển thị (kéo bằng ◀ ▶):</div>
                <div className="flex gap-2 overflow-x-auto">
                  {g.selected_idx.map((fi, pos) => {
                    const f = g.all_frames[fi];
                    return (
                      <div key={pos} className="shrink-0 border rounded p-1 bg-gray-50">
                        {f?.thumb ? <img src={f.thumb} className="w-20 h-24 object-cover rounded" />
                          : <div className="w-20 h-24 bg-gray-100 rounded" />}
                        <div className="text-[10px] text-center">#{pos + 1} · F{f?.sample_index}</div>
                        <div className="flex justify-between mt-1">
                          <button className="text-xs px-1" title="Trái" onClick={() => moveSelected(i, pos, -1)}>◀</button>
                          <label className="text-xs px-1 cursor-pointer text-brand-600" title="Replace">
                            ↻
                            <input type="file" accept="image/*" className="hidden"
                              onChange={e => e.target.files && replaceSelected(i, pos, e.target.files[0])} />
                          </label>
                          <button className="text-xs px-1 text-red-600" title="Xoá" onClick={() => removeSelected(i, pos)}>✕</button>
                          <button className="text-xs px-1" title="Phải" onClick={() => moveSelected(i, pos, 1)}>▶</button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Layout settings */}
      <details className="card mt-6">
        <summary className="font-semibold cursor-pointer">Layout settings</summary>
        <div className="grid sm:grid-cols-3 md:grid-cols-6 gap-3 mt-3">
          {(["tile_width", "rgb_height", "pose_height", "cell_gap", "row_gap", "top_margin", "bottom_margin", "side_margin", "title_font_size", "frame_label_font_size"] as const).map(k => (
            <Field key={k} label={k}>
              <input type="number" className="input" value={(layout as any)[k]}
                onChange={e => setLayout({ ...layout, [k]: +e.target.value })} />
            </Field>
          ))}
          <Field label="background_color">
            <input type="color" className="input h-10" value={layout.background_color}
              onChange={e => setLayout({ ...layout, background_color: e.target.value })} />
          </Field>
          <Field label="text_color">
            <input type="color" className="input h-10" value={layout.text_color}
              onChange={e => setLayout({ ...layout, text_color: e.target.value })} />
          </Field>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={layout.include_titles} onChange={e => setLayout({ ...layout, include_titles: e.target.checked })} />Include titles
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={layout.include_frame_labels} onChange={e => setLayout({ ...layout, include_frame_labels: e.target.checked })} />Frame labels
          </label>
        </div>
      </details>

      {/* Annotations editor */}
      <details className="card mt-6" open={annotations.length > 0}>
        <summary className="font-semibold cursor-pointer">Annotations (text / rectangle / arrow)</summary>
        <div className="mt-3 flex flex-wrap gap-2">
          <button className="btn-ghost" onClick={() => addAnnotation("text")}>+ Text</button>
          <button className="btn-ghost" onClick={() => addAnnotation("rect")}>+ Rectangle</button>
          <button className="btn-ghost" onClick={() => addAnnotation("arrow")}>+ Arrow</button>
          <span className="text-xs text-gray-500 self-center">Toạ độ tính bằng pixel trên canvas đã render.</span>
        </div>
        <div className="mt-3 space-y-2">
          {annotations.map(a => (
            <div key={a.id} className="border rounded p-2 bg-gray-50 flex flex-wrap items-end gap-2">
              <span className="chip bg-gray-200">{a.type}</span>
              {a.type === "text" && (<>
                <Field label="x"><input type="number" className="input w-20" value={a.x} onChange={e => patchAnn(a.id, { x: +e.target.value })} /></Field>
                <Field label="y"><input type="number" className="input w-20" value={a.y} onChange={e => patchAnn(a.id, { y: +e.target.value })} /></Field>
                <Field label="text"><input className="input" value={a.text} onChange={e => patchAnn(a.id, { text: e.target.value })} /></Field>
                <Field label="size"><input type="number" className="input w-20" value={a.font_size} onChange={e => patchAnn(a.id, { font_size: +e.target.value })} /></Field>
              </>)}
              {a.type === "rect" && (<>
                <Field label="x"><input type="number" className="input w-20" value={a.x} onChange={e => patchAnn(a.id, { x: +e.target.value })} /></Field>
                <Field label="y"><input type="number" className="input w-20" value={a.y} onChange={e => patchAnn(a.id, { y: +e.target.value })} /></Field>
                <Field label="w"><input type="number" className="input w-20" value={a.w} onChange={e => patchAnn(a.id, { w: +e.target.value })} /></Field>
                <Field label="h"><input type="number" className="input w-20" value={a.h} onChange={e => patchAnn(a.id, { h: +e.target.value })} /></Field>
                <Field label="stroke"><input type="number" className="input w-20" value={a.stroke} onChange={e => patchAnn(a.id, { stroke: +e.target.value })} /></Field>
              </>)}
              {a.type === "arrow" && (<>
                <Field label="x1"><input type="number" className="input w-20" value={a.x1} onChange={e => patchAnn(a.id, { x1: +e.target.value })} /></Field>
                <Field label="y1"><input type="number" className="input w-20" value={a.y1} onChange={e => patchAnn(a.id, { y1: +e.target.value })} /></Field>
                <Field label="x2"><input type="number" className="input w-20" value={a.x2} onChange={e => patchAnn(a.id, { x2: +e.target.value })} /></Field>
                <Field label="y2"><input type="number" className="input w-20" value={a.y2} onChange={e => patchAnn(a.id, { y2: +e.target.value })} /></Field>
                <Field label="stroke"><input type="number" className="input w-20" value={a.stroke} onChange={e => patchAnn(a.id, { stroke: +e.target.value })} /></Field>
              </>)}
              <Field label="color"><input type="color" className="input h-9 w-14" value={a.color} onChange={e => patchAnn(a.id, { color: e.target.value })} /></Field>
              <button className="btn-ghost text-red-600 text-xs" onClick={() => removeAnn(a.id)}>Xoá</button>
            </div>
          ))}
        </div>
      </details>

      <div className="card mt-6">
        <div className="grid sm:grid-cols-2 gap-3">
          <Field label="Caption (EN) — để trống để tự sinh"><input className="input" value={capEn} onChange={e => setCapEn(e.target.value)} /></Field>
          <Field label="Caption (VI) — để trống để tự sinh"><input className="input" value={capVi} onChange={e => setCapVi(e.target.value)} /></Field>
        </div>
      </div>

      <div className="mt-6 flex items-center gap-3 flex-wrap">
        <button className="btn-primary" onClick={() => generate()} disabled={busy || groups.length < 2}>
          {busy ? "Đang render…" : "Tạo ảnh so sánh + PDF"}
        </button>
        {result && (
          <button className="btn-ghost" onClick={() => generate(result.comparison_id)} disabled={busy}>
            ↻ Rerender (giữ ID {result.comparison_id})
          </button>
        )}
        {err && <span className="text-sm text-red-600">{err}</span>}
      </div>

      {result && (
        <div className="card mt-6">
          <h2 className="font-semibold">Kết quả · {result.comparison_id}</h2>
          <img src={result.comparison_image_url + "?t=" + Date.now()} className="w-full border rounded mt-3" />
          <p className="text-sm text-gray-700 mt-3"><b>EN:</b> {result.caption_en}</p>
          <p className="text-sm text-gray-700"><b>VI:</b> {result.caption_vi}</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <a className="btn-ghost" href={result.comparison_image_url} download>⬇ JPG</a>
            <a className="btn-ghost" href={result.comparison_png_url} download>⬇ PNG</a>
            <a className="btn-ghost" href={result.comparison_pdf_url} download>⬇ PDF report</a>
            <a className="btn-ghost" href={result.comparison_config_json_url} download>⬇ config.json</a>
            <a className="btn-ghost" href={result.comparison_zip_url} download>⬇ ZIP</a>
            <Link className="btn-primary" to="/comparison-editor"
                  onClick={() => {
                    sessionStorage.setItem("editor.bg", JSON.stringify({
                      url: result.comparison_image_url,
                      comparison_id: result.comparison_id,
                      caption_en: result.caption_en, caption_vi: result.caption_vi,
                      metadata: result.metadata || null,
                    }));
                  }}>✏️ Chỉnh sửa với editor</Link>
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
  if (n === 1) return [0];
  return Array.from({ length: n }, (_, i) => Math.round((i * (total - 1)) / (n - 1)));
}
