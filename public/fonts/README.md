# Fuente Inter self-hosted

Este proyecto es **SENSIBLE** (`.no-externo`): tiene prohibido cargar fuentes desde
Google Fonts o cualquier CDN externo. La tipografía **Inter** (licencia SIL Open Font
License 1.1, gratuita y redistribuible) debe alojarse localmente aquí, en
`public/fonts/`.

Mientras estos archivos no existan, la aplicación sigue funcionando correctamente:
`src/styles/fonts.css` declara los `@font-face` apuntando a estos archivos, pero el
`font-family` en los tokens (`src/styles/tokens.css`) siempre incluye un fallback
(`system-ui`, `-apple-system`, `Segoe UI`, `Roboto`, etc.), por lo que el texto se ve
con una tipografía del sistema hasta que se agreguen los woff2 reales.

## Cómo añadir los archivos (una sola vez, en un entorno con acceso controlado)

1. Descarga el paquete oficial de Inter (OFL) desde el repositorio del proyecto
   (https://github.com/rsms/inter, releases) en una máquina con acceso a internet
   autorizada — **no** desde este entorno SENSIBLE.
2. Convierte/extrae los siguientes pesos a `.woff2` (basta con Regular/400,
   Medium/500, SemiBold/600 y Bold/700, que son los usados por los tokens):
   - `Inter-Regular.woff2`
   - `Inter-Medium.woff2`
   - `Inter-SemiBold.woff2`
   - `Inter-Bold.woff2`
3. Copia esos 4 archivos a esta carpeta (`public/fonts/`). No subas otros pesos para
   mantener el bundle liviano (RNF-02, performance).
4. Verifica con `npm run check:externos` que sigue en verde (los archivos locales no
   cuentan como "externos"; solo se bloquean URLs `http(s)` remotas).
5. Verifica en DevTools → Network que la fuente se sirve desde `localhost` (o rutas
   relativas), nunca desde `fonts.googleapis.com`, `fonts.gstatic.com` ni ningún otro
   dominio de terceros.

## Licencia

Inter se distribuye bajo la SIL Open Font License 1.1, que permite el uso, copia y
redistribución embebida en productos. Conserva el archivo de licencia (`LICENSE.txt`)
junto a los woff2 si lo agregas, para trazabilidad.
