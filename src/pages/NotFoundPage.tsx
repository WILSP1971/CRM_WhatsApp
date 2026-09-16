import { Link } from "react-router-dom";
import { Button } from "@/components/ui";

export function NotFoundPage() {
  return (
    <div className="mx-auto flex max-w-md flex-col items-center gap-4 text-center">
      <h1 className="text-2xl font-semibold text-text-primary">Página no encontrada</h1>
      <p className="text-text-secondary">
        La ruta solicitada no existe en la maqueta de OmniCore AI.
      </p>
      <Button asChild>
        <Link to="/bandeja">Volver a la bandeja unificada</Link>
      </Button>
    </div>
  );
}
