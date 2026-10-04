/**
 * Adaptadores backend real -> contrato de la maqueta (`src/lib/types.ts`),
 * SPEC-020 (RNF-07: "cliente tipado; contratos respetados o adaptador
 * documentado").
 *
 * El backend (SPEC-012/014/017/018/019) es deliberadamente más simple que la
 * maqueta visual (SPEC-001..009): estos adaptadores documentan CADA
 * diferencia y cómo se resuelve, en vez de inventar campos no pedidos por
 * las specs del backend.
 *
 * ---------------------------------------------------------------------
 * Diferencias de contrato conocidas (documentadas, no ocultas):
 * ---------------------------------------------------------------------
 * 1. `Conversation.channel` (maqueta: whatsapp/instagram/messenger/webchat)
 *    <- `BackendConversation.canal` (string libre validado contra el mismo
 *    conjunto en `app/schemas/conversation.py`, CANALES_VALIDOS). Slice #2
 *    (SPEC-014/015) solo crea conversaciones de canal "webchat"; el adaptador
 *    hace un cast seguro con fallback a "webchat" si llegara un valor no
 *    reconocido (defensivo, no debería ocurrir dado el validador backend).
 *
 * 2. `Conversation.sentiment` (maqueta: por CONVERSACIÓN, positivo/neutral/
 *    negativo) <- el backend calcula sentimiento POR MENSAJE
 *    (`Message.sentimiento`, SPEC-018), no por conversación. El adaptador
 *    deriva el sentimiento de la conversación tomando el del ÚLTIMO mensaje
 *    con sentimiento calculado (más reciente primero); si ningún mensaje aún
 *    tiene sentimiento (análisis en curso / sin mensajes), se usa "neutral"
 *    como default explícito (nunca se inventa un valor optimista/negativo).
 *
 * 3. `Conversation.lastMessage` / `lastMessageAt` / `unreadCount`: el backend
 *    no expone estos campos derivados directamente en `ConversationOut`
 *    (SPEC-014 no los pidió). El adaptador los calcula en el data provider
 *    a partir de la lista de mensajes ya cargada (`adaptConversationSummary`
 *    recibe el último mensaje opcionalmente); `unreadCount` no tiene
 *    contraparte en el backend (no hay estado de lectura por AGENTE, solo
 *    `estado_entrega` del MENSAJE) y se fija en 0 (documentado: fuera de
 *    alcance de SPEC-014/015, ninguna UI depende de que sea != 0 para
 *    funcionar).
 *
 * 4. `ConversationMessage.direction` (maqueta: entrante/saliente) <-
 *    `BackendMessage.remitente` ("contacto" | "agente" | "ia"): "contacto"
 *    -> "entrante"; "agente"/"ia" -> "saliente" (un mensaje generado por la
 *    IA y luego aprobado por SPEC-019 se envía como salida del negocio,
 *    igual que uno del agente).
 *
 * 5. `ConversationMessage.status` (maqueta: enviado/entregado/leido) <-
 *    `BackendMessage.estado_entrega` (mismo dominio de valores en
 *    `app/services/message_service.py`; se copia 1:1, con "enviado" como
 *    fallback si llegara un valor no reconocido).
 *
 * 6. `Contact` de la maqueta (company, tags, sector, lifetimeValue,
 *    lastInteraction, notes, avatarInitials) NO tiene contraparte en
 *    `BackendContact`/`ContactOut` (SPEC-012/014 solo definieron nombre/
 *    teléfono/email — ver nota explícita en
 *    `backend/app/schemas/contact.py`). SPEC-020 NO inventa esas columnas en
 *    el backend (fuera de alcance): el adaptador `adaptContact` rellena los
 *    campos ausentes con valores neutros/derivados (iniciales calculadas del
 *    nombre real; el resto con placeholders explícitos "—"/vacío) para que
 *    `Contact360Panel` siga renderizando sin romperse, dejando claro que esa
 *    información aún no viene de una fuente real.
 *
 * 7. `Conversation.whatsappWindow` (SPEC-031, sin contraparte en
 *    `ConversationOut`): la ventana de servicio de 24 h de WhatsApp
 *    (RF-03 SPEC-029) se calcula en `backend/app/workers/wa_send_worker.py`
 *    a partir del último mensaje ENTRANTE de la conversación, con la MISMA
 *    ventana de 24 h por defecto (`WHATSAPP_SESSION_WINDOW_HOURS`). El
 *    adaptador `adaptWhatsappWindow` replica ese mismo criterio (fail-closed:
 *    sin mensaje entrante -> fuera de ventana) a partir de los mensajes ya
 *    adaptados, sin requerir un endpoint nuevo (fuera de alcance de
 *    SPEC-031, que solo pide el indicador visual). Solo se calcula para
 *    `channel === "whatsapp"`; el resto de canales no lo usa.
 *
 * 8. RAG (`RagCitation`/`RagDraft`): el backend expone borradores
 *    persistidos con estado (`propuesto`/`editado`/`enviado`/`descartado`,
 *    SPEC-019) y una lista de citas con `similarityScore` ya en 0..1 (mismo
 *    rango que la maqueta). El adaptador `adaptDraft` mapea 1:1 (misma
 *    forma), generando `id`/`conversationId` sintéticos para calzar con
 *    `RagCitation`/`RagDraft` de `types.ts` (que no tienen equivalente
 *    exacto de `chunk_id`/`document_id`, se concatenan en el `id`).
 *    `RagSuggestion` (venta cruzada) NO tiene contraparte en el backend
 *    (SPEC-017/019 no la definieron): permanece en modo mock aunque el flag
 *    esté ON (reemplazo módulo a módulo, RF de SPEC-020).
 *
 * 9. `ConversationMessage.isTranscribedAudio` (SPEC-059) <-
 *    `BackendMessage.tipo === "audio"` (SPEC-053): booleano ya resuelto para
 *    que el componente de mensaje no tenga que conocer el vocabulario crudo
 *    del backend ("texto"/"audio"). Puramente aditivo (RF-03 SPEC-059): con
 *    el flag OFF la maqueta no pasa por este adaptador y el campo queda
 *    `undefined`, sin regresión. Además, `contenido` puede llegar `null`
 *    (nota del schema `MessageOut`, un audio aún sin transcribir) — `text`
 *    hace fallback a cadena vacía (`?? ""`) para no romper el render.
 *
 * 10. `RagDraft.respuestaModo`/`ttsEstado`/`audioListo` (SPEC-069/070,
 *     ADR-014, Entregable #6) <- `BackendDraft.respuesta_modo`/`tts_estado`/
 *     `audio_listo`: copia 1:1 (mismo vocabulario, sin traducción) porque
 *     `RagDraftCard` (SPEC-070) consume directamente esos valores para
 *     decidir qué controles de audio mostrar. Puramente aditivo: con el
 *     flag OFF la maqueta (`src/mocks/rag.json`) no pasa por este adaptador
 *     y los tres campos quedan `undefined` — `RagDraftCard` los trata como
 *     `"texto"`/sin solicitar, igual que el comportamiento previo a esta
 *     SPEC (RNF-FLAG).
 *
 * 11. `ConversationMessage.mediaUrl`/`mediaType` (SPEC-088/090) <-
 *     `BackendMessage.media_url`/`media_type`: copia 1:1 SIN transformación
 *     — es la URL FIRMADA del CDN de Meta (`lookaside.fbsbx.com`) de un
 *     adjunto de DM de Instagram, que el backend solo transporta como
 *     cadena (RF-06 SPEC-088). `ConversationThread` (SPEC-090) la usa para
 *     renderizar un `<img>` (si `mediaType === "image"`) o un enlace "Abrir
 *     adjunto" (otros tipos), con el fetch real ocurriendo en el NAVEGADOR
 *     del agente, nunca en el backend. Explícitamente DISTINTO del patrón
 *     de `isTranscribedAudio` (nota 9): ese es un dato local cifrado
 *     (ADR-009), este es una referencia externa de solo lectura que puede
 *     expirar (Meta la invalida si el contacto borra el contenido) —
 *     limitación aceptada, sin mecanismo de refresco. `undefined`/`null` en
 *     modo mock o si el backend aún no envía el campo (null-safe).
 */

