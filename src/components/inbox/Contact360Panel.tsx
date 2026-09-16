import { Building2, Mail, Phone, Wallet } from "lucide-react";
import { Badge, Card, CardContent, CardHeader, CardTitle } from "@/components/ui";
import { formatCurrency, formatDateTime } from "@/lib/format";
import type { Contact } from "@/lib/types";

interface Contact360PanelProps {
  contact: Contact | undefined;
}

/** Panel de contacto 360° (SPEC-004): datos ficticios de historial y valor. */
export function Contact360Panel({ contact }: Contact360PanelProps) {
  if (!contact) {
    return (
      <Card className="h-full" aria-label="Panel de contacto 360°">
        <CardContent>Selecciona una conversación para ver el contacto.</CardContent>
      </Card>
    );
  }

  return (
    <Card
      className="flex h-full flex-col gap-4 overflow-y-auto"
      aria-label="Panel de contacto 360°"
    >
      <CardHeader>
        <div className="flex items-center gap-3">
          <span
            className="bg-accent-indigo/15 flex h-11 w-11 flex-none items-center justify-center rounded-full text-base font-semibold text-accent-indigo-strong"
            aria-hidden
          >
            {contact.avatarInitials}
          </span>
          <div className="min-w-0">
            <CardTitle className="truncate">{contact.name}</CardTitle>
            <p className="truncate text-xs text-text-muted">{contact.company}</p>
          </div>
        </div>
      </CardHeader>

      <CardContent className="flex flex-col gap-4">
        <dl className="flex flex-col gap-2 text-sm">
          <div className="flex items-center gap-2">
            <Mail className="h-4 w-4 flex-none text-text-muted" aria-hidden />
            <dt className="sr-only">Correo</dt>
            <dd className="truncate text-text-secondary">{contact.email}</dd>
          </div>
          <div className="flex items-center gap-2">
            <Phone className="h-4 w-4 flex-none text-text-muted" aria-hidden />
            <dt className="sr-only">Teléfono</dt>
            <dd className="text-text-secondary">{contact.phone}</dd>
          </div>
          <div className="flex items-center gap-2">
            <Building2 className="h-4 w-4 flex-none text-text-muted" aria-hidden />
            <dt className="sr-only">Sector</dt>
            <dd className="capitalize text-text-secondary">{contact.sector}</dd>
          </div>
          <div className="flex items-center gap-2">
            <Wallet className="h-4 w-4 flex-none text-text-muted" aria-hidden />
            <dt className="sr-only">Valor de vida del cliente</dt>
            <dd className="text-text-secondary">
              {formatCurrency(contact.lifetimeValue)} LTV estimado
            </dd>
          </div>
        </dl>

        <div>
          <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-text-muted">
            Etiquetas
          </h4>
          <ul className="flex flex-wrap gap-1.5" aria-label="Etiquetas del contacto">
            {contact.tags.map((tag) => (
              <li key={tag}>
                <Badge variant="neutral">{tag}</Badge>
              </li>
            ))}
          </ul>
        </div>

        <div>
          <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-text-muted">
            Última interacción
          </h4>
          <p className="text-sm text-text-secondary">
            {formatDateTime(contact.lastInteraction)}
          </p>
        </div>

        {contact.notes && (
          <div>
            <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-text-muted">
              Notas
            </h4>
            <p className="text-sm text-text-secondary">{contact.notes}</p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
