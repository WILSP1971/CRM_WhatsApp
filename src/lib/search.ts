import contactsData from "@/mocks/contacts.json";
import conversationsData from "@/mocks/conversations.json";
import type { Contact, Conversation } from "@/lib/types";

export interface SearchResultItem {
  id: string;
  title: string;
  subtitle: string;
}

export interface SearchResultGroup {
  category: "Contactos" | "Conversaciones" | "Documentos RAG";
  items: SearchResultItem[];
}

const contacts = contactsData as Contact[];
const conversations = conversationsData as Conversation[];

/** Documentos RAG ficticios, solo para poblar la categoría de búsqueda (mock). */
const RAG_DOCS: SearchResultItem[] = [
  {
    id: "doc-001",
    title: "Política de devoluciones 2026",
    subtitle: "Base de conocimiento · PDF",
  },
  {
    id: "doc-002",
    title: "Catálogo de productos Q3",
    subtitle: "Base de conocimiento · Hoja de cálculo",
  },
  {
    id: "doc-003",
    title: "Guion de atención VoiceBot",
    subtitle: "Base de conocimiento · Documento",
  },
];

/**
 * Búsqueda semántica SIMULADA (SPEC-003 RF-08): filtra localmente sobre las
 * fixtures mock. No hay red, no hay RAG real, no hay LLM.
 */
export function searchMock(query: string): SearchResultGroup[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];

  const matchedContacts = contacts
    .filter(
      (c) => c.name.toLowerCase().includes(q) || c.company.toLowerCase().includes(q),
    )
    .map((c) => ({ id: c.id, title: c.name, subtitle: c.company }));

  const matchedConversations = conversations
    .filter((c) => c.lastMessage.toLowerCase().includes(q))
    .map((c) => ({
      id: c.id,
      title: `Conversación ${c.channel}`,
      subtitle: c.lastMessage,
    }));

  const matchedDocs = RAG_DOCS.filter((d) => d.title.toLowerCase().includes(q));

  const groups: SearchResultGroup[] = [
    { category: "Contactos", items: matchedContacts },
    { category: "Conversaciones", items: matchedConversations },
    { category: "Documentos RAG", items: matchedDocs },
  ];

  return groups.filter((group) => group.items.length > 0);
}
