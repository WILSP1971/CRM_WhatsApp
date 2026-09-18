"""Chunking configurable de texto para el pipeline RAG — SPEC-017.

Divide un texto largo en fragmentos ("chunks") de tamaño acotado con
solapamiento configurable, para mejorar la recuperación semántica sin perder
contexto en los bordes de cada fragmento. Puramente determinista y sin I/O
(no depende de Postgres/Redis/AIClient) para facilitar pruebas unitarias.
"""

from __future__ import annotations

from dataclasses import dataclass

# Valores por defecto razonables para nomic-embed-text (ventana de contexto
# amplia, pero se acota para mantener chunks temáticamente coherentes y la
# latencia de embeddings/recuperación bajo control, RNF-04).
DEFAULT_CHUNK_SIZE = 1000
DEFAULT_CHUNK_OVERLAP = 150


class ChunkingConfigError(ValueError):
    """Configuración de chunking inválida (tamaño/solape incoherentes)."""


@dataclass(frozen=True)
class TextChunk:
    """Un fragmento de texto ya recortado, con su orden dentro del documento."""

    orden: int
    contenido: str


def _validar_config(chunk_size: int, chunk_overlap: int) -> None:
    if chunk_size <= 0:
        raise ChunkingConfigError("chunk_size debe ser > 0")
    if chunk_overlap < 0:
        raise ChunkingConfigError("chunk_overlap no puede ser negativo")
    if chunk_overlap >= chunk_size:
        raise ChunkingConfigError("chunk_overlap debe ser menor que chunk_size")


def split_into_chunks(
    text: str,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[TextChunk]:
    """Divide `text` en fragmentos de hasta `chunk_size` caracteres, con
    `chunk_overlap` caracteres de solape entre fragmentos consecutivos.

    - Normaliza espacios en blanco redundantes para no generar chunks vacíos.
    - Si el texto ya cabe en un solo chunk, devuelve un único `TextChunk`.
    - Determinista: mismo texto + misma config -> mismos chunks (idempotente,
      requisito para reintentos de ingesta, R-28).
    """
    _validar_config(chunk_size, chunk_overlap)

    normalized = " ".join(text.split()).strip()
    if not normalized:
        return []

    if len(normalized) <= chunk_size:
        return [TextChunk(orden=0, contenido=normalized)]

    step = chunk_size - chunk_overlap
    chunks: list[TextChunk] = []
    start = 0
    orden = 0
    length = len(normalized)
    while start < length:
        end = min(start + chunk_size, length)
        fragment = normalized[start:end].strip()
        if fragment:
            chunks.append(TextChunk(orden=orden, contenido=fragment))
            orden += 1
        if end >= length:
            break
        start += step
    return chunks