import type {
  BackendCall,
  BackendCallDetail,
  BackendCitation,
  BackendConversation,
  BackendDraft,
  BackendMessage,
} from "@/lib/api/backendTypes";
import type {
  CallDirection,
  Channel,
  Contact,
  Conversation,
  ConversationMessage,
  MessageDirection,
  MessageStatus,
  RagCitation,
  RagDraft,
  RealCallDetail,
  RealCallRecord,
  Sentiment,
  WhatsappServiceWindow,
} from "@/lib/types";

/** RF-03 SPEC-029: mismo default que `Settings.whatsapp_session_window_hours`
 * (`backend/app/core/config.py`, `WHATSAPP_SESSION_WINDOW_HOURS=24`). Es un
 * valor puramente informativo para el indicador SPA (SPEC-031); la decisión
 * real de bloquear/usar plantilla ocurre en el backend (`wa_send_worker`). */
const WHATSAPP_SERVICE_WINDOW_HOURS = 24;

const VALID_CHANNELS: readonly Channel[] = [
  "whatsapp",
  "instagram",
  "messenger",
  "webchat",
];

function adaptChannel(canal: string): Channel {
  return (VALID_CHANNELS as string[]).includes(canal) ? (canal as Channel) : "webchat";
}

const VALID_STATUSES: readonly MessageStatus[] = [
  "enviado",
  "entregado",
  "leido",
  "failed",
];

