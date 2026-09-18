import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * SPEC-020 — Cliente WebSocket del WebChat real (SPEC-015). `WebSocket`
 * MOCKEADO (no requiere backend vivo): verifica URL/handshake con token,
 * envío de mensajes/read receipts y despacho de eventos entrantes.
 */
class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  url: string;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onclose: ((event: unknown) => void) | null = null;
  onerror: ((event: unknown) => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  closed = false;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  send(data: string) {
    this.sent.push(data);
  }

  close() {
    this.closed = true;
  }

  emitMessage(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) });
  }
}

describe("connectWebChat", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.stubEnv("VITE_WS_BASE_URL", "ws://localhost:9999/api/v1");
    FakeWebSocket.instances = [];
    // @ts-expect-error -- sustituye WebSocket global por el fake en el test
    global.WebSocket = FakeWebSocket;
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("abre el socket con la URL/base configurable y el token en query param", async () => {
    const { setAuthToken } = await import("@/lib/authStore");
    setAuthToken("jwt-abc");
    const { connectWebChat } = await import("@/lib/api/wsClient");

    connectWebChat("conv-123", { onEvent: () => {} });

    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(FakeWebSocket.instances[0].url).toBe(
      "ws://localhost:9999/api/v1/ws/chat/conv-123?token=jwt-abc",
    );
  });

  it("sendMessage/sendReadReceipt envían el protocolo JSON esperado", async () => {
    const { connectWebChat } = await import("@/lib/api/wsClient");
    const handle = connectWebChat("conv-123", { onEvent: () => {} });

    handle.sendMessage("agente", "Hola desde el agente");
    handle.sendReadReceipt("msg-1");

    const socket = FakeWebSocket.instances[0];
    expect(JSON.parse(socket.sent[0])).toEqual({
      type: "message",
      remitente: "agente",
      contenido: "Hola desde el agente",
    });
    expect(JSON.parse(socket.sent[1])).toEqual({ type: "read", message_id: "msg-1" });
  });

  it("despacha eventos entrantes parseados a onEvent", async () => {
    const { connectWebChat } = await import("@/lib/api/wsClient");
    const onEvent = vi.fn();
    connectWebChat("conv-123", { onEvent });

    const socket = FakeWebSocket.instances[0];
    socket.emitMessage({ type: "message", message: { id: "m1", contenido: "hola" } });

    expect(onEvent).toHaveBeenCalledWith({
      type: "message",
      message: { id: "m1", contenido: "hola" },
    });
  });

  it("close() cierra el WebSocket subyacente", async () => {
    const { connectWebChat } = await import("@/lib/api/wsClient");
    const handle = connectWebChat("conv-123", { onEvent: () => {} });
    handle.close();
    expect(FakeWebSocket.instances[0].closed).toBe(true);
  });
});
