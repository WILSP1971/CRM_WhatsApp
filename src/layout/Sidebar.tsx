import { NavLink } from "react-router-dom";
import { ChevronsLeft, ChevronsRight } from "lucide-react";
import { NAV_ITEMS } from "@/lib/navigation";
import { cn } from "@/lib/cn";
import { Tooltip } from "@/components/ui";

interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
}

export function Sidebar({ collapsed, onToggle }: SidebarProps) {
  return (
    <aside
      aria-label="Navegación principal"
      className={cn(
        "z-sidebar flex h-screen flex-col border-r border-border-subtle bg-bg-surface",
        "transition-[width] duration-base ease-standard",
        collapsed ? "w-[72px]" : "w-64",
      )}
    >
      <div className="flex h-16 items-center gap-2 border-b border-border-subtle px-4">
        <div
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-accent-indigo text-sm font-bold text-text-inverse"
          aria-hidden="true"
        >
          OC
        </div>
        {!collapsed && (
          <span className="truncate text-sm font-semibold text-text-primary">
            OmniCore AI
          </span>
        )}
      </div>

      <nav className="flex-1 overflow-y-auto py-3" aria-label="Módulos">
        <ul className="flex flex-col gap-1 px-2">
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            const linkContent = (
              <NavLink
                to={item.path}
                className={({ isActive }) =>
                  cn(
                    "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium",
                    "text-text-secondary transition-colors duration-fast ease-standard",
                    "hover:bg-bg-surface-raised hover:text-text-primary",
                    "focus-visible:shadow-focus focus-visible:outline-none",
                    isActive &&
                      "bg-accent-indigo/15 hover:bg-accent-indigo/20 text-accent-indigo-strong",
                  )
                }
                aria-current={undefined}
              >
                <Icon className="h-5 w-5 shrink-0" aria-hidden />
                {!collapsed && <span className="truncate">{item.label}</span>}
              </NavLink>
            );

            return (
              <li key={item.id}>
                {collapsed ? (
                  <Tooltip label={item.label}>{linkContent}</Tooltip>
                ) : (
                  linkContent
                )}
              </li>
            );
          })}
        </ul>
      </nav>

      <div className="border-t border-border-subtle p-2">
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={!collapsed}
          aria-label={collapsed ? "Expandir barra lateral" : "Plegar barra lateral"}
          className={cn(
            "flex w-full items-center justify-center gap-2 rounded-md px-3 py-2 text-sm",
            "text-text-secondary hover:bg-bg-surface-raised hover:text-text-primary",
            "transition-colors duration-fast ease-standard",
            "focus-visible:shadow-focus focus-visible:outline-none",
          )}
        >
          {collapsed ? (
            <ChevronsRight className="h-5 w-5" aria-hidden />
          ) : (
            <>
              <ChevronsLeft className="h-5 w-5" aria-hidden />
              <span>Plegar</span>
            </>
          )}
        </button>
      </div>
    </aside>
  );
}
