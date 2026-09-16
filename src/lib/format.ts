/** Formateadores compartidos (locale es-CO, sin dependencias externas). */

const timeFormatter = new Intl.DateTimeFormat("es-CO", {
  hour: "2-digit",
  minute: "2-digit",
});

const dateTimeFormatter = new Intl.DateTimeFormat("es-CO", {
  day: "2-digit",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});

const currencyFormatter = new Intl.NumberFormat("es-CO", {
  style: "currency",
  currency: "COP",
  maximumFractionDigits: 0,
});

/** Hora corta (HH:mm) para timestamps de mensajes. */
export function formatTime(isoDate: string): string {
  return timeFormatter.format(new Date(isoDate));
}

/** Fecha + hora corta para la lista de conversaciones. */
export function formatDateTime(isoDate: string): string {
  return dateTimeFormatter.format(new Date(isoDate));
}

/** Moneda COP para montos ficticios (LTV, precios de sugerencias). */
export function formatCurrency(value: number): string {
  return currencyFormatter.format(value);
}

/**
 * Duración mm:ss para llamadas/grabaciones del VoiceBot (SPEC-006).
 * Devuelve "—" cuando la duración es cero o negativa. Consolidada aquí
 * para eliminar las dos implementaciones divergentes previas en
 * CallHistory.tsx y RecordingControls.tsx (hallazgo WOLVERINE).
 */
export function formatDuration(totalSeconds: number): string {
  if (totalSeconds <= 0) return "—";
  const minutes = Math.floor(totalSeconds / 60)
    .toString()
    .padStart(2, "0");
  const seconds = Math.floor(totalSeconds % 60)
    .toString()
    .padStart(2, "0");
  return `${minutes}:${seconds}`;
}
