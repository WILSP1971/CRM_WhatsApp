import { useState } from "react";
import { ChevronDown, Building2 } from "lucide-react";
import tenantsData from "@/mocks/tenants.json";
import type { Tenant } from "@/lib/types";
import { cn } from "@/lib/cn";

const tenants = tenantsData as Tenant[];

interface TenantSwitcherProps {
  activeTenantId: string;
  onChange: (tenantId: string) => void;
}

/** Selector de inquilino/empresa (SPEC-003 RF-09): cambia branding/nombre visible. */
export function TenantSwitcher({ activeTenantId, onChange }: TenantSwitcherProps) {
  const [open, setOpen] = useState(false);
  const activeTenant = tenants.find((t) => t.id === activeTenantId) ?? tenants[0];

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        aria-expanded={open}
        aria-haspopup="listbox"
        aria-label="Seleccionar inquilino o empresa"
        className="flex items-center gap-2 rounded-md border border-border-default bg-bg-surface-raised px-3 py-1.5 text-sm text-text-primary transition-colors duration-fast ease-standard hover:border-accent-indigo focus-visible:shadow-focus focus-visible:outline-none"
      >
        <Building2 className="h-4 w-4 text-text-muted" aria-hidden />
        <span className="max-w-[160px] truncate font-medium">{activeTenant.name}</span>
        <ChevronDown className="h-4 w-4 text-text-muted" aria-hidden />
      </button>

      {open && (
        <ul
          role="listbox"
          aria-label="Inquilinos disponibles"
          className="glass-surface absolute left-0 top-full z-overlay mt-2 w-64 rounded-lg p-1 shadow-lg"
        >
          {tenants.map((tenant) => (
            <li key={tenant.id}>
              <button
                type="button"
                role="option"
                aria-selected={tenant.id === activeTenantId}
                onClick={() => {
                  onChange(tenant.id);
                  setOpen(false);
                }}
                className={cn(
                  "flex w-full flex-col items-start gap-0.5 rounded-md px-3 py-2 text-left text-sm",
                  "text-text-secondary hover:bg-bg-surface-raised hover:text-text-primary",
                  "focus-visible:shadow-focus focus-visible:outline-none",
                  tenant.id === activeTenantId &&
                    "bg-accent-indigo/15 text-accent-indigo-strong",
                )}
              >
                <span className="font-medium">{tenant.name}</span>
                <span className="text-xs text-text-muted">{tenant.planLabel}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
