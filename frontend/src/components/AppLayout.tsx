import { NavLink, Outlet } from "react-router-dom";

const nav = [
  { to: "/", label: "Dashboard", icon: "🏠" },
  { to: "/metadata", label: "Metadata CSV", icon: "📄" },
  { to: "/extract", label: "Trích xuất MediaPipe", icon: "🎬" },
  { to: "/compare", label: "So sánh frames", icon: "🔬" },
  { to: "/history", label: "Lịch sử outputs", icon: "🗂️" },
];

export default function AppLayout() {
  return (
    <div className="min-h-full flex">
      <aside className="w-64 shrink-0 bg-white border-r border-gray-200 p-4 hidden md:block">
        <div className="mb-6">
          <div className="text-base font-bold text-brand-700">KLTN VSL</div>
          <div className="text-xs text-gray-500 mt-1">Visualization Tool (local)</div>
        </div>
        <nav className="space-y-1">
          {nav.map(n => (
            <NavLink key={n.to} to={n.to} end
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2 rounded-md text-sm ${isActive ? "bg-brand-50 text-brand-700 font-semibold" : "text-gray-700 hover:bg-gray-100"}`
              }>
              <span>{n.icon}</span>{n.label}
            </NavLink>
          ))}
        </nav>
        <div className="mt-8 text-[11px] text-gray-400 leading-relaxed">
          Backend: <span className="font-mono">127.0.0.1:8000</span><br/>
          Mọi xử lý đều chạy local trên máy bạn.
        </div>
      </aside>
      <main className="flex-1 min-w-0 p-6 md:p-8 max-w-[1500px] mx-auto">
        <Outlet />
      </main>
    </div>
  );
}
