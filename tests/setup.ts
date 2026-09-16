import "@testing-library/jest-dom/vitest";

// jsdom no implementa matchMedia; varios componentes (tema, animaciones)
// pueden consultarlo. Se mockea para que los smoke tests no truenen.
if (!window.matchMedia) {
  window.matchMedia = (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }) as unknown as MediaQueryList;
}

// jsdom no implementa ResizeObserver (usado por Radix/Recharts).
class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}
// @ts-expect-error -- polyfill mínimo para entorno de test
window.ResizeObserver = window.ResizeObserver || ResizeObserverMock;

// jsdom no implementa Element.prototype.scrollTo (usado por autoscroll de
// ConversationThread y LiveTranscript). Es una limitación conocida del
// entorno de test (no un bug de la app: en un navegador real existe).
if (!Element.prototype.scrollTo) {
  Element.prototype.scrollTo = function scrollTo() {};
}
