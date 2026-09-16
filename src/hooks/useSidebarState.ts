import { useCallback, useEffect, useState } from "react";

const STORAGE_KEY = "omnicore-sidebar-collapsed";

/**
 * Estado plegado/desplegado del sidebar, persistente durante la sesión
 * (SPEC-003 RF-02) vía sessionStorage (no requiere sobrevivir cierre del
 * navegador, solo la sesión de navegación actual).
 */
export function useSidebarState() {
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    return window.sessionStorage.getItem(STORAGE_KEY) === "true";
  });

  useEffect(() => {
    try {
      window.sessionStorage.setItem(STORAGE_KEY, String(collapsed));
    } catch {
      // sessionStorage puede no estar disponible; degradación silenciosa.
    }
  }, [collapsed]);

  const toggle = useCallback(() => setCollapsed((prev) => !prev), []);

  return { collapsed, toggle };
}