function adaptMessageStatus(estadoEntrega: string): MessageStatus {
  return (VALID_STATUSES as string[]).includes(estadoEntrega)
    ? (estadoEntrega as MessageStatus)
    : "enviado";
}

function adaptDirection(remitente: BackendMessage["remitente"]): MessageDirection {
  return remitente === "contacto" ? "entrante" : "saliente";
}

const VALID_SENTIMENTS: readonly Sentiment[] = ["positivo", "neutral", "negativo"];

function adaptSentiment(sentimiento: string | null): Sentiment {
  if (sentimiento && (VALID_SENTIMENTS as string[]).includes(sentimiento)) {
    return sentimiento as Sentiment;
  }
  return "neutral";
}

export function adaptMessage(message: BackendMessage): ConversationMessage {
  return {
    id: message.id,
    direction: adaptDirection(message.remitente),
    // Fallback a "" (nota 9 del docblock del módulo): `contenido` puede ser
    // `null` para una nota de voz aún sin transcribir.
    text: message.contenido ?? "",
    sentAt: message.created_at,
    status: adaptMessageStatus(message.estado_entrega),
    isTranscribedAudio: message.tipo === "audio",
    // Nota 11 (SPEC-088/090): copia 1:1, sin transformación — es una URL
    // externa que el CLIENTE consume directamente, el adaptador no la valida
    // ni la reescribe (la validación de forma ya ocurrió en el backend,
    // SPEC-088 RF-03).
    mediaUrl: message.media_url ?? null,
    mediaType: message.media_type ?? null,
  };
}

/**
 * Ventana de servicio de 24 h de WhatsApp (nota 7 del docblock del módulo,
 * RF-03 SPEC-029 / RF-02 SPEC-031): se mide desde el último mensaje
 * ENTRANTE (remitente "contacto"). Fail-closed, igual que el backend
 * (`_within_service_window`): sin mensaje entrante -> fuera de ventana.
 */
export function adaptWhatsappWindow(
  messages: BackendMessage[],
  now: Date = new Date(),
): WhatsappServiceWindow {
  const lastInbound = [...messages]
    .reverse()
    .find((m) => m.remitente === "contacto");

  if (!lastInbound) {
    return { withinWindow: false, lastInboundAt: null };
  }

  const lastInboundAt = new Date(lastInbound.created_at);
  const elapsedMs = now.getTime() - lastInboundAt.getTime();
  const windowMs = WHATSAPP_SERVICE_WINDOW_HOURS * 60 * 60 * 1000;

  return {
    withinWindow: elapsedMs <= windowMs,
    lastInboundAt: lastInbound.created_at,
  };
}

/**
 * Adapta una conversación real + sus mensajes ya cargados (SPEC-020, nota 2
 * y 3 del docblock del módulo: `lastMessage`/`sentiment` se derivan de los
 * mensajes porque `ConversationOut` no los expone).
 */
export function adaptConversation(
  conversation: BackendConversation,
  messages: BackendMessage[],
): Conversation {
  const adaptedMessages = messages.map(adaptMessage);
  const lastBackendMessage = messages.at(-1);
  const lastMessageWithSentiment = [...messages]
    .reverse()
    .find((m) => m.sentimiento !== null);
  const channel = adaptChannel(conversation.canal);

  return {
    id: conversation.id,
    contactId: conversation.contact_id,
    channel,
    sentiment: adaptSentiment(lastMessageWithSentiment?.sentimiento ?? null),
    lastMessage: lastBackendMessage?.contenido ?? "",
    lastMessageAt: lastBackendMessage?.created_at ?? conversation.updated_at,
    // Sin contraparte backend (nota 3): 0 explícito, no inventado.
    unreadCount: 0,
    status: conversation.estado as Conversation["status"],
    messages: adaptedMessages,
    // Solo WhatsApp tiene ventana de servicio (nota 7); otros canales no la usan.
    whatsappWindow: channel === "whatsapp" ? adaptWhatsappWindow(messages) : undefined,
  };
}

