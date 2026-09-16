import { useState } from "react";
import { GlobalSearch } from "@/layout/GlobalSearch";
import { VoiceBotStatusWidget } from "@/layout/VoiceBotStatusWidget";
import { TenantSwitcher } from "@/layout/TenantSwitcher";
import { NotificationsCenter } from "@/layout/NotificationsCenter";
import { UserMenu } from "@/layout/UserMenu";

export function Header() {
  const [activeTenantId, setActiveTenantId] = useState("tenant-comercial");

  return (
    <header
      role="banner"
      className="bg-bg-surface/95 sticky top-0 z-header flex h-16 items-center gap-4 border-b border-border-subtle px-4 backdrop-blur-glass"
    >
      <TenantSwitcher activeTenantId={activeTenantId} onChange={setActiveTenantId} />

      <div className="flex-1">
        <GlobalSearch />
      </div>

      <div className="flex items-center gap-2">
        <VoiceBotStatusWidget />
        <NotificationsCenter />
        <UserMenu />
      </div>
    </header>
  );
}
