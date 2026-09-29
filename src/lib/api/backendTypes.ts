/**
 * Tipos del contrato REAL del backend (OpenAPI de SPEC-014/015/017/018/019),
 * usados SOLO por la capa de integración (`src/lib/api/*`) cuando el
 * feature-flag `VITE_USE_REAL_API` está activo (SPEC-020).
 *
 * Se mantienen separados de `src/lib/types.ts` (contrato de la maqueta,
 * Entregable #1) a propósito: los adaptadores de `src/lib/api/adapters.ts`
 * traducen explícitamente de un lado a otro donde difieren (documentado
 * ahí), en vez de forzar un único tipo para ambos mundos.
 */

export interface BackendPage<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface BackendContact {
  id: string;
  tenant_id: string;
  nombre: string;
  telefono: string | null;
  email: string | null;
  activo: boolean;
  created_at: string;
  updated_at: string;
}

export interface BackendConversation {
  id: string;
  tenant_id: string;
  contact_id: string;
  canal: string;
  estado: string;
  activo: boolean;
  created_at: string;
  updated_at: string;
}

export type BackendRemitente = "contacto" | "agente" | "ia";

export interface BackendMessage {
  id: string;
  tenant_id: string;
  conversation_id: string;
  remitente: BackendRemitente;
  // Nullable (SPEC-053/059): un `Message(tipo="audio")` puede llegar sin
  // `contenido` hasta que el worker STT lo transcribe (`transcripcion_estado
  // != "ok"`); el tipo TS refleja la misma nulabilidad que `MessageOut`
  // (backend/app/schemas/message.py), antes optimista (`string`).
  contenido: string | null;
  sentimiento: string | null;
  sentimiento_score: number | null;
  estado_entrega: string;
  activo: boolean;
  created_at: string;
  updated_at: string;
  // Discriminador de tipo (SPEC-053 RF-01), expuesto de forma ADITIVA por
  // SPEC-059 para que el adaptador derive `ConversationMessage.isTranscribedAudio`
  // ("texto" | "audio"; opcional/null-safe por si un backend más antiguo aún
  // no lo envía).
  tipo?: string | null;
}

export interface BackendCitation {
  source: string;
  excerpt: string;
  similarityScore: number;
  chunk_id: string;
  document_id: string;
}

/**
 * Respuesta de audio (TTS de salida, Entregable #6, SPEC-069/070/ADR-014):
 * `respuesta_modo` ("texto" default | "audio") y `tts_estado` (estado de la
 * ruta OPCIONAL "escuchar antes de enviar", null/"no_solicitado"/"generando"/
 * "listo"/"error") reflejan 1:1 `backend/app/schemas/rag.py::DraftOut`.
 * `audio_listo` es un booleano YA derivado por el backend (`tts_estado ==
 * "listo"`) — la SPA nunca reimplementa esa derivación.
 */
export type BackendRespuestaModo = "texto" | "audio";
export type BackendTtsEstado =
  | "no_solicitado"
  | "generando"
  | "listo"
  | "error";

export interface BackendDraft {
  id: string;
  tenant_id: string;
  conversation_id: string;
  query: string;
  content: string;
  content_original: string;
  model: string;
  citations: BackendCitation[];
  estado: string;
  edited_by: string | null;
  approved_by: string | null;
  sent_message_id: string | null;
  respuesta_modo: BackendRespuestaModo;
  tts_estado: BackendTtsEstado | null;
  audio_listo: boolean;
  activo: boolean;
  created_at: string;
  updated_at: string;
}

export interface LoginRequestBody {
  tenant_slug: string;
  email: string;
  password: string;
}

export interface LoginResponseBody {
  access_token: string;
  token_type: string;
  expires_in: number;
}

/* ---------- Protocolo WebSocket del WebChat (SPEC-015) ---------- */

export interface WsOutgoingMessageEvent {
  type: "message";
  message: BackendMessage;
}

