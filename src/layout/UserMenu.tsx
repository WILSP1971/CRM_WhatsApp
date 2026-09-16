import { useState } from "react";
import { ChevronDown, LogOut, Settings, Moon, Sun } from "lucide-react";
import { useTheme } from "@/lib/theme";
import { cn } from "@/lib/cn";

/** Menú de perfil de usuario (mock) + toggle de tema. */
export function UserMenu() {
  const [open, setOpen] = useState(false);
  const { theme, toggleTheme } = useTheme();

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        aria-expanded={open}
        aria-haspopup="true"
        aria-label="Menú de perfil"
        className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm text-text-primary transition-colors duration-fast ease-standard hover:bg-bg-surface-raised focus-visible:shadow-focus focus-visible:outline-none"
      >
        <span
          className="bg-accent-cyan/20 flex h-8 w-8 items-center justify-center rounded-full text-xs font-semibold text-accent-cyan-strong"
          aria-hidden
        >
          AC
        </span>
        <span className="hidden text-left sm:block">
          <span className="block leading-tight">Agente Comercial</span>
          <span className="block text-xs text-text-muted">Supervisor</span>
        </span>
        <ChevronDown className="h-4 w-4 text-text-muted" aria-hidden />
      </button>

      {open && (
        <ul
          role="menu"
          aria-label="Opciones de perfil"
          className="glass-surface absolute right-0 top-full z-overlay mt-2 w-56 rounded-lg p-1 shadow-lg"
        >
          <li role="none">
            <button
              role="menuitem"
              type="button"
              onClick={toggleTheme}
              className={cn(
                "flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm text-text-secondary",
                "hover:bg-bg-surface-raised hover:text-text-primary",
                "focus-visible:shadow-focus focus-visible:outline-none",
              )}
            >
              {theme === "dark" ? (
                <Sun className="h-4 w-4" aria-hidden />
              ) : (
                <Moon className="h-4 w-4" aria-hidden />
              )}
              Cambiar a tema {theme === "dark" ? "claro" : "oscuro"}
            </button>
          </li>
          <li role="none">
            <button
              role="menuitem"
              type="button"
              className={cn(
                "flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm text-text-secondary",
                "hover:bg-bg-surface-raised hover:text-text-primary",
                "focus-visible:shadow-focus focus-visible:outline-none",
              )}
            >
              <Settings className="h-4 w-4" aria-hidden />
              Configuración
            </button>
          </li>
          <li role="none">
            <button
              role="menuitem"
              type="button"
              className={cn(
                "flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm text-state-danger",
                "hover:bg-state-danger/10",
                "focus-visible:shadow-focus focus-visible:outline-none",
              )}
            >
              <LogOut className="h-4 w-4" aria-hidden />
              Cerrar sesión
            </button>
          </li>
        </ul>
      )}
    </div>
  );
}
