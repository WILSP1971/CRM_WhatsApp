import { Outlet } from "react-router-dom";
import { Sidebar } from "@/layout/Sidebar";
import { Header } from "@/layout/Header";
import { useSidebarState } from "@/hooks/useSidebarState";

export function AppLayout() {
  const { collapsed, toggle } = useSidebarState();

  return (
    <div className="flex h-screen w-full overflow-hidden bg-bg-canvas text-text-primary">
      <a href="#contenido-principal" className="skip-link">
        Saltar al contenido principal
      </a>

      <Sidebar collapsed={collapsed} onToggle={toggle} />

      <div className="flex min-w-0 flex-1 flex-col">
        <Header />
        <main
          id="contenido-principal"
          role="main"
          tabIndex={-1}
          className="flex-1 overflow-y-auto p-6 focus-visible:outline-none"
        >
          <Outlet />
        </main>
      </div>
    </div>
  );
}
