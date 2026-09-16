import { useId, useMemo, useState } from "react";
import { Search } from "lucide-react";
import { Badge, Input } from "@/components/ui";
import { cn } from "@/lib/cn";
import { formatDateTime } from "@/lib/format";
import { CHANNEL_META, SENTIMENT_META } from "@/lib/channels";
import type { Channel, Contact, Conversation } from "@/lib/types";

interface ConversationListProps {
  conversations: Conversation[];
  contactsById: Record<string, Contact>;
  selectedId: string | null;
  onSelect: (id: string) => void;
}

const CHANNEL_FILTERS: Array<{ id: Channel | "todos"; label: string }> = [
  { id: "todos", label: "Todos" },
  { id: "whatsapp", label: "WhatsApp" },
  { id: "instagram", label: "Instagram" },
  { id: "messenger", label: "Messenger" },
  { id: "webchat", label: "Chat web" },
];

/** Lista de conversaciones multicanal (SPEC-004): filtro por canal + buscador. */
export function ConversationList({
  conversations,
  contactsById,
  selectedId,
  onSelect,
}: ConversationListProps) {
  const [channelFilter, setChannelFilter] = useState<Channel | "todos">("todos");
  const [query, setQuery] = useState("");
  const searchInputId = useId();

  const filtered = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return conversations.filter((conversation) => {
      const contact = contactsById[conversation.contactId];
      const matchesChannel =
        channelFilter === "todos" || conversation.channel === channelFilter;
      const matchesQuery =
        normalizedQuery.length === 0 ||
        contact?.name.toLowerCase().includes(normalizedQuery) ||
        conversation.lastMessage.toLowerCase().includes(normalizedQuery);
      return matchesChannel && matchesQuery;
    });
  }, [conversations, contactsById, channelFilter, query]);

  return (
    <div className="flex h-full flex-col gap-3">
      <div className="flex flex-col gap-2 px-1">
        <label htmlFor={searchInputId} className="sr-only">
          Buscar conversaciones por contacto o mensaje
        </label>
        <div className="relative">
          <Search
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted"
            aria-hidden
          />
          <Input
            id={searchInputId}
            type="search"
            placeholder="Buscar contacto o mensaje…"
            className="pl-9"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>

        <div
          role="group"
          aria-label="Filtrar conversaciones por canal"
          className="flex flex-wrap gap-1.5"
        >
          {CHANNEL_FILTERS.map((filter) => {
            const active = channelFilter === filter.id;
            return (
              <button
                key={filter.id}
                type="button"
                aria-pressed={active}
                onClick={() => setChannelFilter(filter.id)}
                className={cn(
                  "rounded-full border px-3 py-1 text-xs font-medium transition-colors duration-fast ease-standard",
                  "focus-visible:shadow-focus focus-visible:outline-none",
                  active
                    ? "border-accent-indigo bg-accent-indigo text-text-inverse"
                    : "border-border-subtle bg-bg-surface-raised text-text-secondary hover:border-accent-indigo",
                )}
              >
                {filter.label}
              </button>
            );
          })}
        </div>
      </div>

      <ul
        role="listbox"
        aria-label="Conversaciones"
        className="flex flex-1 flex-col gap-1 overflow-y-auto px-1 pb-2"
      >
        {filtered.length === 0 && (
          <li className="px-2 py-6 text-center text-sm text-text-muted">
            No hay conversaciones que coincidan con el filtro.
          </li>
        )}

        {filtered.map((conversation) => {
          const contact = contactsById[conversation.contactId];
          const channelMeta = CHANNEL_META[conversation.channel];
          const sentimentMeta = SENTIMENT_META[conversation.sentiment];
          const ChannelIcon = channelMeta.icon;
          const selected = conversation.id === selectedId;
          const hasUnread = conversation.unreadCount > 0;

          return (
            <li key={conversation.id} role="presentation">
              <button
                type="button"
                role="option"
                aria-selected={selected}
                onClick={() => onSelect(conversation.id)}
                className={cn(
                  "flex w-full flex-col gap-1.5 rounded-lg border px-3 py-2.5 text-left",
                  "transition-colors duration-fast ease-standard",
                  "focus-visible:shadow-focus focus-visible:outline-none",
                  selected
                    ? "bg-accent-indigo/10 border-accent-indigo"
                    : "border-transparent hover:bg-bg-surface-raised",
                )}
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="flex min-w-0 items-center gap-2">
                    <span
                      className={cn(
                        "flex h-7 w-7 flex-none items-center justify-center rounded-full bg-bg-surface",
                        channelMeta.colorClass,
                      )}
                      aria-hidden
                    >
                      <ChannelIcon className="h-4 w-4" />
                    </span>
                    <span className="truncate text-sm font-semibold text-text-primary">
                      {contact?.name ?? "Contacto desconocido"}
                    </span>
                    <span className="sr-only">
                      Canal: {channelMeta.label}. Sentimiento: {sentimentMeta.label}.
                    </span>
                  </div>
                  <span className="flex-none text-xs text-text-muted">
                    {formatDateTime(conversation.lastMessageAt)}
                  </span>
                </div>

                <p className="truncate text-sm text-text-secondary">
                  {conversation.lastMessage}
                </p>

                <div className="flex flex-wrap items-center gap-1.5">
                  <Badge variant={sentimentMeta.badgeVariant}>
                    {sentimentMeta.label}
                  </Badge>
                  <Badge variant="neutral">{conversation.status}</Badge>
                  {hasUnread && (
                    <span
                      className="ml-auto inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-accent-cyan px-1.5 text-xs font-semibold text-text-inverse"
                      aria-label={`${conversation.unreadCount} mensajes no leídos`}
                    >
                      {conversation.unreadCount}
                    </span>
                  )}
                </div>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
