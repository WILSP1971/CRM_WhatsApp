import { useMemo, useState } from "react";
import { Card } from "@/components/ui";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui";
import { ConversationList } from "@/components/inbox/ConversationList";
import { ConversationThread } from "@/components/inbox/ConversationThread";
import { Contact360Panel } from "@/components/inbox/Contact360Panel";
import { RagPanel } from "@/components/rag/RagPanel";
import conversationsData from "@/mocks/conversations.json";
import contactsData from "@/mocks/contacts.json";
import type { Contact, Conversation } from "@/lib/types";

const conversations = conversationsData as Conversation[];
const contacts = contactsData as Contact[];

const contactsById = Object.fromEntries(
  contacts.map((contact) => [contact.id, contact]),
) as Record<string, Contact>;

/** Bandeja omnicanal unificada (SPEC-004) + panel lateral RAG (SPEC-005). */
export function InboxPage() {
  const [selectedId, setSelectedId] = useState<string | null>(
    conversations[0]?.id ?? null,
  );
  const [draftsByConversation, setDraftsByConversation] = useState<
    Record<string, string>
  >({});

  const selectedConversation = useMemo(
    () => conversations.find((c) => c.id === selectedId) ?? null,
    [selectedId],
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
    <div className="grid h-full min-h-0 grid-cols-1 gap-4 lg:grid-cols-[320px_1fr_360px]">
      <Card
        className="flex min-h-0 flex-col overflow-hidden p-3"
        aria-label="Lista de conversaciones"
      >
        <ConversationList
          conversations={conversations}
          contactsById={contactsById}
          selectedId={selectedId}
          onSelect={setSelectedId}
        />
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
  );
}
