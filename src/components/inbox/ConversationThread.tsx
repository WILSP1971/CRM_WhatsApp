import { useEffect, useRef, useState } from "react";
import { AlertTriangle, Check, CheckCheck, Paperclip, Send } from "lucide-react";
import { Badge, Button } from "@/components/ui";
import { cn } from "@/lib/cn";
import { formatTime } from "@/lib/format";
import {
  CHANNEL_META,
  MESSAGE_STATUS_LABEL,
  SENTIMENT_META,
  WHATSAPP_WINDOW_META,
} from "@/lib/channels";
import type { Contact, Conversation, ConversationMessage, MessageStatus } from "@/lib/types";

interface ConversationThreadProps {
  conversation: Conversation;
  contact: Contact | undefined;
  draftText: string;
  onDraftChange: (value: string) => void;
}

/**
 * Adjunto de un DM de Instagram (SPEC-088/090): `message.mediaUrl` es la URL
 * FIRMADA del CDN de Meta (`lookaside.fbsbx.com`), transportada tal cual por
 * el backend — el NAVEGADOR del agente es quien hace el fetch real al
 * renderizar/abrir esta URL, el backend nunca descarga el binario (RF-06
 * SPEC-088). Headless/mínimo (Q5=A SPEC-090): sin reproductor dedicado.
 *
 * - `mediaType === "image"` -> `<img>` directo a la URL del CDN, con
 *   fallback "Adjunto no disponible" vía `onError` (la URL puede
 *   expirar/revocarse si el contacto borra el contenido — comportamiento
 *   ACEPTADO, SPEC-088 RF-07, sin mecanismo de refresco).
 * - cualquier otro tipo (`video`/`audio`/`file`) -> enlace "Abrir adjunto"
 *   que el navegador abre en una pestaña nueva.
 */
function MessageAttachment({ message }: { message: ConversationMessage }) {
  const [imageError, setImageError] = useState(false);

  if (!message.mediaUrl) {
    return null;
  }

  if (message.mediaType === "image" && !imageError) {
    return (
      <img
        src={message.mediaUrl}
        alt="Adjunto de Instagram"
        className="mb-1.5 max-h-64 max-w-full rounded-lg border border-border-subtle object-cover"
        onError={() => setImageError(true)}
      />
    );
  }

  if (message.mediaType === "image" && imageError) {
    return (
      <p className="mb-1.5 flex items-center gap-1.5 rounded-lg border border-border-subtle bg-bg-surface-raised px-3 py-2 text-xs text-text-muted">
        <Paperclip className="h-3.5 w-3.5" aria-hidden />
        Adjunto no disponible
      </p>
    );
  }

  return (
    <a
      href={message.mediaUrl}
      target="_blank"
      rel="noopener noreferrer"
      className={cn(
        "mb-1.5 flex items-center gap-1.5 rounded-lg border border-border-subtle bg-bg-surface-raised px-3 py-2 text-xs font-medium text-accent-indigo-strong",
        "hover:underline focus-visible:shadow-focus focus-visible:outline-none",
      )}
    >
      <Paperclip className="h-3.5 w-3.5" aria-hidden />
      Abrir adjunto
    </a>
  );
}

function MessageStatusIcon({ status }: { status: MessageStatus }) {
  if (status === "failed") {
    return (
      <AlertTriangle className="h-3.5 w-3.5 text-state-danger-strong" aria-hidden />
    );
  }
  if (status === "enviado") {
    return <Check className="h-3.5 w-3.5" aria-hidden />;
  }
  return (
    <CheckCheck
      className={cn("h-3.5 w-3.5", status === "leido" && "text-accent-cyan-strong")}
      aria-hidden
    />
  );
}

