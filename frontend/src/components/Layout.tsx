import { NavLink, Outlet, useLocation } from "react-router-dom";
import {
  AlertOctagon,
  Aperture,
  BarChart3,
  Camera,
  Flame,
  Activity,
  BellRing,
  Building2,
  ListChecks,
  LogOut,
  Ruler,
  Search,
  ShieldAlert,
  ShieldCheck,
  SlidersHorizontal,
  UserCog,
  Users,
  Video,
} from "lucide-react";
import { useConnectionStatus } from "../hooks/useConnectionStatus";
import { useAuth } from "../hooks/useAuth";
import TiamLogo from "./TiamLogo";

const NAV_ITEMS = [
  { to: "/", label: "Live Monitor", icon: Video },
  { to: "/admin/cameras", label: "Cameras", icon: Camera },
  { to: "/admin/zone-types", label: "Zone Types", icon: ListChecks },
  { to: "/admin/zones", label: "Zone Studio", icon: ShieldAlert },
  { to: "/admin/calibration", label: "Calibration Tool", icon: Ruler },
  { to: "/admin/fisheye", label: "Fisheye Setup", icon: Aperture },
  { to: "/coaching", label: "Incidents", icon: BellRing },
  { to: "/incidents/search", label: "Incident Search", icon: Search },
  { to: "/analytics", label: "Analytics & Reports", icon: BarChart3 },
  { to: "/heatmap/usage", label: "Usage Heatmap", icon: Flame },
  { to: "/heatmap/violations", label: "Violations Heatmap", icon: AlertOctagon },
];

const ADMIN_ITEMS = [
  { to: "/admin/users", label: "User Management", icon: Users },
  { to: "/admin/roles", label: "Role Management", icon: ShieldCheck },
  { to: "/admin/detection-settings", label: "Detection Settings", icon: SlidersHorizontal },
  { to: "/admin/site", label: "Site", icon: Building2 },
  { to: "/admin/system", label: "System", icon: Activity },
];

function StatusBadge({ label, connected }: { label: string; connected: boolean }) {
  return (
    <span className={connected ? "dm-pill-emerald" : "dm-pill-red"}>
      <span className={`h-1.5 w-1.5 rounded-full ${connected ? "bg-emerald-400" : "bg-red-400"}`} />
      {label}: {connected ? "Online" : "Offline"}
    </span>
  );
}

export default function Layout() {
  const { apiOnline, wsConnected } = useConnectionStatus();
  const { user, role, logout } = useAuth();
  const location = useLocation();
  const isAdmin = role?.is_system ?? false;

  const visibleNavItems = NAV_ITEMS.filter((item) => isAdmin || role?.pages.includes(item.to));
  const allItems = isAdmin ? [...visibleNavItems, ...ADMIN_ITEMS] : visibleNavItems;
  const current = allItems.find((item) =>
    item.to === "/" ? location.pathname === "/" : location.pathname.startsWith(item.to)
  );

  return (
    <div className="flex h-screen w-screen bg-apl-midnight text-slate-100">
      <aside className="flex w-60 flex-shrink-0 flex-col border-r border-line bg-panel">
        <div className="flex h-14 items-center gap-2.5 px-4 border-b border-line">
          <TiamLogo className="h-6 flex-shrink-0" />
          <div className="h-5 w-px bg-line" />
          <div className="font-display text-sm font-medium leading-tight text-slate-200">
            Security Monitor
          </div>
        </div>
        <nav className="flex-1 space-y-1 p-3">
          {visibleNavItems.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                  isActive
                    ? "bg-apl-sunset/15 text-apl-sunset ring-1 ring-inset ring-apl-sunset/30"
                    : "text-slate-400 hover:bg-panel-2 hover:text-slate-100"
                }`
              }
            >
              <Icon className="h-4 w-4" />
              {label}
            </NavLink>
          ))}

          {isAdmin && (
            <>
              <div className="px-3 pt-4 pb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                Admin
              </div>
              {ADMIN_ITEMS.map(({ to, label, icon: Icon }) => (
                <NavLink
                  key={to}
                  to={to}
                  className={({ isActive }) =>
                    `flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                      isActive
                        ? "bg-apl-sunset/15 text-apl-sunset ring-1 ring-inset ring-apl-sunset/30"
                        : "text-slate-400 hover:bg-panel-2 hover:text-slate-100"
                    }`
                  }
                >
                  <Icon className="h-4 w-4" />
                  {label}
                </NavLink>
              ))}
            </>
          )}
        </nav>

        <div className="border-t border-line p-3">
          <div className="flex items-center justify-between rounded-lg px-3 py-2 text-sm">
            <div className="flex items-center gap-2 text-slate-300">
              <UserCog className="h-4 w-4 text-slate-500" />
              <div className="leading-tight">
                <div className="font-medium">{user?.username}</div>
                <div className="text-xs text-slate-500">{role?.name}</div>
              </div>
            </div>
            <button
              onClick={logout}
              title="Sign out"
              className="text-slate-500 hover:text-apl-sunset"
            >
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <header className="flex h-14 flex-shrink-0 items-center justify-between border-b border-line bg-panel px-6">
          <div className="flex items-center gap-1.5 text-sm">
            <span className="text-slate-500">Security Monitor</span>
            <span className="text-muted">/</span>
            <span className="font-display text-base font-medium text-slate-100">
              {current?.label ?? "Dashboard"}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <StatusBadge label="API" connected={apiOnline} />
            <StatusBadge label="WS" connected={wsConnected} />
          </div>
        </header>

        <main className="flex-1 overflow-auto bg-apl-midnight p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
