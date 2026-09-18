import { describe, expect, it } from "vitest";
import {
  adaptContact,
  adaptConversation,
  adaptCitations,
  adaptDraft,
  adaptMessage,
} from "@/lib/api/adapters";
import type { BackendConversation, BackendMessage } from "@/lib/api/backendTypes";

/**
 * SPEC-020 — Adaptadores backend real -> `src/lib/types.ts` (documentados en
 * `src/lib/api/adapters.ts`). Pruebas puras, sin red.
 */
describe("adaptMessage", () => {
  const base: BackendMessage = {
    id: "m1",
    tenant_id: "t1",
    conversation_id: "c1",
    remitente: "contacto",
    contenido: "Hola",
    sentimiento: "positivo",
    sentimiento_score: 0.9,
    estado_entrega: "entregado",
    activo: true,
    created_at: "2026-09-15T14:20:00-05:00",
    updated_at: "2026-09-15T14:20:00-05:00",
  };

  it("mapea remitente=contacto a direction=entrante", () => {
    expect(adaptMessage(base).direction).toBe("entrante");
  });

  it("mapea remitente=agente y remitente=ia a direction=saliente", () => {
    expect(adaptMessage({ ...base, remitente: "agente" }).direction).toBe("saliente");
    expect(adaptMessage({ ...base, remitente: "ia" }).direction).toBe("saliente");
  });

  it("hace fallback a estado 'enviado' ante un estado_entrega desconocido", () => {
    expect(adaptMessage({ ...base, estado_entrega: "raro" }).status).toBe("enviado");
  });
});

describe("adaptConversation", () => {
  const conversation: BackendConversation = {
    id: "c1",
    tenant_id: "t1",
    contact_id: "contact-1",
    canal: "webchat",
    estado: "abierta",
    activo: true,
    created_at: "2026-09-15T14:00:00-05:00",
    updated_at: "2026-09-15T14:30:00-05:00",
  };

  it("deriva lastMessage/lastMessageAt del último mensaje", () => {
    const messages: BackendMessage[] = [
      {
        id: "m1",
        tenant_id: "t1",
        conversation_id: "c1",
        remitente: "contacto",
        contenido: "Primero",
        sentimiento: null,
        sentimiento_score: null,
        estado_entrega: "leido",
        activo: true,
        created_at: "2026-09-15T14:10:00-05:00",
        updated_at: "2026-09-15T14:10:00-05:00",
      },
      {
        id: "m2",
        tenant_id: "t1",
        conversation_id: "c1",
        remitente: "agente",
        contenido: "Último mensaje",
        sentimiento: "negativo",
        sentimiento_score: 0.2,
        estado_entrega: "entregado",
        activo: true,
        created_at: "2026-09-15T14:20:00-05:00",
        updated_at: "2026-09-15T14:20:00-05:00",
      },
    ];
    const result = adaptConversation(conversation, messages);
    expect(result.lastMessage).toBe("Último mensaje");
    expect(result.lastMessageAt).toBe("2026-09-15T14:20:00-05:00");
    expect(result.sentiment).toBe("negativo");
    expect(result.unreadCount).toBe(0);
    expect(result.messages).toHaveLength(2);
  });

  it("usa 'neutral' cuando ningún mensaje tiene sentimiento calculado aún", () => {
    const messages: BackendMessage[] = [
      {
        id: "m1",
        tenant_id: "t1",
        conversation_id: "c1",
        remitente: "contacto",
        contenido: "Hola",
        sentimiento: null,
        sentimiento_score: null,
        estado_entrega: "enviado",
        activo: true,
        created_at: "2026-09-15T14:10:00-05:00",
        updated_at: "2026-09-15T14:10:00-05:00",
      },
    ];
    expect(adaptConversation(conversation, messages).sentiment).toBe("neutral");
  });

  it("hace fallback de canal a 'webchat' ante un valor no reconocido", () => {
    const result = adaptConversation({ ...conversation, canal: "sms" }, []);
    expect(result.channel).toBe("webchat");
  });
});

describe("adaptContact", () => {
  it("calcula iniciales del nombre real y placeholders explícitos para campos sin contraparte backend", () => {
    const contact = adaptContact({
      id: "contact-1",
      nombre: "Laura Gómez",
      telefono: "3001234567",
      email: "laura@example.com",
    });
    expect(contact.avatarInitials).toBe("LG");
    expect(contact.company).toBe("—");
    expect(contact.tags).toEqual([]);
    expect(contact.lifetimeValue).toBe(0);
  });
});

describe("adaptCitations / adaptDraft", () => {
  it("adapta citas con id sintético trazable a document_id/chunk_id", () => {
    const result = adaptCitations("c1", [
      {
        source: "Catálogo.pdf",
        excerpt: "fragmento",
        similarityScore: 0.9,
        chunk_id: "chunk-1",
        document_id: "doc-1",
      },
    ]);
    expect(result).toHaveLength(1);
    expect(result[0].conversationId).toBe("c1");
    expect(result[0].id).toContain("doc-1");
  });

  it("adapta un borrador real a RagDraft", () => {
    const draft = adaptDraft({
      id: "draft-1",
      tenant_id: "t1",
      conversation_id: "c1",
      query: "q",
      content: "Respuesta sugerida",
      content_original: "Respuesta sugerida",
      model: "qwen2.5:7b-instruct",
      citations: [],
      estado: "propuesto",
      edited_by: null,
      approved_by: null,
      sent_message_id: null,
      activo: true,
      created_at: "2026-09-15T14:20:00-05:00",
      updated_at: "2026-09-15T14:20:00-05:00",
    });
    expect(draft).toEqual({
      id: "draft-1",
      conversationId: "c1",
      text: "Respuesta sugerida",
      generatedAt: "2026-09-15T14:20:00-05:00",
    });
  });
});
