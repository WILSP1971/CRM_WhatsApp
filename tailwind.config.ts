import type { Config } from "tailwindcss";

/**
 * Tailwind config — OmniCore AI.
 * Todos los colores/radios/sombras/fuentes se resuelven contra las CSS
 * variables definidas en src/styles/tokens.css (RNF-04: cero hardcode).
 */
const config: Config = {
  darkMode: ["class", '[data-theme="dark"]'],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        "bg-canvas": "var(--color-bg-canvas)",
        "bg-surface": "var(--color-bg-surface)",
        "bg-surface-raised": "var(--color-bg-surface-raised)",
        "bg-card": "var(--color-bg-card)",

        "border-subtle": "var(--color-border-subtle)",
        "border-default": "var(--color-border-default)",

        "text-primary": "var(--color-text-primary)",
        "text-secondary": "var(--color-text-secondary)",
        "text-muted": "var(--color-text-muted)",
        "text-inverse": "var(--color-text-inverse)",

        "accent-indigo": "var(--color-accent-indigo)",
        "accent-indigo-strong": "var(--color-accent-indigo-strong)",
        "accent-cyan": "var(--color-accent-cyan)",
        "accent-cyan-strong": "var(--color-accent-cyan-strong)",

        "state-success": "var(--color-state-success)",
        "state-success-strong": "var(--color-state-success-strong)",
        "state-warning": "var(--color-state-warning)",
        "state-warning-strong": "var(--color-state-warning-strong)",
        "state-danger": "var(--color-state-danger)",
        "state-danger-strong": "var(--color-state-danger-strong)",

        "badge-success-text": "var(--color-badge-success-text)",
        "badge-warning-text": "var(--color-badge-warning-text)",
        "badge-danger-text": "var(--color-badge-danger-text)",
        "badge-ai-text": "var(--color-badge-ai-text)",

        "chart-indigo": "var(--color-chart-indigo)",
        "chart-cyan": "var(--color-chart-cyan)",
        "chart-warning": "var(--color-chart-warning)",
        "chart-success": "var(--color-chart-success)",
        "chart-danger": "var(--color-chart-danger)",
        "chart-muted": "var(--color-chart-muted)",

        "focus-ring": "var(--color-focus-ring)",
      },
      fontFamily: {
        sans: ["var(--font-family-sans)"],
      },
      fontSize: {
        xs: "var(--font-size-xs)",
        sm: "var(--font-size-sm)",
        base: "var(--font-size-base)",
        md: "var(--font-size-md)",
        lg: "var(--font-size-lg)",
        xl: "var(--font-size-xl)",
        "2xl": "var(--font-size-2xl)",
        "3xl": "var(--font-size-3xl)",
      },
      spacing: {
        0: "var(--space-0)",
        1: "var(--space-1)",
        2: "var(--space-2)",
        3: "var(--space-3)",
        4: "var(--space-4)",
        5: "var(--space-5)",
        6: "var(--space-6)",
        8: "var(--space-8)",
        10: "var(--space-10)",
        12: "var(--space-12)",
        16: "var(--space-16)",
      },
      borderRadius: {
        sm: "var(--radius-sm)",
        md: "var(--radius-md)",
        lg: "var(--radius-lg)",
        xl: "var(--radius-xl)",
        full: "var(--radius-full)",
      },
      boxShadow: {
        sm: "var(--shadow-sm)",
        md: "var(--shadow-md)",
        lg: "var(--shadow-lg)",
        focus: "var(--shadow-focus)",
      },
      backdropBlur: {
        glass: "var(--blur-glass)",
      },
      transitionDuration: {
        fast: "var(--duration-fast)",
        base: "var(--duration-base)",
        slow: "var(--duration-slow)",
      },
      transitionTimingFunction: {
        standard: "var(--ease-standard)",
      },
      zIndex: {
        header: "var(--z-header)",
        sidebar: "var(--z-sidebar)",
        overlay: "var(--z-overlay)",
        tooltip: "var(--z-tooltip)",
      },
    },
  },
  plugins: [],
};

export default config;