export interface WsDeliveryStatusEvent {
  type: "delivery_status";
  message_id: string;
  conversation_id: string;
  estado_entrega: string;
}

export interface WsErrorEvent {
  type: "error";
  detail: string;
}

export type WsServerEvent = WsOutgoingMessageEvent | WsDeliveryStatusEvent | WsErrorEvent;

/* ---------- Canal de voz — ficha de llamada (SPEC-040) ----------
 *
 * Rutas exactas de `backend/app/api/calls.py` (montadas bajo `/api/v1`):
 *   GET /calls
 *   GET /calls/{id}
 *   GET /calls/{id}/audio (binario, no JSON — ver `callsApi.ts`)
 */

export interface BackendCall {
  id: string;
  tenant_id: string;
  call_id: string;
  numero: string;
  direccion: "entrante" | "saliente";
  duracion: number | null;
  estado: string;
  contact_id: string | null;
  conversation_id: string | null;
  resumen: string | null;
  audio_disponible: boolean;
  activo: boolean;
  created_at: string;
  updated_at: string;
}

export interface BackendTranscriptSegment {
  inicio: number;
  fin: number;
  texto: string;
  hablante: string;
}

export interface BackendCallTranscript {
  id: string;
  call_id: string;
  segmentos: BackendTranscriptSegment[];
  idioma: string;
  modelo_stt: string;
  wer: number | null;
}

export interface BackendCallSentiment {
  sentimiento: string | null;
  sentimiento_score: number | null;
}

export interface BackendCallRagDraft {
  id: string;
  conversation_id: string;
  content: string;
  content_original: string;
  model: string;
  citations: BackendCitation[];
  estado: string;
  edited_by: string | null;
  approved_by: string | null;
  sent_message_id: string | null;
}

export interface BackendCallDetail {
  call: BackendCall;
  transcript: BackendCallTranscript | null;
  sentiment: BackendCallSentiment;
  rag_draft: BackendCallRagDraft | null;
}

/* ---------- Analítica de negocio (SPEC-063) ----------
 *
 * Ruta exacta de `backend/app/api/analytics.py` (montada bajo `/api/v1`):
 *   GET /analytics/business?desde=YYYY-MM-DD&hasta=YYYY-MM-DD[&canal=...]
 *
 * Refleja 1:1 `backend/app/schemas/analytics.py` (`BusinessAnalyticsOut` y
 * anidados) — SOLO agregados del tenant, sin PII individual (RF-04 SPEC-062).
 */

export interface BackendConversacionesPorCanal {
  canal: string;
  total: number;
  abiertas: number;
  cerradas: number;
}

export interface BackendSerieDiariaPunto {
  fecha: string;
  total: number;
}

export interface BackendConversationMetrics {
  total: number;
  abiertas: number;
  cerradas: number;
  por_canal: BackendConversacionesPorCanal[];
  serie_diaria: BackendSerieDiariaPunto[];
}

export interface BackendResponseTimeMetrics {
  primera_respuesta_promedio_seg: number | null;
  respuesta_promedio_seg: number | null;
  conversaciones_con_respuesta: number;
}

export interface BackendConversionMetrics {
  tasa: number | null;
  cerradas: number;
  totales: number;
}

export interface BackendSentimientoDistribucion {
  positivo: number;
  neutral: number;
  negativo: number;
  sin_clasificar: number;
}

export interface BackendAiAssistanceMetrics {
  pct_drafts_aprobados: number | null;
  conversaciones_con_draft_aprobado: number;
  conversaciones_total: number;
  sentimiento: BackendSentimientoDistribucion;
}

export interface BackendBusinessAnalytics {
  desde: string;
  hasta: string;
  canal: string | null;
  conversaciones: BackendConversationMetrics;
  tiempos_respuesta: BackendResponseTimeMetrics;
  conversion: BackendConversionMetrics;
  ia_asistencia: BackendAiAssistanceMetrics | null;
}
