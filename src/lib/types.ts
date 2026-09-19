/**
 * Tipos compartidos para las fixtures mock de OmniCore AI.
 * Todos los datos son ficticios (ver src/mocks/*.json).
 */

export type Channel = "whatsapp" | "instagram" | "messenger" | "webchat";

export type Sentiment = "positivo" | "neutral" | "negativo";

export type ConversationStatus = "abierta" | "pendiente" | "escalada" | "cerrada";

export type Sector = "comercial" | "servicios" | "manufactura";

export interface Contact {
  id: string;
  name: string;
  company: string;
  email: string;
  phone: string;
  avatarInitials: string;
  tags: string[];
  sector: Sector;
  lifetimeValue: number;
  lastInteraction: string;
  notes?: string;
}

export type MessageDirection = "entrante" | "saliente";
/**
 * Estados de entrega del mensaje. `failed` (SPEC-029/SPEC-031) es un estado
 * TERMINAL propio del transporte de envío por WhatsApp (Graph API): 429/5xx
 * agotados o ventana de 24h bloqueada sin plantilla HSM. Solo puede
 * observarse en datos reales (flag ON); la maqueta mock no lo usa.
 */
export type MessageStatus = "enviado" | "entregado" | "leido" | "failed";

export interface ConversationMessage {
  id: string;
  direction: MessageDirection;
  text: string;
  sentAt: string;
  status: MessageStatus;
}

/**
 * Ventana de servicio de 24 h de WhatsApp (SPEC-029 RF-03, indicador SPA
 * SPEC-031): se mide desde el último mensaje ENTRANTE (del contacto).
 * Dentro de ventana -> texto libre; fuera -> se exige plantilla HSM.
 * Solo aplica a `channel === "whatsapp"`; `undefined` en cualquier otro
 * canal o en modo mock (Entregable #1 intacto, RF-05/RNF-07 SPEC-020).
 */
export interface WhatsappServiceWindow {
  /** `true` si hay un mensaje entrante dentro de las últimas 24 h. */
  withinWindow: boolean;
  /** ISO de creación del último mensaje entrante; `null` si no existe. */
  lastInboundAt: string | null;
}

export interface Conversation {
  id: string;
  contactId: string;
  channel: Channel;
  sentiment: Sentiment;
  lastMessage: string;
  lastMessageAt: string;
  unreadCount: number;
  status: ConversationStatus;
  messages: ConversationMessage[];
  /** Solo poblado para `channel === "whatsapp"` en modo real (SPEC-031). */
  whatsappWindow?: WhatsappServiceWindow;
}

/* ---------- RAG (SPEC-005) — representación, sin IA/LLM real ---------- */

export interface RagCitation {
  id: string;
  conversationId: string;
  source: string;
  excerpt: string;
  similarityScore: number;
}

export interface RagDraft {
  id: string;
  conversationId: string;
  text: string;
  generatedAt: string;
}

export interface RagSuggestion {
  id: string;
  conversationId: string;
  name: string;
  description: string;
  price: number;
}

export interface RagData {
  citations: RagCitation[];
  drafts: RagDraft[];
  suggestions: RagSuggestion[];
  notaFicticia: string;
}

export type CallDirection = "entrante" | "saliente";
export type CallStatus = "finalizada" | "en_espera" | "en_llamada" | "perdida";

export interface CallRecord {
  id: string;
  contactId: string;
  direction: CallDirection;
  status: CallStatus;
  durationSeconds: number;
  startedAt: string;
  detectedIntent: string;
  recordingSimulated: boolean;
}

export interface KpiSummaryItem {
  id: string;
  label: string;
  value: number;
  delta: number;
  trend: "up" | "down" | "flat";
}

export interface KpiBySector {
  sector: Sector;
  ingresosEstimados: number;
  ticketsAbiertos: number;
}

export interface KpiData {
  generatedAt: string;
  resumen: KpiSummaryItem[];
  porSector: KpiBySector[];
  notaFicticia: string;
}

export interface Tenant {
  id: string;
  name: string;
  sector: Sector;
  initials: string;
  planLabel: string;
}

export type NotificationSeverity = "info" | "warning" | "success" | "danger";

export interface AppNotification {
  id: string;
  title: string;
  description: string;
  createdAt: string;
  read: boolean;
  severity: NotificationSeverity;
}

/* ---------- VoiceBot / telefonía VoIP (SPEC-006) — representación, sin VoIP real ---------- */

export type TranscriptSpeaker = "agente" | "cliente" | "voicebot";

export interface TranscriptLine {
  speaker: TranscriptSpeaker;
  text: string;
}

export interface VoiceBotIntent {
  id: string;
  label: string;
  confidence: number;
}

export interface VoiceBotData {
  notaFicticia: string;
  activeCallId: string;
  intents: VoiceBotIntent[];
  transcripts: Record<string, TranscriptLine[]>;
  callIntentMap: Record<string, string>;
}
