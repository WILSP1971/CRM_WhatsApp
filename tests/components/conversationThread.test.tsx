import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { ConversationThread } from "@/components/inbox/ConversationThread";
import type { Contact, Conversation, ConversationMessage } from "@/lib/types";

/**
 * SPEC-090 — Render mínimo (headless, Q5=A) del adjunto de un DM de
 * Instagram (`message.mediaUrl`/`mediaType`, SPEC-088 RF-06): `<img>` directo
 * a la URL del CDN de Meta si es imagen, fallback de error de carga, o
 * enlace "Abrir adjunto" para otros tipos. El backend solo transporta la
 * cadena; el fetch real lo hace el navegador (no se testea red real aquí).
 */
describe("ConversationThread — adjunto de Instagram (SPEC-088/090)", () => {
  afterEach(() => cleanup());

  const contact: Contact = {
    id: "contact-1",
    name: "Laura Gómez",
    company: "—",
    email: "laura@example.com",
    phone: "—",
    avatarInitials: "LG",
    tags: [],
    sector: "comercial",
    lifetimeValue: 0,
    lastInteraction: "",
  };

  function buildConversation(message: ConversationMessage): Conversation {
    return {
      id: "conv-1",
      contactId: contact.id,
      channel: "instagram",
      sentiment: "neutral",
      lastMessage: message.text,
      lastMessageAt: message.sentAt,
      unreadCount: 0,
      status: "abierta",
      messages: [message],
    };
  }

  const baseMessage: ConversationMessage = {
    id: "m1",
    direction: "entrante",
    text: "",
    sentAt: "2026-10-04T10:00:00-05:00",
    status: "entregado",
  };

  it("renderiza un <img> apuntando directo a la URL del CDN cuando mediaType='image'", () => {
    const conversation = buildConversation({
      ...baseMessage,
      mediaUrl: "https://lookaside.fbsbx.com/ig_messaging_cdn/?asset_id=1&signature=abc",
      mediaType: "image",
    });

    render(
      <ConversationThread
        conversation={conversation}
        contact={contact}
        draftText=""
        onDraftChange={vi.fn()}
      />,
    );

    const img = screen.getByRole("img", { name: /adjunto de instagram/i });
    expect(img).toHaveAttribute(
      "src",
      "https://lookaside.fbsbx.com/ig_messaging_cdn/?asset_id=1&signature=abc",
    );
  });

  it("muestra el fallback 'Adjunto no disponible' cuando la imagen falla al cargar (URL expirada/revocada)", () => {
    const conversation = buildConversation({
      ...baseMessage,
      mediaUrl: "https://lookaside.fbsbx.com/ig_messaging_cdn/?asset_id=1&signature=abc",
      mediaType: "image",
    });

    render(
      <ConversationThread
        conversation={conversation}
        contact={contact}
        draftText=""
        onDraftChange={vi.fn()}
      />,
    );

    const img = screen.getByRole("img", { name: /adjunto de instagram/i });
    fireEvent.error(img);

    expect(screen.getByText(/adjunto no disponible/i)).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /adjunto de instagram/i })).not.toBeInTheDocument();
  });

  it("renderiza un enlace 'Abrir adjunto' para tipos distintos de 'image' (video/audio/file)", () => {
    const conversation = buildConversation({
      ...baseMessage,
      mediaUrl: "https://lookaside.fbsbx.com/ig_messaging_cdn/?asset_id=2&signature=xyz",
      mediaType: "video",
    });

    render(
      <ConversationThread
        conversation={conversation}
        contact={contact}
        draftText=""
        onDraftChange={vi.fn()}
      />,
    );

    const link = screen.getByRole("link", { name: /abrir adjunto/i });
    expect(link).toHaveAttribute(
      "href",
      "https://lookaside.fbsbx.com/ig_messaging_cdn/?asset_id=2&signature=xyz",
    );
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
  });

  it("no renderiza ningún adjunto cuando mediaUrl es null/undefined (mensaje de texto normal)", () => {
    const conversation = buildConversation({ ...baseMessage, text: "Hola, ¿cómo estás?" });

    render(
      <ConversationThread
        conversation={conversation}
        contact={contact}
        draftText=""
        onDraftChange={vi.fn()}
      />,
    );

    expect(screen.queryByRole("img", { name: /adjunto de instagram/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /abrir adjunto/i })).not.toBeInTheDocument();
    expect(screen.getByText("Hola, ¿cómo estás?")).toBeInTheDocument();
  });
});
