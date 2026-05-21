import { useEffect, useRef, useState } from "react";
import * as fabric from "fabric";
import jsPDF from "jspdf";
import { usePersistedState } from "../lib/session";
import { useToast } from "../components/Toast";

type EditorBg = {
  url: string;
  comparison_id?: string;
  caption_en?: string;
  caption_vi?: string;
  metadata?: any;
};

const DEFAULT_STROKE = "#e11d48";
const DEFAULT_FILL = "transparent";
const DEFAULT_WIDTH = 3;
const DEFAULT_FONT_SIZE = 24;
const DEFAULT_TEXT = "#000000";

type Tool = "select" | "arrow" | "line" | "rect" | "circle" | "oval" | "text";

export default function ComparisonEditorPage() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const fcRef = useRef<fabric.Canvas | null>(null);
  const bgRef = useRef<fabric.Image | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const projectInputRef = useRef<HTMLInputElement>(null);

  const [bg, setBg] = usePersistedState<EditorBg | null>("editor.bgMeta", null);
  const [capEn, setCapEn] = usePersistedState<string>("editor.capEn", "");
  const [capVi, setCapVi] = usePersistedState<string>("editor.capVi", "");
  const [savedJson, setSavedJson] = usePersistedState<any>("editor.json", null);

  const [tool, setTool] = useState<Tool>("select");
  const [stroke, setStroke] = useState(DEFAULT_STROKE);
  const [fill, setFill] = useState<string>(DEFAULT_FILL);
  const [width, setWidth] = useState(DEFAULT_WIDTH);
  const [fontSize, setFontSize] = useState(DEFAULT_FONT_SIZE);
  const [textColor, setTextColor] = useState(DEFAULT_TEXT);
  const [selProps, setSelProps] = useState<any>(null);
  const [zoom, setZoom] = useState(1);

  const undoStack = useRef<string[]>([]);
  const redoStack = useRef<string[]>([]);
  const skipHistory = useRef(false);
  const { push: toast } = useToast();

  // ---- Init ----
  useEffect(() => {
    const c = new fabric.Canvas(canvasRef.current!, {
      backgroundColor: "#f3f4f6",
      preserveObjectStacking: true,
      selection: true,
    });
    fcRef.current = c;

    // Pickup from /compare handoff
    const handoff = sessionStorage.getItem("editor.bg");
    if (handoff) {
      sessionStorage.removeItem("editor.bg");
      try {
        const obj = JSON.parse(handoff) as EditorBg;
        setBg(obj);
        if (obj.caption_en) setCapEn(obj.caption_en);
        if (obj.caption_vi) setCapVi(obj.caption_vi);
        loadBackground(obj.url, () => {
          if (savedJson) restoreObjectsOnly(savedJson);
        });
      } catch {}
    } else if (bg?.url) {
      loadBackground(bg.url, () => {
        if (savedJson) restoreObjectsOnly(savedJson);
      });
    }

    const updateSel = () => {
      const o = c.getActiveObject();
      if (!o) { setSelProps(null); return; }
      setSelProps({
        stroke: (o as any).stroke,
        fill: (o as any).fill,
        strokeWidth: (o as any).strokeWidth,
        fontSize: (o as any).fontSize,
        opacity: o.opacity,
      });
    };
    c.on("selection:created", updateSel);
    c.on("selection:updated", updateSel);
    c.on("selection:cleared", () => setSelProps(null));

    const recordHistory = () => {
      if (skipHistory.current) return;
      undoStack.current.push(JSON.stringify(c.toJSON(["isBackground", "selectable", "evented"])));
      redoStack.current = [];
      autoSave();
    };
    c.on("object:added", recordHistory);
    c.on("object:modified", recordHistory);
    c.on("object:removed", recordHistory);

    const handleKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.tagName === "INPUT" || (e.target as HTMLElement)?.tagName === "TEXTAREA") return;
      if ((e.key === "Delete" || e.key === "Backspace") && c.getActiveObject()) {
        const ao = c.getActiveObject();
        if (ao && !(ao as any).isBackground) { c.remove(ao); c.discardActiveObject().renderAll(); }
      }
      if ((e.ctrlKey || e.metaKey) && e.key === "z") { e.preventDefault(); undo(); }
      if ((e.ctrlKey || e.metaKey) && (e.key === "y" || (e.shiftKey && e.key === "Z"))) { e.preventDefault(); redo(); }
    };
    window.addEventListener("keydown", handleKey);
    return () => {
      window.removeEventListener("keydown", handleKey);
      c.dispose();
      fcRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function autoSave() {
    const c = fcRef.current; if (!c) return;
    const json = c.toJSON(["isBackground", "selectable", "evented"]);
    setSavedJson(json);
  }

  function loadBackground(url: string, after?: () => void) {
    const c = fcRef.current; if (!c) return;
    fabric.Image.fromURL(url, (img) => {
      if (!img) return;
      const maxW = 1200;
      const scale = img.width! > maxW ? maxW / img.width! : 1;
      img.scale(scale);
      img.set({
        left: 0, top: 0, selectable: false, evented: false,
        hasControls: false, hasBorders: false, lockMovementX: true, lockMovementY: true,
      });
      (img as any).isBackground = true;
      c.setWidth(img.getScaledWidth());
      c.setHeight(img.getScaledHeight());
      // Remove old background if any
      c.getObjects().filter((o: any) => o.isBackground).forEach(o => c.remove(o));
      skipHistory.current = true;
      c.add(img); c.sendToBack(img);
      bgRef.current = img;
      skipHistory.current = false;
      c.renderAll();
      after?.();
    }, { crossOrigin: "anonymous" });
  }

  function restoreObjectsOnly(json: any) {
    const c = fcRef.current; if (!c || !json?.objects) return;
    skipHistory.current = true;
    fabric.util.enlivenObjects(
      json.objects.filter((o: any) => !o.isBackground),
      (objs: fabric.Object[]) => {
        objs.forEach(o => c.add(o));
        c.renderAll();
        skipHistory.current = false;
      },
      "fabric",
    );
  }

  // ---- Tools ----
  function addArrow() {
    const c = fcRef.current!;
    const line = new fabric.Line([50, 50, 250, 50], { stroke, strokeWidth: width, selectable: true });
    const head = new fabric.Triangle({
      left: 250, top: 50, originX: "center", originY: "center",
      width: 16 + width * 2, height: 16 + width * 2, fill: stroke, angle: 90,
    });
    const g = new fabric.Group([line, head], { left: 80, top: 80 });
    c.add(g); c.setActiveObject(g);
  }
  function addLine() {
    fcRef.current!.add(new fabric.Line([50, 50, 250, 50], { stroke, strokeWidth: width, left: 80, top: 80 }));
  }
  function addRect() {
    fcRef.current!.add(new fabric.Rect({
      left: 80, top: 80, width: 160, height: 100,
      stroke, strokeWidth: width, fill: fill === "transparent" ? "transparent" : fill,
    }));
  }
  function addCircle() {
    fcRef.current!.add(new fabric.Circle({
      left: 80, top: 80, radius: 60, stroke, strokeWidth: width, fill: fill === "transparent" ? "transparent" : fill,
    }));
  }
  function addOval() {
    fcRef.current!.add(new fabric.Ellipse({
      left: 80, top: 80, rx: 90, ry: 50, stroke, strokeWidth: width, fill: fill === "transparent" ? "transparent" : fill,
    }));
  }
  function addText() {
    const t = new fabric.IText("Chú thích", {
      left: 100, top: 100, fontSize, fill: textColor, fontFamily: "sans-serif",
    });
    fcRef.current!.add(t); fcRef.current!.setActiveObject(t);
  }

  function onToolClick(t: Tool) {
    setTool(t);
    if (t === "arrow") addArrow();
    else if (t === "line") addLine();
    else if (t === "rect") addRect();
    else if (t === "circle") addCircle();
    else if (t === "oval") addOval();
    else if (t === "text") addText();
  }

  function del() {
    const c = fcRef.current!; const o = c.getActiveObject();
    if (o && !(o as any).isBackground) { c.remove(o); c.discardActiveObject().renderAll(); }
  }
  function bringForward() { const c = fcRef.current!; const o = c.getActiveObject(); if (o) { c.bringForward(o); c.renderAll(); autoSave(); } }
  function sendBackward() { const c = fcRef.current!; const o = c.getActiveObject();
    if (o) {
      c.sendBackwards(o);
      // never go below background
      if (bgRef.current) c.sendToBack(bgRef.current);
      c.renderAll(); autoSave();
    }
  }

  function undo() {
    const c = fcRef.current!;
    if (undoStack.current.length < 2) return;
    const cur = undoStack.current.pop()!;
    redoStack.current.push(cur);
    const prev = undoStack.current[undoStack.current.length - 1];
    skipHistory.current = true;
    c.loadFromJSON(prev, () => { c.renderAll(); skipHistory.current = false; autoSave(); });
  }
  function redo() {
    const c = fcRef.current!;
    const nxt = redoStack.current.pop(); if (!nxt) return;
    undoStack.current.push(nxt);
    skipHistory.current = true;
    c.loadFromJSON(nxt, () => { c.renderAll(); skipHistory.current = false; autoSave(); });
  }

  function applyProp(prop: string, value: any) {
    const c = fcRef.current!; const o = c.getActiveObject(); if (!o) return;
    o.set(prop as any, value);
    o.setCoords();
    c.renderAll();
    setSelProps({ ...selProps, [prop]: value });
    autoSave();
  }

  function zoomTo(z: number) {
    const c = fcRef.current!;
    const nz = Math.min(4, Math.max(0.2, z));
    c.setZoom(nz);
    c.setWidth(c.getWidth() * (nz / zoom));
    c.setHeight(c.getHeight() * (nz / zoom));
    setZoom(nz);
  }
  function fitScreen() {
    const c = fcRef.current!;
    if (!bgRef.current) return;
    c.setZoom(1);
    c.setWidth(bgRef.current.getScaledWidth());
    c.setHeight(bgRef.current.getScaledHeight());
    setZoom(1);
  }

  // ---- Background loading ----
  function onBgFile(file: File) {
    const url = URL.createObjectURL(file);
    setBg({ url, comparison_id: undefined });
    loadBackground(url);
  }

  // ---- Export ----
  function dataURL(format: "png" | "jpeg" = "png") {
    const c = fcRef.current!;
    c.discardActiveObject().renderAll();
    return c.toDataURL({ format, quality: 0.95, multiplier: 1 });
  }
  function downloadAs(format: "png" | "jpeg") {
    const url = dataURL(format);
    const a = document.createElement("a");
    a.href = url; a.download = `comparison_annotated.${format === "jpeg" ? "jpg" : "png"}`;
    a.click();
  }
  function exportPdf() {
    const c = fcRef.current!;
    const url = dataURL("png");
    const w = c.getWidth(), h = c.getHeight();
    const orient = w > h ? "landscape" : "portrait";
    const pdf = new jsPDF({ unit: "pt", format: "a4", orientation: orient });
    const pw = pdf.internal.pageSize.getWidth(), ph = pdf.internal.pageSize.getHeight();
    const margin = 32;
    const availW = pw - margin * 2;
    const scale = availW / w;
    const imgH = h * scale;
    pdf.setFontSize(13);
    pdf.text("KLTN VSL · Annotated comparison", margin, margin);
    pdf.addImage(url, "PNG", margin, margin + 14, availW, imgH);

    let y = margin + 14 + imgH + 18;
    pdf.setFontSize(11);
    if (capEn) { pdf.text(`EN: ${capEn}`, margin, y); y += 14; }
    if (capVi) { pdf.text(`VI: ${capVi}`, margin, y); y += 14; }
    if (bg?.metadata) {
      y += 6;
      pdf.setFontSize(10);
      pdf.text("Metadata:", margin, y); y += 12;
      const md = bg.metadata;
      const lines = JSON.stringify(md, null, 2).split("\n");
      for (const ln of lines) {
        if (y > ph - margin) { pdf.addPage(); y = margin; }
        pdf.text(ln, margin, y); y += 11;
      }
    }
    pdf.save("comparison_annotated.pdf");
  }

  function saveProject() {
    const c = fcRef.current!;
    const proj = {
      background_image_url: bg?.url || null,
      comparison_id: bg?.comparison_id || null,
      canvas_width: c.getWidth(),
      canvas_height: c.getHeight(),
      objects: c.toJSON(["isBackground", "selectable", "evented"]),
      caption_en: capEn,
      caption_vi: capVi,
      metadata: bg?.metadata || null,
    };
    const blob = new Blob([JSON.stringify(proj, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `editor_project_${Date.now()}.json`;
    a.click();
  }

  async function loadProject(file: File) {
    try {
      const proj = JSON.parse(await file.text());
      setCapEn(proj.caption_en || "");
      setCapVi(proj.caption_vi || "");
      const newBg: EditorBg = {
        url: proj.background_image_url,
        comparison_id: proj.comparison_id,
        metadata: proj.metadata,
        caption_en: proj.caption_en, caption_vi: proj.caption_vi,
      };
      setBg(newBg);
      if (proj.background_image_url) {
        loadBackground(proj.background_image_url, () => {
          restoreObjectsOnly(proj.objects);
        });
      } else {
        const c = fcRef.current!;
        skipHistory.current = true;
        c.loadFromJSON(proj.objects, () => { c.renderAll(); skipHistory.current = false; autoSave(); });
      }
      toast("ok", "Đã mở project JSON.");
    } catch (e: any) {
      toast("err", "Project JSON không hợp lệ: " + e.message);
    }
  }

  // ---- UI ----
  return (
    <div>
      <h1 className="text-2xl font-bold">Chỉnh sửa ảnh so sánh</h1>
      <p className="text-sm text-gray-600 mt-1">Editor giống draw.io: thêm mũi tên, khung, chữ chú thích trên ảnh so sánh đã sinh.</p>

      {/* Top toolbar */}
      <div className="card mt-4 flex flex-wrap items-center gap-2">
        <TBtn active={tool === "select"} onClick={() => setTool("select")}>↖ Chọn</TBtn>
        <TBtn onClick={() => onToolClick("arrow")}>➜ Mũi tên</TBtn>
        <TBtn onClick={() => onToolClick("line")}>— Đường thẳng</TBtn>
        <TBtn onClick={() => onToolClick("rect")}>▭ Hình chữ nhật</TBtn>
        <TBtn onClick={() => onToolClick("circle")}>● Hình tròn</TBtn>
        <TBtn onClick={() => onToolClick("oval")}>◯ Hình oval</TBtn>
        <TBtn onClick={() => onToolClick("text")}>T Thêm chữ</TBtn>
        <div className="w-px h-6 bg-gray-200 mx-1" />
        <TBtn onClick={undo}>↶ Hoàn tác</TBtn>
        <TBtn onClick={redo}>↷ Làm lại</TBtn>
        <TBtn onClick={del}>🗑 Xoá đối tượng</TBtn>
        <div className="w-px h-6 bg-gray-200 mx-1" />
        <TBtn onClick={() => zoomTo(zoom * 1.2)}>＋ Phóng to</TBtn>
        <TBtn onClick={() => zoomTo(zoom / 1.2)}>－ Thu nhỏ</TBtn>
        <TBtn onClick={fitScreen}>⤢ Vừa màn hình</TBtn>
        <div className="ml-auto flex flex-wrap gap-2">
          <button className="btn-ghost" onClick={() => fileInputRef.current?.click()}>🖼 Đổi background</button>
          <input ref={fileInputRef} type="file" accept="image/*" className="hidden"
                 onChange={e => e.target.files && onBgFile(e.target.files[0])} />
          <button className="btn-ghost" onClick={() => downloadAs("png")}>⬇ Tải PNG</button>
          <button className="btn-ghost" onClick={() => downloadAs("jpeg")}>⬇ Tải JPG</button>
          <button className="btn-ghost" onClick={exportPdf}>⬇ Tải PDF</button>
          <button className="btn-ghost" onClick={saveProject}>💾 Lưu project JSON</button>
          <button className="btn-ghost" onClick={() => projectInputRef.current?.click()}>📂 Mở project JSON</button>
          <input ref={projectInputRef} type="file" accept="application/json" className="hidden"
                 onChange={e => e.target.files && loadProject(e.target.files[0])} />
        </div>
      </div>

      <div className="mt-4 grid grid-cols-12 gap-4">
        {/* Left panel - defaults */}
        <div className="col-span-12 md:col-span-2 card space-y-3">
          <div className="font-semibold text-sm">Mặc định</div>
          <Row label="Màu viền"><input type="color" value={stroke} onChange={e => setStroke(e.target.value)} className="w-full h-8" /></Row>
          <Row label="Màu nền">
            <div className="flex items-center gap-1">
              <input type="color" value={fill === "transparent" ? "#ffffff" : fill}
                     onChange={e => setFill(e.target.value)} className="flex-1 h-8" />
              <label className="flex items-center gap-1 text-[11px]">
                <input type="checkbox" checked={fill === "transparent"}
                       onChange={e => setFill(e.target.checked ? "transparent" : "#ffffff")} />
                ⌀
              </label>
            </div>
          </Row>
          <Row label="Độ dày nét"><input type="number" min={1} max={20} value={width} onChange={e => setWidth(+e.target.value)} className="input" /></Row>
          <Row label="Cỡ chữ"><input type="number" min={8} max={120} value={fontSize} onChange={e => setFontSize(+e.target.value)} className="input" /></Row>
          <Row label="Màu chữ"><input type="color" value={textColor} onChange={e => setTextColor(e.target.value)} className="w-full h-8" /></Row>
          <div className="pt-2 border-t text-[11px] text-gray-500">
            Background bị khoá. Tooltip: dùng "Đổi background" để thay ảnh.
          </div>
        </div>

        {/* Canvas */}
        <div className="col-span-12 md:col-span-8 card overflow-auto">
          <div className="text-xs text-gray-500 mb-2">Zoom: {(zoom * 100).toFixed(0)}%</div>
          <div className="border border-gray-200 inline-block">
            <canvas ref={canvasRef} width={800} height={500} />
          </div>
          {!bg?.url && (
            <div className="mt-3 text-sm text-gray-500">
              Chưa có ảnh so sánh. Tạo ảnh tại <a className="text-brand-600" href="/compare">So sánh frames</a>{" "}
              rồi bấm <b>"Chỉnh sửa với editor"</b>, hoặc đổi background ở trên.
            </div>
          )}
        </div>

        {/* Right panel - selected object props */}
        <div className="col-span-12 md:col-span-2 card space-y-3">
          <div className="font-semibold text-sm">Đối tượng đang chọn</div>
          {!selProps && <div className="text-xs text-gray-500">Chưa chọn đối tượng nào.</div>}
          {selProps && (
            <>
              <Row label="Màu viền">
                <input type="color" value={selProps.stroke || "#000000"}
                       onChange={e => applyProp("stroke", e.target.value)} className="w-full h-8" />
              </Row>
              <Row label="Màu nền">
                <div className="flex items-center gap-1">
                  <input type="color" value={selProps.fill && selProps.fill !== "transparent" ? selProps.fill : "#ffffff"}
                         onChange={e => applyProp("fill", e.target.value)} className="flex-1 h-8" />
                  <label className="flex items-center gap-1 text-[11px]">
                    <input type="checkbox" checked={selProps.fill === "transparent" || !selProps.fill}
                           onChange={e => applyProp("fill", e.target.checked ? "transparent" : "#ffffff")} />
                    ⌀
                  </label>
                </div>
              </Row>
              <Row label="Độ dày nét">
                <input type="number" min={1} max={20} value={selProps.strokeWidth || 1}
                       onChange={e => applyProp("strokeWidth", +e.target.value)} className="input" />
              </Row>
              {selProps.fontSize != null && (
                <Row label="Cỡ chữ">
                  <input type="number" min={8} max={120} value={selProps.fontSize}
                         onChange={e => applyProp("fontSize", +e.target.value)} className="input" />
                </Row>
              )}
              <Row label="Độ mờ">
                <input type="range" min={0.1} max={1} step={0.1} value={selProps.opacity || 1}
                       onChange={e => applyProp("opacity", +e.target.value)} className="w-full" />
              </Row>
              <div className="flex gap-1">
                <button className="btn-ghost text-xs flex-1" onClick={bringForward}>↑ Lên trên</button>
                <button className="btn-ghost text-xs flex-1" onClick={sendBackward}>↓ Xuống dưới</button>
              </div>
            </>
          )}
        </div>
      </div>

      {/* Captions */}
      <div className="card mt-4 grid sm:grid-cols-2 gap-3">
        <div>
          <label className="label">Caption EN</label>
          <textarea className="input" rows={2} value={capEn} onChange={e => setCapEn(e.target.value)} />
        </div>
        <div>
          <label className="label">Caption VI</label>
          <textarea className="input" rows={2} value={capVi} onChange={e => setCapVi(e.target.value)} />
        </div>
      </div>
    </div>
  );
}

function TBtn({ children, onClick, active }: { children: any; onClick?: () => void; active?: boolean }) {
  return (
    <button onClick={onClick}
            className={`px-3 py-1.5 rounded-md text-xs border ${
              active ? "bg-brand-50 border-brand-300 text-brand-700" : "bg-white border-gray-200 hover:bg-gray-50"
            }`}>
      {children}
    </button>
  );
}
function Row({ label, children }: { label: string; children: any }) {
  return <div><label className="label">{label}</label>{children}</div>;
}
