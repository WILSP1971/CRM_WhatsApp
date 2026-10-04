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
  /**
   * `true` si el mensaje es una nota de voz de WhatsApp ya transcrita
   * (`Message.tipo === "audio"`, SPEC-053) — la SPA muestra un badge
   * discreto "transcrito de audio" (SPEC-059). Reproductor de audio
   * pospuesto (P3, fuera de alcance de SPEC-059). `undefined`/`false` en
   * modo mock (`VITE_USE_REAL_API=OFF`): la maqueta de #1–#4 no lo usa, sin
   * regresión (RNF-07).
   */
  isTranscribedAudio?: boolean;
  /**
   * URL EXTERNA del CDN de Meta (`lookaside.fbsbx.com`) de un adjunto de DM
   * de Instagram (SPEC-088/090), copiada TAL CUAL desde `MessageOut.media_url`
   * — el backend NUNCA descarga ese binario (política de Meta,
   * `chatwoot#8583`). El NAVEGADOR del agente hace el fetch directo a esa
   * URL para renderizarla/abrirla bajo demanda. La URL puede expirar o ser
   * revocada por Meta (el contacto borró el contenido): comportamiento
   * ACEPTADO, se maneja con un fallback de error de carga, sin mecanismo de
   * refresco (no existe). EXPLÍCITAMENTE DISTINTO de `isTranscribedAudio`
   * (nota de voz de WhatsApp, local/cifrada, ADR-009): aquí no hay storage
   * local ni cifrado, es una referencia externa de solo lectura.
   * `undefined`/`null` para mensajes sin adjunto y para los de
   * WhatsApp/webchat/mock.
   */
  mediaUrl?: string | null;
  /** Tipo del adjunto (`"image"` | `"video"` | `"audio"` | `"file"`, tal
   * como lo clasifica Meta en `attachments[].type`), copiado 1:1 desde
   * `MessageOut.media_type`. Determina si se renderiza `<img>` o un enlace
   * "Abrir adjunto". `undefined`/`null` junto con `mediaUrl` ausente. */
  mediaType?: string | null;
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

/**
 * Modo de respuesta del borrador (SPEC-069/070, ADR-014, Entregable #6):
 * opt-in explícito (Q2-A) — por defecto `"texto"` (comportamiento actual
 * idéntico); `"audio"` habilita la UX de "responder con audio" en
 * `RagDraftCard`. `undefined` en modo mock (flag OFF): la maqueta de
 * #1-#5 no lo usa, sin regresión (RNF-FLAG SPEC-070).
 */
export type RagRespuestaModo = "texto" | "audio";

/**
 * Estado de la ruta OPCIONAL "escuchar antes de enviar" (SPEC-069/070,
 * Q1-C): refleja 1:1 `BackendTtsEstado`. `undefined`/`null` = nunca
 * solicitado o modo mock.
 */
export type RagTtsEstado = "no_solicitado" | "generando" | "listo" | "error";

export interface RagDraft {
  id: string;
  conversationId: string;
  text: string;
  generatedAt: string;
  /** Aditivo (SPEC-070): ausente en modo mock -> se trata como `"texto"`. */
  respuestaModo?: RagRespuestaModo;
  /** Aditivo (SPEC-070): ausente/`null` en modo mock o si nunca se pidió escuchar. */
  ttsEstado?: RagTtsEstado | null;
  /** Aditivo (SPEC-070): booleano derivado ya resuelto por el backend. */
  audioListo?: boolean;
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

/* ---------- Ficha de llamada real (SPEC-040) — datos reales tras VITE_USE_REAL_API ----------
 *
 * Contratos NUEVOS, exclusivos del modo real (`USE_REAL_API === true`,
 * `GET /calls`/`GET /calls/{id}`, `backend/app/api/calls.py`): NO reemplazan
 * `CallRecord`/`VoiceBotData` (que siguen siendo el contrato de la maqueta
 * mock, SPEC-006, intacto con el flag OFF). El componente de ficha de
 * llamada del módulo VoiceBot alterna entre ambos igual que `InboxPage`
 * alterna `Conversation` mock/real (SPEC-020).
 */

/** Un segmento de la transcripción real (inicio/fin en segundos, SPEC-038). */
export interface RealTranscriptSegment {
  inicio: number;
  fin: number;
  texto: string;
  hablante: string;
}

export interface RealCallTranscript {
  id: string;
  callId: string;
  segmentos: RealTranscriptSegment[];
  idioma: string;
  modeloStt: string;
  wer: number | null;
}

/** Borrador RAG citado de la llamada (SPEC-019/039); reutiliza `RagCitation`
 * (misma forma que el panel RAG de la Bandeja) con `≥3` citas trazables. */
export interface RealCallRagDraft {
  id: string;
  conversationId: string;
  content: string;
  contentOriginal: string;
  model: string;
  citations: RagCitation[];
  estado: string;
  editedBy: string | null;
  approvedBy: string | null;
  sentMessageId: string | null;
}

export interface RealCallRecord {
  id: string;
  contactId: string | null;
  conversationId: string | null;
  callId: string;
  numero: string;
  direccion: CallDirection;
  duracionSeconds: number | null;
  estado: string;
  resumen: string | null;
  /** `true` si hay audio para reproducir (sujeto a retención, SPEC-041, aún
   * no implementada); `false` si nunca hubo audio o ya fue purgado. */
  audioDisponible: boolean;
  createdAt: string;
}

export interface RealCallDetail {
  call: RealCallRecord;
  transcript: RealCallTranscript | null;
  sentiment: Sentiment | null;
  sentimentScore: number | null;
  ragDraft: RealCallRagDraft | null;
}