/** Hilo de conversación unificado (SPEC-004): burbujas, canal, estado y composer visual. */
export function ConversationThread({
  conversation,
  contact,
  draftText,
  onDraftChange,
}: ConversationThreadProps) {
  const channelMeta = CHANNEL_META[conversation.channel];
  const sentimentMeta = SENTIMENT_META[conversation.sentiment];
  const ChannelIcon = channelMeta.icon;
  // Indicador de ventana 24h/plantilla (SPEC-031, RF-02): solo WhatsApp real.
  const whatsappWindowMeta =
    conversation.channel === "whatsapp" && conversation.whatsappWindow
      ? conversation.whatsappWindow.withinWindow
        ? WHATSAPP_WINDOW_META.dentro
        : WHATSAPP_WINDOW_META.fuera
      : null;
  const scrollRef = useRef<HTMLDivElement>(null);
  const [localDraft, setLocalDraft] = useState(draftText);

  useEffect(() => {
    setLocalDraft(draftText);
  }, [draftText]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [conversation.id]);

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center justify-between gap-3 border-b border-border-subtle px-4 py-3">
        <div className="flex min-w-0 items-center gap-3">
          <span
            className="bg-accent-indigo/15 flex h-9 w-9 flex-none items-center justify-center rounded-full text-sm font-semibold text-accent-indigo-strong"
            aria-hidden
          >
            {contact?.avatarInitials ?? "??"}
          </span>
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-text-primary">
              {contact?.name ?? "Contacto desconocido"}
            </p>
            <p className="flex items-center gap-1 text-xs text-text-muted">
              <ChannelIcon
                className={cn("h-3.5 w-3.5", channelMeta.colorClass)}
                aria-hidden
              />
              <span>{channelMeta.label}</span>
            </p>
          </div>
        </div>
        <div className="flex flex-none items-center gap-2">
          {whatsappWindowMeta && (
            <Badge
              variant={whatsappWindowMeta.badgeVariant}
              aria-label={`Ventana de servicio de WhatsApp: ${whatsappWindowMeta.label}`}
            >
              {whatsappWindowMeta.label}
            </Badge>
          )}
          <Badge
            variant={sentimentMeta.badgeVariant}
            aria-label={`Sentimiento del hilo: ${sentimentMeta.label}`}
          >
            Sentimiento: {sentimentMeta.label}
          </Badge>
        </div>
      </header>

      <div
        ref={scrollRef}
        role="log"
        aria-label={`Mensajes de la conversación con ${contact?.name ?? "contacto"}`}
        className="flex flex-1 flex-col gap-3 overflow-y-auto px-4 py-4"
      >
        {conversation.messages.map((message) => {
          const isOutgoing = message.direction === "saliente";
          return (
            <div
              key={message.id}
              className={cn("flex flex-col", isOutgoing ? "items-end" : "items-start")}
            >
              {message.isTranscribedAudio && (
                // Sin `aria-label`: el texto visible ya es el nombre
                // accesible (WCAG 2.5.3 Label in Name) — un `aria-label`
                // distinto del texto visible genera discrepancia entre lo
                // que ve un usuario vidente y lo que oye un lector de
                // pantalla (hallazgo DAREDEVIL, SPEC-059).
                <Badge variant="neutral" className="mb-1">
                  Transcrito de audio
                </Badge>
              )}
              <MessageAttachment message={message} />
              {message.text.length > 0 && (
                <div
                  className={cn(
                    "max-w-[75%] rounded-xl px-3.5 py-2.5 text-sm shadow-sm",
                    isOutgoing
                      ? "bg-accent-indigo text-text-inverse"
                      : "border border-border-subtle bg-bg-surface-raised text-text-primary",
                  )}
                >
                  {message.text}
                </div>
              )}
              <div className="mt-1 flex items-center gap-1 px-1 text-xs text-text-muted">
                <span>{formatTime(message.sentAt)}</span>
                {isOutgoing && (
                  <>
                    <span aria-hidden>·</span>
                    <span className="flex items-center gap-0.5">
                      <MessageStatusIcon status={message.status} />
                      <span>{MESSAGE_STATUS_LABEL[message.status]}</span>
                    </span>
                  </>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <form
        className="flex items-center gap-2 border-t border-border-subtle px-4 py-3"
        onSubmit={(event) => event.preventDefault()}
        aria-label="Responder conversación (maqueta, sin envío real)"
      >
        <label htmlFor="composer-input" className="sr-only">
          Escribir respuesta
        </label>
        <input
          id="composer-input"
          type="text"
          value={localDraft}
          onChange={(event) => {
            setLocalDraft(event.target.value);
            onDraftChange(event.target.value);
          }}
          placeholder="Escribe una respuesta… (maqueta, no envía mensajes reales)"
          className={cn(
            "h-10 w-full rounded-md border border-border-default bg-bg-surface-raised px-3 text-sm text-text-primary",
            "placeholder:text-text-muted",
            "focus-visible:border-accent-cyan focus-visible:shadow-focus focus-visible:outline-none",
          )}
        />
        <Button
          type="submit"
          size="icon"
          aria-label="Enviar respuesta (deshabilitado en la maqueta)"
          disabled
        >
          <Send className="h-4 w-4" aria-hidden />
        </Button>
      </form>
    </div>
  );
}
