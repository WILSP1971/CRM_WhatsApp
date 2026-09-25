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
  contenido: string;
  sentimiento: string | null;
  sentimiento_score: number | null;
  estado_entrega: string;
  activo: boolean;
  created_at: string;
  updated_at: string;
}

export interface BackendCitation {
  source: string;
  excerpt: string;
  similarityScore: number;
  chunk_id: string;
  document_id: string;
}

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
