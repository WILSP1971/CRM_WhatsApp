"""Cálculo de Word Error Rate (WER) para transcripciones STT — SPEC-042.

WER es la métrica estándar de calidad de un sistema de reconocimiento de voz:
compara una transcripción HIPÓTESIS (la que produjo el modelo) contra una
transcripción de REFERENCIA ("ground truth", normalmente hecha por un humano)
y cuenta ediciones a nivel de PALABRA (sustituciones + inserciones + borrados)
sobre el total de palabras de la referencia:

    WER = (S + I + D) / N_palabras_referencia

Implementación: distancia de Levenshtein clásica a nivel de palabra
(programación dinámica O(n*m)), sin dependencias externas (no se añade
`jiwer`/`python-Levenshtein` — no están instalados en este entorno y el
algoritmo es standard/corto de implementar y probar directamente).

Uso previsto:
  - `compute_wer`: la función pura, testeable con texto conocido
    (`tests/test_stt_wer.py`) — es lo que SÍ se puede verificar en este
    sandbox sin GPU/modelo real.
  - Poblar `call_transcripts.wer` (columna ya existente, SPEC-036) es
    responsabilidad de quien tenga un PAR (hipótesis del modelo real,
    referencia humana) — fuera del alcance de SPEC-042 en este sandbox por
    no haber habla real disponible (ver
    `tests/fixtures_audio/synthetic_call_audio.py` y el reporte de HAWKEYE
    para el detalle de esta limitación). El `stt_worker` (SPEC-038) NO llama
    a esta función en el camino de producción — no existe hoy un flujo que
    aporte una referencia humana automáticamente; queda como utilidad lista
    para el proceso de evaluación offline documentado en el runbook
    (SPEC-043) cuando exista un corpus real es-CO con transcripción de
    referencia.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_WORD_SPLIT_RE = re.compile(r"\s+")


def _normalize_and_tokenize(text: str) -> list[str]:
    """Normalización mínima antes de tokenizar por palabra: minúsculas y
    colapso de espacios múltiples. NO elimina puntuación agresivamente (una
    decisión de WER "raw" vs "normalizado" es del dominio de negocio; aquí se
    documenta la normalización aplicada para que el número sea reproducible)."""
    return [tok for tok in _WORD_SPLIT_RE.split(text.strip().lower()) if tok]


@dataclass(frozen=True)
class WerResult:
    wer: float
    substitutions: int
    insertions: int
    deletions: int
    reference_word_count: int

    @property
    def matches(self) -> int:
        return self.reference_word_count - self.substitutions - self.deletions


def compute_wer(reference: str, hypothesis: str) -> WerResult:
    """Calcula el WER de `hypothesis` contra `reference` (distancia de
    Levenshtein a nivel de palabra, con retropropagación del tipo de edición).

    Caso borde: referencia vacía.
      - Si la hipótesis también está vacía -> WER 0.0 (coinciden, nada que
        editar).
      - Si la hipótesis NO está vacía -> WER 1.0 (todo el contenido de la
        hipótesis son inserciones sobre una referencia vacía; se acota a 1.0
        en vez de dejar crecer sin límite, mismo criterio que la mayoría de
        implementaciones de referencia como `jiwer` para este caso
        degenerado)."""
    ref_words = _normalize_and_tokenize(reference)
    hyp_words = _normalize_and_tokenize(hypothesis)

    n = len(ref_words)
    m = len(hyp_words)

    if n == 0:
        return WerResult(
            wer=0.0 if m == 0 else 1.0,
            substitutions=0,
            insertions=m,
            deletions=0,
            reference_word_count=0,
        )

    # dp[i][j] = costo mínimo de edición para transformar ref[:i] en hyp[:j].
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dp[i][0] = i  # borrar las i primeras palabras de la referencia
    for j in range(m + 1):
        dp[0][j] = j  # insertar las j primeras palabras de la hipótesis

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if ref_words[i - 1] == hyp_words[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = 1 + min(
                    dp[i - 1][j],  # borrado
                    dp[i][j - 1],  # inserción
                    dp[i - 1][j - 1],  # sustitución
                )

    # Retropropagación para desglosar el costo total en S/I/D (útil para
    # depuración/reporte, no solo el número agregado).
    i, j = n, m
    substitutions = insertions = deletions = 0
    while i > 0 or j > 0:
        if i > 0 and j > 0 and ref_words[i - 1] == hyp_words[j - 1]:
            i -= 1
            j -= 1
            continue
        if i > 0 and j > 0 and dp[i][j] == dp[i - 1][j - 1] + 1:
            substitutions += 1
            i -= 1
            j -= 1
        elif j > 0 and dp[i][j] == dp[i][j - 1] + 1:
            insertions += 1
            j -= 1
        else:
            deletions += 1
            i -= 1

    total_edits = substitutions + insertions + deletions
    wer = total_edits / n

    return WerResult(
        wer=wer,
        substitutions=substitutions,
        insertions=insertions,
        deletions=deletions,
        reference_word_count=n,
    )
