import { Users } from "lucide-react";
import { PlaceholderPage } from "@/pages/PlaceholderPage";

export function ContactsPage() {
  return (
    <PlaceholderPage
      icon={Users}
      title="Contactos 360°"
      description="Vista consolidada de cada cliente: historial, canales, valor y notas."
      specNote="Este módulo se implementará junto con SPEC-004 (panel de contacto 360° dentro de la bandeja unificada)."
    />
  );
}
