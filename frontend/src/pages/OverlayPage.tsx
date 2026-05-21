import { useEffect, useMemo, useState } from "react";
import { api, FILES } from "../lib/api";
import { usePersistedState } from "../lib/session";
import { useToast } from "../components/Toast";

type OutputItem = {
  project_dir: string;
  video_name: string;
  label: string;
  manifest?: any;
};

type Presets = {
  landmark_presets: Record<string, string[]>;
  gradients: string[];
  all_landmarks: string[];
  overlay_types: string[];
  layout_modes: string[];
  background_modes: string[];
};

type OverlayConfig = {
  overlay_type: string;
  layout_mode: string;
  landmark_preset: string;
  selected_landmarks: string[];
  frame_selection: { mode: "evenly" | "preset" | "manual"; count: number; sample_indices: number[] };
  style: {
    color_mode: "gradient" | "single" | "lr_split";
    gradient_name: string;
    single_color?: [number, number, number];
    alpha_start: number;
    alpha_end: number;
    show_start_marker: boolean;
    show_end_marker: boolean;
    show_arrow_direction: boolean;
    line_width: number;
    trajectory_width: number;
    point_radius: number;
    marker_radius: number;
    background_mode: string;
    background_opacity: number;
    show_title: boolean;
    show_legend: boolean;
    show_temporal_legend: boolean;
  };
  title: string;
  caption_en: string;
  caption_vi: string;
};

const DEFAULT_CFG: OverlayConfig = {
  overlay_type: "skeleton",
  layout_mode: "single",
  landmark_preset: "fine_temporal",
  selected_landmarks: [],
  frame_selection: { mode: "evenly", count: 9, sample_indices: [] },
  style: {
    color_mode: "gradient",
    gradient_name: "warm",
    alpha_start: 0.25,
    alpha_end: 1.0,
    show_start_marker: true,
    show_end_marker: true,
    show_arrow_direction: true,
    line_width: 3,
    trajectory_width: 3,
    point_radius: 4,
    marker_radius: 8,
    background_mode: "rgb_middle",
    background_opacity: 0.85,
    show_title: true,
    show_legend: true,
    show_temporal_legend: true,
  },
  title: "",
  caption_en: "",
  caption_vi: "",
};

const TYPE_LABEL: Record<string, string> = {
  skeleton: "Skeleton theo thời gian",
  wrist_path: "Quỹ đạo cổ tay",
  fingertip_path: "Quỹ đạo đầu ngón tay",
  rgb_overlay: "RGB + overlay chuyển động",
};
const LAYOUT_LABEL: Record<string, string> = {
  single: "Đơn (1 video)",
  multi_row: "Nhiều dòng (so sánh)",
  side_by_side: "Cạnh nhau (4 loại overlay)",
};
const BG_LABEL: Record<string, string> = {
  rgb_middle: "RGB frame giữa",
  rgb_first: "RGB frame đầu",
  rgb_index: "RGB theo index",
  white: "Nền trắng",
  dark: "Nền tối",
  transparent: "Trong suốt",
};
const PRESET_LABEL: Record<string, string> = {
  large_trajectory: "Trajectory lớn (wrist + elbow)",
  fine_temporal: "Temporal tinh (wrist + fingertip)",
  occlusion_hand: "Occlusion / bàn tay",
  full_pose: "Toàn bộ pose",
};

