import {
  Inbox,
  Users,
  PhoneCall,
  BrainCircuit,
  RefreshCw,
  Workflow,
  BarChart3,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  id: string;
  label: string;
  path: string;
  icon: LucideIcon;
}

/** Los 6+ espacios del sidebar, en el orden pedido por SPEC-003. */
export const NAV_ITEMS: NavItem[] = [
  { id: "bandeja", label: "Bandeja unificada", path: "/bandeja", icon: Inbox },
  { id: "contactos", label: "Contactos 360°", path: "/contactos", icon: Users },
  {
    id: "llamadas",
    label: "Centro de llamadas VoiceBot",
    path: "/llamadas",
    icon: PhoneCall,
  },
  { id: "rag", label: "Centro RAG", path: "/rag", icon: BrainCircuit },
  { id: "erp", label: "Sync ERP", path: "/erp", icon: RefreshCw },
  { id: "flujos", label: "Flujos automatizados", path: "/flujos", icon: Workflow },
  {
    id: "analitica",
    label: "Analítica multisectorial",
    path: "/analitica",
    icon: BarChart3,
  },
];
