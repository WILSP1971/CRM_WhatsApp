import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { RagDraftCard } from "@/components/rag/RagDraftCard";
import type { RagDraft } from "@/lib/types";

/**
 * SPEC-070 — Criterios de aceptación de la tarjeta de borrador extendida
 * con la UX de audio (opt-in RF-01, "escuchar antes de enviar" RF-02,
 * estados AAA RF-03, disclaimer firme RF-04, feature-flag RF-05, error con
 * reintentar/caer a texto RF-06).
 */
describe("RagDraftCard — flujo de texto (flag OFF / useRealApi=false)", () => {
  afterEach(() => cleanup());

  const draft: RagDraft = {
    id: "draft-1",
    conversationId: "conv-1",
    text: "Respuesta sugerida de prueba",
    generatedAt: "2026-09-20T10:00:00-05:00",
  };

  it("no muestra NINGÚN control de audio cuando useRealApi=false (RF-05/RNF-FLAG)", () => {
    render(
      <RagDraftCard draft={draft} loading={false} onUseDraft={vi.fn()} useRealApi={false} />,
    );

    expect(screen.getByText(/Respuesta sugerida de prueba/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Usar borrador/i })).toBeInTheDocument();
    expect(screen.queryByLabelText(/Responder con audio/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Escuchar antes de enviar/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Aprobar y enviar/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/respuesta de voz asistida/i)).not.toBeInTheDocument();
  });

  it("el flujo 'Usar borrador' sigue intacto (comportamiento actual)", () => {
    const onUseDraft = vi.fn();
    render(<RagDraftCard draft={draft} loading={false} onUseDraft={onUseDraft} />);

    fireEvent.click(screen.getByRole("button", { name: /Usar borrador/i }));
    expect(onUseDraft).toHaveBeenCalledWith("Respuesta sugerida de prueba");
  });
});

describe("RagDraftCard — flujo de audio (flag ON / useRealApi=true)", () => {
  afterEach(() => cleanup());

  const baseDraft: RagDraft = {
    id: "draft-1",
    conversationId: "conv-1",
    text: "Respuesta sugerida de prueba",
    generatedAt: "2026-09-20T10:00:00-05:00",
    respuestaModo: "texto",
    ttsEstado: "no_solicitado",
    audioListo: false,
  };

  it("por defecto (respuesta_modo='texto') NO muestra el disclaimer ni el reproductor (RF-01 opt-in)", () => {
    render(<RagDraftCard draft={baseDraft} loading={false} onUseDraft={vi.fn()} useRealApi />);

    expect(screen.getByLabelText(/Responder con audio/i)).not.toBeChecked();
    expect(screen.queryByText(/respuesta de voz asistida/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Escuchar antes de enviar/i })).not.toBeInTheDocument();
  });

  it("invoca onSetRespuestaModo('audio') al activar el toggle opt-in", () => {
    const onSetRespuestaModo = vi.fn();
    render(
      <RagDraftCard
        draft={baseDraft}
        loading={false}
        onUseDraft={vi.fn()}
        useRealApi
        onSetRespuestaModo={onSetRespuestaModo}
      />,
    );

    fireEvent.click(screen.getByLabelText(/Responder con audio/i));
    expect(onSetRespuestaModo).toHaveBeenCalledWith("audio");
  });

  it("muestra SIEMPRE el disclaimer de voz sintética cuando respuesta_modo='audio' (RF-04, firme)", () => {
    render(
      <RagDraftCard
        draft={{ ...baseDraft, respuestaModo: "audio" }}
        loading={false}
        onUseDraft={vi.fn()}
        useRealApi
      />,
    );

    expect(screen.getByText(/respuesta de voz asistida/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Escuchar antes de enviar/i })).toBeInTheDocument();
  });

  it("invoca onRequestListen al pulsar 'Escuchar antes de enviar'", () => {
    const onRequestListen = vi.fn();
    render(
      <RagDraftCard
        draft={{ ...baseDraft, respuestaModo: "audio" }}
        loading={false}
        onUseDraft={vi.fn()}
        useRealApi
        onRequestListen={onRequestListen}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Escuchar antes de enviar/i }));
    expect(onRequestListen).toHaveBeenCalledTimes(1);
  });

  it("estado 'generando': anuncia por aria-live y deshabilita el botón de escuchar", () => {
    render(
      <RagDraftCard
        draft={{ ...baseDraft, respuestaModo: "audio", ttsEstado: "generando" }}
        loading={false}
        onUseDraft={vi.fn()}
        useRealApi
        requestingAudio
      />,
    );

    expect(screen.getByRole("button", { name: /Generando audio/i })).toBeDisabled();
    expect(
      screen.getByText(/Generando el clip de audio de la respuesta/i),
    ).toBeInTheDocument();
  });

  it("estado 'listo': muestra el reproductor <audio controls> apuntando a audioUrl", () => {
    render(
      <RagDraftCard
        draft={{ ...baseDraft, respuestaModo: "audio", ttsEstado: "listo", audioListo: true }}
        loading={false}
        onUseDraft={vi.fn()}
        useRealApi
        audioUrl="blob:mock-audio-url"
      />,
    );

    const audioEl = document.querySelector("audio");
    expect(audioEl).toBeInTheDocument();
    expect(audioEl).toHaveAttribute("controls");
    expect(document.querySelector("audio source")).toHaveAttribute(
      "src",
      "blob:mock-audio-url",
    );
    expect(screen.getByText("Audio listo")).toBeInTheDocument();
  });

  it("estado 'error': ofrece reintentar y caer a texto sin bloquear al agente (RF-06)", () => {
    const onRequestListen = vi.fn();
    const onSetRespuestaModo = vi.fn();
    render(
      <RagDraftCard
        draft={{ ...baseDraft, respuestaModo: "audio", ttsEstado: "error" }}
        loading={false}
        onUseDraft={vi.fn()}
        useRealApi
        audioError="No se pudo generar el clip de audio. Puedes reintentar o responder con texto."
        onRequestListen={onRequestListen}
        onSetRespuestaModo={onSetRespuestaModo}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent(/No se pudo generar el clip/i);

    fireEvent.click(screen.getByRole("button", { name: /^Reintentar$/i }));
    expect(onRequestListen).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: /Responder con texto/i }));
    expect(onSetRespuestaModo).toHaveBeenCalledWith("texto");
  });

  it("el botón 'Aprobar y enviar' NO se deshabilita por no haber escuchado el clip (RNF-HITL: aprobar sin escuchar sigue siendo válido)", () => {
    render(
      <RagDraftCard
        draft={{ ...baseDraft, respuestaModo: "audio", ttsEstado: "no_solicitado" }}
        loading={false}
        onUseDraft={vi.fn()}
        useRealApi
      />,
    );

    expect(screen.getByRole("button", { name: /Aprobar y enviar/i })).toBeEnabled();
  });

  it("invoca onApprove al pulsar 'Aprobar y enviar'", () => {
    const onApprove = vi.fn();
    render(
      <RagDraftCard
        draft={baseDraft}
        loading={false}
        onUseDraft={vi.fn()}
        useRealApi
        onApprove={onApprove}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Aprobar y enviar/i }));
    expect(onApprove).toHaveBeenCalledTimes(1);
  });
});
