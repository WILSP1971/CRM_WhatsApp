# Tabla de resultados consolidada — SPEC-067 (THOR)

Modo 'warm': modelo cargado UNA VEZ (representativo de un worker persistente), 5 repeticiones por guion, incluye transcodificacion a OGG/Opus con ffmpeg 7.0.2 estatico.

| Motor | Voz | Guion | Categoria | Chars | Synth media (s) | E2E media (s) | E2E p95 (s) | Cumple <=5s | Cumple <=10s |
|---|---|---|---|---|---|---|---|---|---|
| piper | es_MX-ald-medium | corta_01 | corta | 61 | 0.839 | 1.242 | 1.932 | si | si |
| piper | es_MX-ald-medium | corta_02 | corta | 37 | 0.389 | 0.669 | 0.718 | si | si |
| piper | es_MX-ald-medium | corta_03 | corta | 53 | 0.505 | 0.831 | 0.978 | si | si |
| piper | es_MX-ald-medium | media_01 | media | 188 | 1.787 | 2.617 | 3.148 | si | si |
| piper | es_MX-ald-medium | media_02 | media | 195 | 2.149 | 3.248 | 3.586 | si | si |
| piper | es_MX-ald-medium | media_03 | media | 205 | 1.927 | 3.055 | 3.347 | si | si |
| piper | es_MX-ald-medium | larga_01 | larga | 656 | 6.402 | 9.403 | 10.137 | NO | NO |
| piper | es_MX-ald-medium | larga_02 | larga | 612 | 5.639 | 8.567 | 9.629 | NO | si |
| piper | es_MX-claude-high | corta_01 | corta | 61 | 0.437 | 0.77 | 0.864 | si | si |
| piper | es_MX-claude-high | corta_02 | corta | 37 | 0.359 | 0.574 | 0.637 | si | si |
| piper | es_MX-claude-high | corta_03 | corta | 53 | 0.56 | 1.241 | 1.322 | si | si |
| piper | es_MX-claude-high | media_01 | media | 188 | 2.536 | 4.558 | 5.588 | NO | si |
| piper | es_MX-claude-high | media_02 | media | 195 | 2.106 | 3.32 | 4.49 | si | si |
| piper | es_MX-claude-high | media_03 | media | 205 | 1.725 | 3.229 | 3.784 | si | si |
| piper | es_MX-claude-high | larga_01 | larga | 656 | 5.923 | 9.043 | 10.721 | NO | NO |
| piper | es_MX-claude-high | larga_02 | larga | 612 | 5.255 | 8.519 | 10.108 | NO | NO |
| piper | es_AR-daniela-high | corta_01 | corta | 61 | 1.713 | 2.119 | 2.921 | si | si |
| piper | es_AR-daniela-high | corta_02 | corta | 37 | 0.992 | 1.252 | 1.431 | si | si |
| piper | es_AR-daniela-high | corta_03 | corta | 53 | 1.853 | 2.068 | 2.623 | si | si |
| piper | es_AR-daniela-high | media_01 | media | 188 | 4.848 | 5.721 | 6.765 | NO | si |
| piper | es_AR-daniela-high | media_02 | media | 195 | 5.165 | 5.938 | 6.331 | NO | si |
| piper | es_AR-daniela-high | media_03 | media | 205 | 5.669 | 6.4 | 6.974 | NO | si |
| piper | es_AR-daniela-high | larga_01 | larga | 656 | 15.366 | 17.735 | 18.288 | NO | NO |
| piper | es_AR-daniela-high | larga_02 | larga | 612 | 15.671 | 18.512 | 20.287 | NO | NO |
| piper | es_ES-davefx-medium | corta_01 | corta | 61 | 0.433 | 0.68 | 0.801 | si | si |
| piper | es_ES-davefx-medium | corta_02 | corta | 37 | 0.274 | 0.446 | 0.524 | si | si |
| piper | es_ES-davefx-medium | corta_03 | corta | 53 | 0.345 | 0.691 | 0.727 | si | si |
| piper | es_ES-davefx-medium | media_01 | media | 188 | 1.182 | 1.882 | 2.017 | si | si |
| piper | es_ES-davefx-medium | media_02 | media | 195 | 1.196 | 1.63 | 1.692 | si | si |
| piper | es_ES-davefx-medium | media_03 | media | 205 | 1.59 | 2.518 | 2.809 | si | si |
| piper | es_ES-davefx-medium | larga_01 | larga | 656 | 3.648 | 6.773 | 7.19 | NO | si |
| piper | es_ES-davefx-medium | larga_02 | larga | 612 | 3.406 | 5.713 | 6.246 | NO | si |
| coqui (es/css10/vits) | css10-vits-default | corta_01 | corta | 61 | 1.189 | 1.547 | 2.265 | si | si |
| coqui (es/css10/vits) | css10-vits-default | corta_02 | corta | 37 | 0.579 | 0.828 | 1.019 | si | si |
| coqui (es/css10/vits) | css10-vits-default | corta_03 | corta | 53 | 0.662 | 0.985 | 1.076 | si | si |
| coqui (es/css10/vits) | css10-vits-default | media_01 | media | 188 | 2.53 | 3.435 | 3.67 | si | si |
| coqui (es/css10/vits) | css10-vits-default | media_02 | media | 195 | 2.45 | 3.405 | 3.643 | si | si |
| coqui (es/css10/vits) | css10-vits-default | media_03 | media | 205 | 2.482 | 3.52 | 3.845 | si | si |
| coqui (es/css10/vits) | css10-vits-default | larga_01 | larga | 656 | 7.348 | 10.909 | 11.98 | NO | NO |
| coqui (es/css10/vits) | css10-vits-default | larga_02 | larga | 612 | 7.597 | 9.822 | 15.239 | NO | NO |
