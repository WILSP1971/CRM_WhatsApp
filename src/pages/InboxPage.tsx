import { useEffect, useMemo, useState } from "react";
import { Card } from "@/components/ui";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui";
import { ConversationList } from "@/components/inbox/ConversationList";
import { ConversationThread } from "@/components/inbox/ConversationThread";
import { Contact360Panel } from "@/components/inbox/Contact360Panel";
import { RagPanel } from "@/components/rag/RagPanel";
import { useConversationsData } from "@/lib/dataProvider/useConversationsData";

/**
 * Bandeja omnicanal unificada (SPEC-004) + panel lateral RAG (SPEC-005).
 *
 * SPEC-020: los datos vienen de `useConversationsData`, que alterna
 * mock/real por `VITE_USE_REAL_API` (ver `src/lib/env.ts`). Con el flag OFF
 * el comportamiento es idéntico al Entregable #1 (mismos fixtures, sin red).
 */
export function InboxPage() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draftsByConversation, setDraftsByConversation] = useState<
    Record<string, string>
  >({});

  const { conversations, contactsById, loading, error } =
    useConversationsData(selectedId);

  // Selecciona la primera conversación disponible una vez cargadas (modo
  // mock: ocurre en el primer render, igual que antes; modo real: tras la
  // carga inicial por red).
  useEffect(() => {
    if (selectedId === null && conversations.length > 0) {
      setSelectedId(conversations[0].id);
    }
  }, [conversations, selectedId]);

  const selectedConversation = useMemo(
    () => conversations.find((c) => c.id === selectedId) ?? null,
    [conversations, selectedId],
  );
  const selectedContact = selectedConversation
    ? contactsById[selectedConversation.contactId]
    : undefined;

  const draftText = selectedId ? (draftsByConversation[selectedId] ?? "") : "";

  function handleDraftChange(value: string) {
    if (!selectedId) return;
    setDraftsByConversation((prev) => ({ ...prev, [selectedId]: value }));
  }

  function handleUseDraft(text: string) {
    if (!selectedId) return;
    setDraftsByConversation((prev) => ({ ...prev, [selectedId]: text }));
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      {error && (
        <div
          role="alert"
          className="border-state-danger-strong/40 bg-state-danger-strong/10 rounded-md border px-3 py-2 text-sm text-state-danger-strong"
        >
          No se pudo cargar la Bandeja real: {error}
        </div>
      )}
      <div className="grid h-full min-h-0 grid-cols-1 gap-4 lg:grid-cols-[320px_1fr_360px]">
        <Card
          className="flex min-h-0 flex-col overflow-hidden p-3"
          aria-label="Lista de conversaciones"
        >
          {loading ? (
            <div className="flex h-full items-center justify-center p-6 text-sm text-text-muted">
              Cargando conversaciones…
            </div>
          ) : (
            <ConversationList
              conversations={conversations}
              contactsById={contactsById}
              selectedId={selectedId}
              onSelect={setSelectedId}
            />
          )}
        </Card>

        <Card
          className="flex min-h-0 flex-col overflow-hidden p-0"
          aria-label="Hilo de conversación"
        >
          {selectedConversation ? (
            <ConversationThread
              conversation={selectedConversation}
              contact={selectedContact}
              draftText={draftText}
              onDraftChange={handleDraftChange}
            />
          ) : (
            <div className="flex h-full items-center justify-center p-6 text-sm text-text-muted">
              Selecciona una conversación para ver el hilo.
            </div>
          )}
        </Card>

        <div className="flex min-h-0 flex-col overflow-hidden">
          <Tabs defaultValue="rag" className="flex h-full min-h-0 flex-col">
            <TabsList aria-label="Panel derecho" className="mb-3 self-start">
              <TabsTrigger value="rag">Asistente RAG</TabsTrigger>
              <TabsTrigger value="contacto">Contacto 360°</TabsTrigger>
            </TabsList>
            <TabsContent value="rag" className="min-h-0 flex-1 overflow-hidden">
              <RagPanel conversationId={selectedId} onUseDraft={handleUseDraft} />
            </TabsContent>
            <TabsContent value="contacto" className="min-h-0 flex-1 overflow-hidden">
              <Contact360Panel contact={selectedContact} />
            </TabsContent>
          </Tabs>
        </div>
      </div>
    </div>
  );
}