function initialsFromName(nombre: string): string {
  const parts = nombre.trim().split(/\s+/).filter(Boolean);
  const initials = parts.slice(0, 2).map((part) => part[0]?.toUpperCase() ?? "");
  return initials.join("") || "??";
}

/**
 * Adapta un contacto real (SPEC-012/014) al `Contact` de la maqueta (nota 6
 * del docblock del módulo): los campos sin contraparte backend quedan con
 * placeholders explícitos, nunca datos inventados que parezcan reales.
 */
export function adaptContact(backendContact: {
  id: string;
  nombre: string;
  telefono: string | null;
  email: string | null;
}): Contact {
  return {
    id: backendContact.id,
    name: backendContact.nombre,
    company: "—",
    email: backendContact.email ?? "—",
    phone: backendContact.telefono ?? "—",
    avatarInitials: initialsFromName(backendContact.nombre),
    tags: [],
    sector: "comercial",
    lifetimeValue: 0,
    lastInteraction: "",
  };
}

function citationId(citation: BackendCitation, index: number): string {
  return `${citation.document_id}:${citation.chunk_id}:${index}`;
}

export function adaptCitations(
  conversationId: string,
  citations: BackendCitation[],
): RagCitation[] {
  return citations.map((citation, index) => ({
    id: citationId(citation, index),
    conversationId,
    source: citation.source,
    excerpt: citation.excerpt,
    similarityScore: citation.similarityScore,
  }));
}

export function adaptDraft(draft: BackendDraft): RagDraft {
  return {
    id: draft.id,
    conversationId: draft.conversation_id,
    text: draft.content,
    generatedAt: draft.created_at,
    respuestaModo: draft.respuesta_modo,
    ttsEstado: draft.tts_estado,
    audioListo: draft.audio_listo,
  };
}

/* ---------- Canal de voz — ficha de llamada (SPEC-040) ---------- */

const VALID_CALL_DIRECTIONS: readonly CallDirection[] = ["entrante", "saliente"];

function adaptCallDirection(direccion: string): CallDirection {
  return (VALID_CALL_DIRECTIONS as string[]).includes(direccion)
    ? (direccion as CallDirection)
    : "entrante";
}

/** Adapta el resumen de listado (`BackendCall`, `GET /calls`) al contrato de
 * la ficha real de llamada (nota: SIN transcripción/sentimiento/borrador —
 * esos solo vienen en el detalle, `GET /calls/{id}`, para no sobrecargar el
 * listado). */
export function adaptCall(call: BackendCall): RealCallRecord {
  return {
    id: call.id,
    contactId: call.contact_id,
    conversationId: call.conversation_id,
    callId: call.call_id,
    numero: call.numero,
    direccion: adaptCallDirection(call.direccion),
    duracionSeconds: call.duracion,
    estado: call.estado,
    resumen: call.resumen,
    audioDisponible: call.audio_disponible,
    createdAt: call.created_at,
  };
}

/**
 * Adapta la ficha completa de una llamada (SPEC-040, `GET /calls/{id}`):
 * transcripción real (segmentos + timestamps + hablante), sentimiento,
 * resumen y borrador citado (`≥3` citas, RF-02 SPEC-040). Reutiliza
 * `adaptSentiment`/`adaptCitations` (mismas funciones que la Bandeja/RAG) en
 * vez de duplicar la lógica de mapeo.
 */
export function adaptCallDetail(detail: BackendCallDetail): RealCallDetail {
  const draft = detail.rag_draft;
  return {
    call: adaptCall(detail.call),
    transcript: detail.transcript
      ? {
          id: detail.transcript.id,
          callId: detail.transcript.call_id,
          segmentos: detail.transcript.segmentos.map((segmento) => ({
            inicio: segmento.inicio,
            fin: segmento.fin,
            texto: segmento.texto,
            hablante: segmento.hablante,
          })),
          idioma: detail.transcript.idioma,
          modeloStt: detail.transcript.modelo_stt,
          wer: detail.transcript.wer,
        }
      : null,
    sentiment:
      detail.sentiment.sentimiento !== null
        ? adaptSentiment(detail.sentiment.sentimiento)
        : null,
    sentimentScore: detail.sentiment.sentimiento_score,
    ragDraft: draft
      ? {
          id: draft.id,
          conversationId: draft.conversation_id,
          content: draft.content,
          contentOriginal: draft.content_original,
          model: draft.model,
          citations: adaptCitations(draft.conversation_id, draft.citations),
          estado: draft.estado,
          editedBy: draft.edited_by,
          approvedBy: draft.approved_by,
          sentMessageId: draft.sent_message_id,
        }
      : null,
  };
}
