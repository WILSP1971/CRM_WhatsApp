import { MessageCircle, Instagram, Facebook, Globe, type LucideIcon } from "lucide-react";
import type { Channel, Sentiment, MessageStatus } from "@/lib/types";

/**
 * Metadatos visuales por canal (SPEC-004). Iconos SVG locales (lucide-react,
 * dependencia de build, cero red en runtime) — nunca imágenes remotas.
 */
export interface ChannelMeta {
  label: string;
  icon: LucideIcon;
  /** Color de acento por canal, siempre resuelto vía token/clase Tailwind. */
  colorClass: string;
}

export const CHANNEL_META: Record<Channel, ChannelMeta> = {
  whatsapp: {
    label: "WhatsApp",
    icon: MessageCircle,
    colorClass: "text-state-success-strong",
  },
  instagram: {
    label: "Instagram",
    icon: Instagram,
    colorClass: "text-state-danger-strong",
  },
  messenger: {
    label: "Messenger",
    icon: Facebook,
    colorClass: "text-accent-indigo-strong",
  },
  webchat: {
    label: "Chat web",
    icon: Globe,
    colorClass: "text-accent-cyan-strong",
  },
};

export interface SentimentMeta {
  label: string;
  badgeVariant: "success" | "warning" | "danger";
}

/** Sentimiento representado como badge + etiqueta textual (no solo color, RNF a11y). */
export const SENTIMENT_META: Record<Sentiment, SentimentMeta> = {
  positivo: { label: "Positivo", badgeVariant: "success" },
  neutral: { label: "Neutral", badgeVariant: "warning" },
  negativo: { label: "Negativo", badgeVariant: "danger" },
};

export const MESSAGE_STATUS_LABEL: Record<MessageStatus, string> = {
  enviado: "Enviado",
  entregado: "Entregado",
  leido: "Leído",
  // Estado terminal de envío por WhatsApp (SPEC-029/SPEC-031); solo en datos
  // reales, nunca en la maqueta mock.
  failed: "Fallido",
};

/**
 * Indicador de ventana de servicio de 24 h de WhatsApp (SPEC-031, RF-02).
 * Texto siempre explícito (no solo color, RNF a11y — mismo patrón que
 * `SENTIMENT_META`).
 */
export const WHATSAPP_WINDOW_META = {
  dentro: {
    label: "Dentro de ventana 24 h",
    badgeVariant: "success" as const,
  },
  fuera: {
    label: "Fuera de ventana · requiere plantilla",
    badgeVariant: "warning" as const,
  },
};
