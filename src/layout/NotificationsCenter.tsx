import { useState } from "react";
import { Bell } from "lucide-react";
import notificationsData from "@/mocks/notifications.json";
import type { AppNotification } from "@/lib/types";
import { Badge } from "@/components/ui";
import { cn } from "@/lib/cn";

const notifications = notificationsData as AppNotification[];

const severityToVariant: Record<
  AppNotification["severity"],
  "success" | "warning" | "danger" | "ai"
> = {
  info: "ai",
  warning: "warning",
  success: "success",
  danger: "danger",
};

export function NotificationsCenter() {
  const [open, setOpen] = useState(false);
  const unreadCount = notifications.filter((n) => !n.read).length;

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        aria-expanded={open}
        aria-haspopup="true"
        aria-label={`Notificaciones${unreadCount > 0 ? `, ${unreadCount} sin leer` : ""}`}
        className="relative flex h-10 w-10 items-center justify-center rounded-md text-text-secondary transition-colors duration-fast ease-standard hover:bg-bg-surface-raised hover:text-text-primary focus-visible:shadow-focus focus-visible:outline-none"
      >
        <Bell className="h-5 w-5" aria-hidden />
        {unreadCount > 0 && (
          <span
            className="absolute right-1.5 top-1.5 flex h-2 w-2 rounded-full bg-state-danger"
            aria-hidden
          />
        )}
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="Centro de notificaciones"
          className="glass-surface absolute right-0 top-full z-overlay mt-2 w-80 rounded-lg p-3 shadow-lg"
        >
          <p className="mb-2 text-sm font-semibold text-text-primary">Notificaciones</p>
          <ul className="flex flex-col gap-2">
            {notifications.map((n) => (
              <li
                key={n.id}
                className={cn(
                  "rounded-md border border-border-subtle p-2",
                  !n.read && "bg-bg-surface-raised",
                )}
              >
                <div className="mb-1 flex items-center justify-between gap-2">
                  <span className="text-sm font-medium text-text-primary">{n.title}</span>
                  <Badge variant={severityToVariant[n.severity]}>{n.severity}</Badge>
                </div>
                <p className="text-xs text-text-secondary">{n.description}</p>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
