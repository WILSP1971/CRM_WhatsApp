import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import path from "node:path";

/**
 * SPEC-009 — Test de contraste WCAG de los design tokens (SPEC-002).
 *
 * Lee src/styles/tokens.css como fuente única de verdad (no duplica valores
 * a mano) y calcula el ratio de contraste real (fórmula WCAG 2.x de
 * luminancia relativa) entre los pares texto/fondo usados como texto normal
 * en la app. Falla si algún par por debajo del umbral AAA (7:1) está en uso
 * real como texto de cuerpo (ver anotación `aaaRequired`).
 */

function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace("#", "");
  const n = parseInt(h, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function relLum([r, g, b]: [number, number, number]): number {
  const [rs, gs, bs] = [r, g, b].map((c) => {
    const cs = c / 255;
    return cs <= 0.03928 ? cs / 12.92 : Math.pow((cs + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * rs + 0.7152 * gs + 0.0722 * bs;
}

export function contrastRatio(hex1: string, hex2: string): number {
  const l1 = relLum(hexToRgb(hex1));
  const l2 = relLum(hexToRgb(hex2));
  const [lighter, darker] = l1 > l2 ? [l1, l2] : [l2, l1];
  return (lighter + 0.05) / (darker + 0.05);
}

function extractTokens(css: string, scopeSelector: RegExp): Record<string, string> {
  const scopeMatch = css.match(scopeSelector);
  if (!scopeMatch) throw new Error(`No se encontró el bloque ${scopeSelector}`);
  const block = scopeMatch[1];
  const tokens: Record<string, string> = {};
  const re = /--([\w-]+):\s*(#[0-9a-fA-F]{6})\s*;/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(block))) {
    tokens[m[1]] = m[2];
  }
  return tokens;
}

const tokensPath = path.resolve(__dirname, "../src/styles/tokens.css");
const css = readFileSync(tokensPath, "utf-8");

// Bloque :root (tema oscuro, por defecto)
const darkTokens = extractTokens(css, /:root\s*\{([\s\S]*?)\n\}/);
// Bloque :root[data-theme="light"]
const lightTokens = extractTokens(css, /:root\[data-theme="light"\]\s*\{([\s\S]*?)\n\}/);

const AAA_NORMAL_TEXT = 7;

// Pares texto/fondo verificados: SOLO combinaciones confirmadas en uso real
// como texto normal en componentes (ver grep de clases Tailwind `text-*`).
const textPairs: Array<{ label: string; fg: string; bg: string; aaaRequired: boolean }> = [
  { label: "text-primary / bg-canvas", fg: "color-text-primary", bg: "color-bg-canvas", aaaRequired: true },
  { label: "text-primary / bg-surface", fg: "color-text-primary", bg: "color-bg-surface", aaaRequired: true },
  { label: "text-primary / bg-card", fg: "color-text-primary", bg: "color-bg-card", aaaRequired: true },
  { label: "text-secondary / bg-canvas", fg: "color-text-secondary", bg: "color-bg-canvas", aaaRequired: true },
  { label: "text-secondary / bg-card", fg: "color-text-secondary", bg: "color-bg-card", aaaRequired: true },
  // text-muted se usa extensamente como texto de cuerpo (12-14px) en las
  // 6 páginas (ConversationList, RagCitationList, tablas de Analytics, etc.)
  // -> requiere AAA. Ver hallazgo HAWKEYE SPEC-009.
  { label: "text-muted / bg-canvas", fg: "color-text-muted", bg: "color-bg-canvas", aaaRequired: true },
  { label: "text-muted / bg-card", fg: "color-text-muted", bg: "color-bg-card", aaaRequired: true },
  // Variantes -strong de estado: usadas como texto real en Badge.tsx y
  // KpiCard.tsx, siempre sobre bg-card (fondo real de esos componentes).
  { label: "success-strong / bg-card", fg: "color-state-success-strong", bg: "color-bg-card", aaaRequired: true },
  { label: "warning-strong / bg-card", fg: "color-state-warning-strong", bg: "color-bg-card", aaaRequired: true },
  { label: "danger-strong / bg-card", fg: "color-state-danger-strong", bg: "color-bg-card", aaaRequired: true },
  { label: "accent-indigo-strong / bg-canvas", fg: "color-accent-indigo-strong", bg: "color-bg-canvas", aaaRequired: true },
  { label: "accent-cyan-strong / bg-canvas", fg: "color-accent-cyan-strong", bg: "color-bg-canvas", aaaRequired: true },
];

describe.each([
  ["oscuro", darkTokens],
  ["claro", lightTokens],
])("Contraste WCAG AAA — tema %s", (_themeName, tokens) => {
  for (const { label, fg, bg, aaaRequired } of textPairs) {
    it(`${label} >= 7:1 (AAA)`, () => {
      const fgHex = tokens[fg];
      const bgHex = tokens[bg];
      expect(fgHex, `token --${fg} no encontrado`).toBeDefined();
      expect(bgHex, `token --${bg} no encontrado`).toBeDefined();
      const ratio = contrastRatio(fgHex, bgHex);
      if (aaaRequired) {
        expect(ratio, `${label}: ${fgHex} on ${bgHex} = ${ratio.toFixed(2)}:1`).toBeGreaterThanOrEqual(
          AAA_NORMAL_TEXT,
        );
      }
    });
  }
});
