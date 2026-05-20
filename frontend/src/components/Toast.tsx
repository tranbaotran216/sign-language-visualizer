import { createContext, useCallback, useContext, useState, ReactNode } from "react";

type Toast = { id: number; kind: "ok" | "err" | "info"; msg: string };
type Ctx = { push: (kind: Toast["kind"], msg: string) => void };

const ToastCtx = createContext<Ctx>({ push: () => {} });
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((kind: Toast["kind"], msg: string) => {
    const id = Date.now() + Math.random();
    setItems(xs => [...xs, { id, kind, msg }]);
    setTimeout(() => setItems(xs => xs.filter(x => x.id !== id)), 4000);
  }, []);
  return (
    <ToastCtx.Provider value={{ push }}>
      {children}
      <div className="fixed bottom-4 right-4 z-[100] space-y-2">
        {items.map(t => (
          <div key={t.id} className={`px-4 py-2 rounded-md shadow-md text-sm text-white ${
            t.kind === "ok" ? "bg-green-600" : t.kind === "err" ? "bg-red-600" : "bg-gray-800"
          }`}>{t.msg}</div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
