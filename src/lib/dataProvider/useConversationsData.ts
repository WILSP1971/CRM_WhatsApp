/**
 * Hook de datos de la Bandeja (SPEC-020): alterna mock/real según
 * `USE_REAL_API` (feature-flag). Reemplaza el import directo de
 * `src/mocks/conversations.json`/`contacts.json` en `InboxPage`.
 *
 * Con el flag OFF (default): devuelve EXACTAMENTE los mismos fixtures que
 * hoy, de forma síncrona, sin ningún `fetch`/WebSocket -> cero llamadas de
 * red, maqueta intacta (RF-05).
 *
 * Con el flag ON: carga conversaciones+mensajes reales vía REST
 * (SPEC-014) y luego se suscribe al WebSocket del WebChat (SPEC-015) de la
 * conversación seleccionada para reflejar mensajes/estado de entrega en
 * vivo (RF-08, RF "Bandeja muestra conversaciones/mensajes reales por
 * WebSocket").
 */

import { useEffect, useMemo, useState } from "react";
import conversationsData from "@/mocks/conversations.json";
import contactsData from "@/mocks/contacts.json";
import type { Contact, Conversation } from "@/lib/types";
import { USE_REAL_API } from "@/lib/env";
import {
  fetchConversations,
  fetchMessages,
  sendMessage,
} from "@/lib/api/conversationsApi";
import { adaptContact, adaptConversation, adaptMessage } from "@/lib/api/adapters";
import { connectWebChat, type WebChatSocketHandle } from "@/lib/api/wsClient";
import { ensureDevSession } from "@/lib/dataProvider/devSession";
import type { BackendContact } from "@/lib/api/backendTypes";

const mockConversations = conversationsData as Conversation[];
const mockContacts = contactsData as Contact[];

export interface ConversationsDataState {
  conversations: Conversation[];
  contactsById: Record<string, Contact>;
  /** `true` mientras se resuelve la carga inicial en modo real; siempre `false` en modo mock. */
  loading: boolean;
  /** Mensaje de error de la integración real (p.ej. backend caído); `null` en modo mock. */
  error: string | null;
  /** Envía un mensaje saliente por el canal activo (WS real u no-op en mock). */
  sendOutgoingMessage: (conversationId: string, contenido: string) => void;
}

function toContactsById(contacts: Contact[]): Record<string, Contact> {
  return Object.fromEntries(contacts.map((contact) => [contact.id, contact]));
}

/**
 * Trae contactos reales bajo demanda (SPEC-014, GET /contacts) para poblar
 * `contactsById` solo con los contactos referenciados por conversaciones
 * reales (evita traer el listado completo del tenant sin necesidad).
 */
async function fetchContactsByIds(_ids: string[]): Promise<BackendContact[]> {
  // Nota (adaptador documentado, SPEC-020): `GET /contacts` no soporta
  // filtro por lista de ids (SPEC-014 solo expone filtro por `nombre`), así
  // que se resuelve por `GET /contacts/{id}` individual: alcance simple,
  // acorde al tamaño de una bandeja de demo. Implementado en
  // `fetchContactsByIdsImpl` para permitir mock en tests.
  return fetchContactsByIdsImpl(_ids);
}

async function fetchContactsByIdsImpl(ids: string[]): Promise<BackendContact[]> {
  const { apiFetch } = await import("@/lib/api/httpClient");
  const uniqueIds = Array.from(new Set(ids));
  const results = await Promise.all(
    uniqueIds.map((id) => apiFetch<BackendContact>(`/contacts/${id}`).catch(() => null)),
  );
  return results.filter((c): c is BackendContact => c !== null);
}

export function useConversationsData(
  selectedConversationId: string | null,
): ConversationsDataState {
  const [realConversations, setRealConversations] = useState<Conversation[]>([]);
  const [realContactsById, setRealContactsById] = useState<Record<string, Contact>>({});
  const [loading, setLoading] = useState(USE_REAL_API);
  const [error, setError] = useState<string | null>(null);
  const [socketHandle, setSocketHandle] = useState<WebChatSocketHandle | null>(null);

  // Carga inicial real: login de dev -> conversaciones -> mensajes -> contactos.
  useEffect(() => {
    if (!USE_REAL_API) return;
    let cancelled = false;

    async function load() {
      try {
        setLoading(true);
        setError(null);
        await ensureDevSession();
        const page = await fetchConversations({ pageSize: 50 });
        const withMessages = await Promise.all(
          page.items.map(async (conversation) => {
            const messagesPage = await fetchMessages(conversation.id, { pageSize: 100 });
            return adaptConversation(conversation, messagesPage.items);
          }),
        );
        if (cancelled) return;
        setRealConversations(withMessages);

        const contactIds = page.items.map((c) => c.contact_id);
        const backendContacts = await fetchContactsByIds(contactIds);
        if (cancelled) return;
        setRealContactsById(toContactsById(backendContacts.map(adaptContact)));
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof Error ? err.message : "Error cargando la Bandeja real.",
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  // Suscripción WebSocket a la conversación seleccionada (solo modo real).
  useEffect(() => {
    if (!USE_REAL_API || !selectedConversationId) return;
    let cancelled = false;
    let handle: WebChatSocketHandle | null = null;

    ensureDevSession()
      .then(() => {
        if (cancelled) return;
        handle = connectWebChat(selectedConversationId, {
          onEvent: (event) => {
            if (event.type !== "message") return;
            const incoming = adaptMessage(event.message);
            setRealConversations((prev) =>
              prev.map((conversation) =>
                conversation.id === selectedConversationId
                  ? {
                      ...conversation,
                      messages: [...conversation.messages, incoming],
                      lastMessage: incoming.text,
                      lastMessageAt: incoming.sentAt,
                    }
                  : conversation,
              ),
            );
          },
        });
        setSocketHandle(handle);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Error conectando el WebChat.");
        }
      });

    return () => {
      cancelled = true;
      handle?.close();
      setSocketHandle(null);
    };
  }, [selectedConversationId]);

  const sendOutgoingMessage = useMemo(
    () => (conversationId: string, contenido: string) => {
      if (!USE_REAL_API) return; // Modo mock: sin efecto (maqueta, no envía mensajes reales).
      if (socketHandle && conversationId === selectedConversationId) {
        socketHandle.sendMessage("agente", contenido);
        return;
      }
      // Fallback REST si el socket aún no está listo (p.ej. reconexión).
      void sendMessage(conversationId, { remitente: "agente", contenido });
    },
    [socketHandle, selectedConversationId],
  );

  if (!USE_REAL_API) {
    return {
      conversations: mockConversations,
      contactsById: toContactsById(mockContacts),
      loading: false,
      error: null,
      sendOutgoingMessage,
    };
  }

  return {
    conversations: realConversations,
    contactsById: realContactsById,
    loading,
    error,
    sendOutgoingMessage,
  };
}