export default function OverlayPage() {
  const { push } = useToast();
  const [outputs, setOutputs] = useState<OutputItem[]>([]);
  const [presets, setPresets] = useState<Presets | null>(null);
  const [selected, setSelected] = usePersistedState<string[]>("overlay:selected", []);
  const [cfg, setCfg] = usePersistedState<OverlayConfig>("overlay:cfg", DEFAULT_CFG);
  const [result, setResult] = usePersistedState<any>("overlay:result", null);
  const [busy, setBusy] = useState(false);
  const [history, setHistory] = useState<any[]>([]);

  useEffect(() => {
    api<{ items: OutputItem[] }>("/outputs").then(d => setOutputs(d.items)).catch(() => {});
    api<Presets>("/overlay/presets").then(setPresets).catch(() => {});
    refreshHistory();
  }, []);

  function refreshHistory() {
    api<{ items: any[] }>("/overlay").then(d => setHistory(d.items)).catch(() => {});
  }

  // restore from sessionStorage hand-off (History / Dataset QA / Model Results)
  useEffect(() => {
    const raw = sessionStorage.getItem("kltn:overlay:handoff");
    if (raw) {
      try {
        const h = JSON.parse(raw);
        if (Array.isArray(h?.project_dirs)) setSelected(h.project_dirs);
        if (h?.config) setCfg({ ...DEFAULT_CFG, ...h.config });
        sessionStorage.removeItem("kltn:overlay:handoff");
        push("ok", "Đã nhận dữ liệu overlay từ trang khác.");
      } catch {/* ignore */}
    }
  }, []);

  const selectedT = useMemo(() => {
    if (!selected.length) return 64;
    const first = outputs.find(o => o.project_dir === selected[0]);
    return first?.manifest?.timesteps ?? 64;
  }, [selected, outputs]);

  function toggle(pd: string) {
    setSelected(s => s.includes(pd) ? s.filter(x => x !== pd) : [...s, pd]);
  }

  function update<K extends keyof OverlayConfig>(k: K, v: OverlayConfig[K]) {
    setCfg(c => ({ ...c, [k]: v }));
  }
  function updateStyle<K extends keyof OverlayConfig["style"]>(k: K, v: OverlayConfig["style"][K]) {
    setCfg(c => ({ ...c, style: { ...c.style, [k]: v } }));
  }

  async function generate() {
    if (!selected.length) { push("err", "Chọn ít nhất 1 video đã extract."); return; }
    setBusy(true);
    try {
      const lm = cfg.selected_landmarks.length
        ? cfg.selected_landmarks
        : (presets?.landmark_presets[cfg.landmark_preset] || []);
      const payload = {
        project_dirs: selected,
        config: { ...cfg, selected_landmarks: lm },
      };
      const r = await api("/overlay/create", { method: "POST", body: JSON.stringify(payload) });
      setResult(r);
      push("ok", "Đã tạo overlay.");
      refreshHistory();
    } catch (e: any) {
      push("err", e.message || "Lỗi tạo overlay");
    } finally {
      setBusy(false);
    }
  }

  function downloadConfig() {
    const blob = new Blob([JSON.stringify({ project_dirs: selected, config: cfg }, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `overlay_config_${Date.now()}.json`;
    a.click();
  }
  function loadConfig(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (!f) return;
    const r = new FileReader();
    r.onload = () => {
      try {
        const j = JSON.parse(String(r.result));
        if (Array.isArray(j.project_dirs)) setSelected(j.project_dirs);
        if (j.config) setCfg({ ...DEFAULT_CFG, ...j.config });
        push("ok", "Đã nạp project JSON.");
      } catch { push("err", "JSON không hợp lệ"); }
    };
    r.readAsText(f);
  }

  function setPresetSampling(count: number) {
    update("frame_selection", { mode: "evenly", count, sample_indices: [] });
  }
  function setPresetIndices() {
    update("frame_selection", { mode: "preset", count: 9,
      sample_indices: [0, 8, 16, 24, 32, 40, 48, 56, 63].filter(i => i < selectedT) });
  }
  function toggleLandmark(name: string) {
    setCfg(c => {
      const base = c.selected_landmarks.length ? c.selected_landmarks
        : (presets?.landmark_presets[c.landmark_preset] || []);
      const next = base.includes(name) ? base.filter(x => x !== name) : [...base, name];
      return { ...c, selected_landmarks: next };
    });
  }

  const activeLandmarks = cfg.selected_landmarks.length
    ? cfg.selected_landmarks
    : (presets?.landmark_presets[cfg.landmark_preset] || []);

  return (
    <div>
      <header className="mb-6">
        <h1 className="text-2xl font-bold">Overlay chuyển động</h1>
        <p className="text-sm text-gray-500">Temporal Overlay Visualization — Phase 8</p>
      </header>

      <div className="grid grid-cols-12 gap-4">
        {/* ---------------- LEFT: source ---------------- */}
        <section className="col-span-12 lg:col-span-3 bg-white border border-gray-200 rounded-md p-4">
          <h2 className="font-semibold mb-2">Nguồn dữ liệu</h2>
          <p className="text-xs text-gray-500 mb-3">Chọn video đã extract từ <code>backend/outputs/</code>.</p>
          <div className="space-y-1 max-h-[60vh] overflow-auto pr-1">
            {outputs.length === 0 && <div className="text-sm text-gray-400">Chưa có outputs. Vào /extract để extract trước.</div>}
            {outputs.map(o => (
              <label key={o.project_dir} className="flex items-start gap-2 text-sm px-2 py-1 rounded hover:bg-gray-50 cursor-pointer">
                <input type="checkbox" checked={selected.includes(o.project_dir)} onChange={() => toggle(o.project_dir)} className="mt-1" />
                <div className="min-w-0">
                  <div className="font-medium truncate">{o.video_name} <span className="text-gray-500">— {o.label}</span></div>
                  <div className="text-[11px] text-gray-400 truncate">{o.project_dir}</div>
                </div>
              </label>
            ))}
          </div>
          <div className="text-xs text-gray-500 mt-3">Đã chọn: <b>{selected.length}</b></div>
        </section>

        {/* ---------------- MIDDLE: settings ---------------- */}
        <section className="col-span-12 lg:col-span-5 bg-white border border-gray-200 rounded-md p-4 space-y-4">
          <h2 className="font-semibold">Cài đặt overlay</h2>

          <div>
            <label className="text-xs text-gray-500">Loại overlay</label>
            <div className="grid grid-cols-2 gap-2 mt-1">
              {Object.entries(TYPE_LABEL).map(([k, v]) => (
                <button key={k} onClick={() => update("overlay_type", k)}
                        className={`text-xs px-3 py-2 rounded border ${cfg.overlay_type === k ? "bg-brand-50 border-brand-400 text-brand-700 font-semibold" : "border-gray-200 hover:bg-gray-50"}`}>
                  {v}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="text-xs text-gray-500">Layout</label>
            <select value={cfg.layout_mode} onChange={e => update("layout_mode", e.target.value)}
                    className="w-full mt-1 text-sm border border-gray-200 rounded px-2 py-1.5">
              {Object.entries(LAYOUT_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
            {cfg.layout_mode === "multi_row" && selected.length < 2 &&
              <div className="text-[11px] text-amber-600 mt-1">Chọn ≥2 video để dùng multi-row.</div>}
          </div>

          <div>
            <label className="text-xs text-gray-500">Sampling frame (mặc định 5–10 frames, KHÔNG overlay toàn bộ 64)</label>
            <div className="flex gap-2 mt-1 flex-wrap">
              {[5, 7, 9, 10].map(n => (
                <button key={n} onClick={() => setPresetSampling(n)}
                        className={`text-xs px-3 py-1.5 rounded border ${cfg.frame_selection.mode === "evenly" && cfg.frame_selection.count === n ? "bg-brand-50 border-brand-400" : "border-gray-200"}`}>
                  {n} frames
                </button>
              ))}
              <button onClick={setPresetIndices}
                      className={`text-xs px-3 py-1.5 rounded border ${cfg.frame_selection.mode === "preset" ? "bg-brand-50 border-brand-400" : "border-gray-200"}`}>
                Preset [0,8,16,…,63]
              </button>
            </div>
            <div className="mt-2">
              <label className="text-[11px] text-gray-500">Custom indices (cách nhau bằng dấu phẩy)</label>
              <input className="w-full text-xs border border-gray-200 rounded px-2 py-1 font-mono"
                     placeholder="vd: 0,8,16,24,32"
                     value={cfg.frame_selection.mode === "manual" ? cfg.frame_selection.sample_indices.join(",") : ""}
                     onChange={e => {
                       const arr = e.target.value.split(",").map(s => parseInt(s.trim(), 10)).filter(n => !isNaN(n));
                       update("frame_selection", { mode: "manual", count: arr.length || 9, sample_indices: arr });
                     }} />
            </div>
          </div>

          <div>
            <label className="text-xs text-gray-500">Landmark preset</label>
            <select value={cfg.landmark_preset}
                    onChange={e => { update("landmark_preset", e.target.value); update("selected_landmarks", []); }}
                    className="w-full mt-1 text-sm border border-gray-200 rounded px-2 py-1.5">
              {Object.entries(PRESET_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
            <div className="mt-2 grid grid-cols-2 gap-1">
              {(presets?.all_landmarks || []).map(name => (
                <label key={name} className="flex items-center gap-2 text-[11px] text-gray-700">
                  <input type="checkbox" checked={activeLandmarks.includes(name)} onChange={() => toggleLandmark(name)} />
                  {name}
                </label>
              ))}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-gray-500">Color mode</label>
              <select value={cfg.style.color_mode}
                      onChange={e => updateStyle("color_mode", e.target.value as any)}
                      className="w-full mt-1 text-sm border border-gray-200 rounded px-2 py-1.5">
                <option value="gradient">gradient theo thời gian</option>
                <option value="single">màu đơn</option>
                <option value="lr_split">tách trái/phải</option>
              </select>
            </div>
            <div>
              <label className="text-xs text-gray-500">Gradient</label>
              <select value={cfg.style.gradient_name}
                      onChange={e => updateStyle("gradient_name", e.target.value)}
                      className="w-full mt-1 text-sm border border-gray-200 rounded px-2 py-1.5">
                {(presets?.gradients || ["warm", "cool", "viridis"]).map(g => <option key={g}>{g}</option>)}
              </select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-gray-500">Alpha start: {cfg.style.alpha_start}</label>
              <input type="range" min={0} max={1} step={0.05} value={cfg.style.alpha_start}
                     onChange={e => updateStyle("alpha_start", parseFloat(e.target.value))} className="w-full" />
            </div>
            <div>
              <label className="text-xs text-gray-500">Alpha end: {cfg.style.alpha_end}</label>
              <input type="range" min={0} max={1} step={0.05} value={cfg.style.alpha_end}
                     onChange={e => updateStyle("alpha_end", parseFloat(e.target.value))} className="w-full" />
            </div>
            <div>
              <label className="text-xs text-gray-500">Line width: {cfg.style.line_width}</label>
              <input type="range" min={1} max={8} step={1} value={cfg.style.line_width}
                     onChange={e => updateStyle("line_width", parseInt(e.target.value))} className="w-full" />
            </div>
            <div>
              <label className="text-xs text-gray-500">Trajectory width: {cfg.style.trajectory_width}</label>
              <input type="range" min={1} max={10} step={1} value={cfg.style.trajectory_width}
                     onChange={e => updateStyle("trajectory_width", parseInt(e.target.value))} className="w-full" />
            </div>
            <div>
              <label className="text-xs text-gray-500">Point radius: {cfg.style.point_radius}</label>
              <input type="range" min={1} max={10} step={1} value={cfg.style.point_radius}
                     onChange={e => updateStyle("point_radius", parseInt(e.target.value))} className="w-full" />
            </div>
            <div>
              <label className="text-xs text-gray-500">Marker radius: {cfg.style.marker_radius}</label>
              <input type="range" min={3} max={16} step={1} value={cfg.style.marker_radius}
                     onChange={e => updateStyle("marker_radius", parseInt(e.target.value))} className="w-full" />
            </div>
          </div>

          <div className="grid grid-cols-3 gap-2 text-xs">
            <label className="flex items-center gap-2"><input type="checkbox" checked={cfg.style.show_start_marker} onChange={e => updateStyle("show_start_marker", e.target.checked)} /> start ○</label>
            <label className="flex items-center gap-2"><input type="checkbox" checked={cfg.style.show_end_marker} onChange={e => updateStyle("show_end_marker", e.target.checked)} /> end ●</label>
            <label className="flex items-center gap-2"><input type="checkbox" checked={cfg.style.show_arrow_direction} onChange={e => updateStyle("show_arrow_direction", e.target.checked)} /> arrow ➜</label>
            <label className="flex items-center gap-2"><input type="checkbox" checked={cfg.style.show_title} onChange={e => updateStyle("show_title", e.target.checked)} /> title</label>
            <label className="flex items-center gap-2"><input type="checkbox" checked={cfg.style.show_legend} onChange={e => updateStyle("show_legend", e.target.checked)} /> legend</label>
            <label className="flex items-center gap-2"><input type="checkbox" checked={cfg.style.show_temporal_legend} onChange={e => updateStyle("show_temporal_legend", e.target.checked)} /> temporal bar</label>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-gray-500">Nền RGB</label>
              <select value={cfg.style.background_mode}
                      onChange={e => updateStyle("background_mode", e.target.value)}
                      className="w-full mt-1 text-sm border border-gray-200 rounded px-2 py-1.5">
                {(presets?.background_modes || []).map(m => <option key={m} value={m}>{BG_LABEL[m] || m}</option>)}
              </select>
            </div>
            <div>
              <label className="text-xs text-gray-500">Opacity nền: {cfg.style.background_opacity}</label>
              <input type="range" min={0.2} max={1} step={0.05} value={cfg.style.background_opacity}
                     onChange={e => updateStyle("background_opacity", parseFloat(e.target.value))} className="w-full" />
            </div>
          </div>

          <div className="space-y-2">
            <input className="w-full text-sm border border-gray-200 rounded px-2 py-1.5"
                   placeholder="Tiêu đề / Title"
                   value={cfg.title} onChange={e => update("title", e.target.value)} />
            <input className="w-full text-sm border border-gray-200 rounded px-2 py-1.5"
                   placeholder="Caption EN"
                   value={cfg.caption_en} onChange={e => update("caption_en", e.target.value)} />
            <input className="w-full text-sm border border-gray-200 rounded px-2 py-1.5"
                   placeholder="Chú thích VI"
                   value={cfg.caption_vi} onChange={e => update("caption_vi", e.target.value)} />
          </div>
        </section>

        {/* ---------------- RIGHT: preview + export ---------------- */}
        <section className="col-span-12 lg:col-span-4 bg-white border border-gray-200 rounded-md p-4">
          <h2 className="font-semibold mb-2">Xem trước overlay</h2>
          <div className="flex flex-wrap gap-2 mb-3">
            <button onClick={generate} disabled={busy}
                    className="text-sm px-3 py-1.5 rounded bg-brand-600 text-white disabled:opacity-50">
              {busy ? "Đang render…" : "Tạo overlay"}
            </button>
            <button onClick={downloadConfig} className="text-sm px-3 py-1.5 rounded border border-gray-300">💾 Lưu project JSON</button>
            <label className="text-sm px-3 py-1.5 rounded border border-gray-300 cursor-pointer">
              📂 Mở project JSON
              <input type="file" accept="application/json" onChange={loadConfig} className="hidden" />
            </label>
          </div>

          {result?.png_url ? (
            <div className="space-y-2">
              <img src={FILES + result.png_url.replace("/files", "")} alt="overlay preview"
                   className="w-full border border-gray-200 rounded" />
              <div className="flex flex-wrap gap-2 text-sm">
                <a href={result.png_url} download className="px-3 py-1.5 rounded border border-gray-300">Tải PNG</a>
                <a href={result.jpg_url} download className="px-3 py-1.5 rounded border border-gray-300">Tải JPG</a>
                {result.pdf_url && <a href={result.pdf_url} download className="px-3 py-1.5 rounded border border-gray-300">Tải PDF</a>}
                {result.config_url && <a href={result.config_url} download className="px-3 py-1.5 rounded border border-gray-300">Config JSON</a>}
              </div>
              <div className="text-[11px] text-gray-400">id: {result.overlay_project_id}</div>
            </div>
          ) : (
            <div className="text-sm text-gray-400 border border-dashed border-gray-200 rounded p-6 text-center">
              Bấm <b>Tạo overlay</b> để render preview.
            </div>
          )}

          <hr className="my-4" />
          <h3 className="font-semibold text-sm mb-2">Lịch sử overlay</h3>
          <div className="space-y-2 max-h-[40vh] overflow-auto pr-1">
            {history.length === 0 && <div className="text-xs text-gray-400">Chưa có overlay nào.</div>}
            {history.map(h => (
              <div key={h.overlay_project_id} className="flex items-center gap-2 border border-gray-100 rounded p-2">
                {h.png_url && <img src={h.png_url} className="w-16 h-12 object-cover rounded" />}
                <div className="flex-1 min-w-0">
                  <div className="text-xs truncate">{h.overlay_project_id}</div>
                  <div className="flex gap-2 text-[11px] mt-1">
                    {h.png_url && <a className="text-brand-600" href={h.png_url} target="_blank">PNG</a>}
                    {h.pdf_url && <a className="text-brand-600" href={h.pdf_url} target="_blank">PDF</a>}
                    {h.config_url && <a className="text-brand-600" href={h.config_url} target="_blank">JSON</a>}
                    <button className="text-red-500"
                            onClick={async () => {
                              if (!confirm("Xoá overlay này?")) return;
                              await api(`/overlay/${h.overlay_project_id}`, { method: "DELETE" });
                              refreshHistory();
                            }}>Xoá</button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
