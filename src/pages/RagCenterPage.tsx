import { BrainCircuit } from "lucide-react";
import { PlaceholderPage } from "@/pages/PlaceholderPage";

export function RagCenterPage() {
  return (
    <PlaceholderPage
      icon={BrainCircuit}
      title="Centro RAG"
      description="Panel de conocimiento empresarial: citas, borradores sugeridos y fuentes."
      specNote="Este módulo se implementará en SPEC-005 (Panel lateral RAG en vivo)."
    />
  );
}
