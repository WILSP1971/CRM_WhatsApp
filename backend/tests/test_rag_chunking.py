"""Tests unitarios de `app.services.rag.chunking` — SPEC-017.

Puramente unitarios (sin BD/Redis/AIClient): validan el chunking configurable
(tamaño/solape) y su determinismo (requisito de idempotencia en reintentos,
R-28).
"""

from __future__ import annotations

import pytest

from app.services.rag.chunking import (
    ChunkingConfigError,
    split_into_chunks,
)


def test_texto_corto_produce_un_unico_chunk():
    chunks = split_into_chunks("hola mundo", chunk_size=1000, chunk_overlap=100)

    assert len(chunks) == 1
    assert chunks[0].orden == 0
    assert chunks[0].contenido == "hola mundo"


def test_texto_vacio_produce_cero_chunks():
    assert split_into_chunks("   ", chunk_size=100, chunk_overlap=10) == []
    assert split_into_chunks("", chunk_size=100, chunk_overlap=10) == []


def test_texto_largo_se_divide_en_varios_chunks_ordenados():
    text = "palabra " * 500  # texto largo determinista
    chunks = split_into_chunks(text, chunk_size=200, chunk_overlap=20)

    assert len(chunks) > 1
    ordenes = [c.orden for c in chunks]
    assert ordenes == list(range(len(chunks)))
    for chunk in chunks:
        assert len(chunk.contenido) <= 200


def test_chunking_es_determinista_mismo_texto_misma_config():
    text = "El gato subió al tejado. " * 100
    chunks_1 = split_into_chunks(text, chunk_size=150, chunk_overlap=30)
    chunks_2 = split_into_chunks(text, chunk_size=150, chunk_overlap=30)

    assert [c.contenido for c in chunks_1] == [c.contenido for c in chunks_2]
    assert [c.orden for c in chunks_1] == [c.orden for c in chunks_2]


def test_solape_hace_que_chunks_consecutivos_compartan_texto():
    text = "abcdefghij" * 30
    chunks = split_into_chunks(text, chunk_size=50, chunk_overlap=10)

    assert len(chunks) > 1
    # El final del primer chunk debe reaparecer al inicio del segundo
    # (dentro de la ventana de solape configurada).
    overlap_tail = chunks[0].contenido[-10:]
    assert overlap_tail in chunks[1].contenido


@pytest.mark.parametrize(
    "chunk_size,chunk_overlap",
    [(0, 0), (-10, 0), (100, -1), (100, 100), (100, 150)],
)
def test_config_invalida_lanza_error(chunk_size, chunk_overlap):
    with pytest.raises(ChunkingConfigError):
        split_into_chunks("texto", chunk_size=chunk_size, chunk_overlap=chunk_overlap)
