"""`AIClient` de prueba para los tests del pipeline RAG (SPEC-017).

NO abre red real ni importa SDKs de terceros: implementa la misma interfaz
pública que `app.services.ai_service.AIClient` (`embed`, `chat`,
`is_available`) con vectores/(respuestas determinísticas construidos en
memoria, para poder afirmar sobre el ORDEN de similitud recuperado y sobre el
contenido de las citas sin depender de un modelo real ni de una GPU.

Se usa en los tests que ejercitan `ingest_service`/`retrieval_service`/
`draft_service`/`app/api/rag.py` vía `app.dependency_overrides`.
"""

from __future__ import annotations

from app.models.embedding import EMBEDDING_DIM
from app.services.ai_service import AIServiceUnavailableError


def _vector_for_text(text: str) -> list[float]:
    """Vector determinístico y estable para un texto dado (bag-of-characters).

    No pretende tener semántica real, pero SÍ debe producir un ordenamiento
    de similitud coseno coherente con el solapamiento de CONTENIDO entre
    textos — condición que los tests de `retrieval_service`/`draft_service`
    verifican explícitamente (orden por similitud, citas trazables).

    CORRECCIÓN (bug encontrado contra Postgres real,
    `test_recuperacion_devuelve_chunks_ordenados_por_similitud`): la versión
    anterior indexaba por `i % EMBEDDING_DIM` (la POSICIÓN del carácter
    dentro del string), no por su identidad — dos chunks distintos, cada uno
    calculado con su propio índice interno reiniciado en 0, podían
    "alinearse" por pura coincidencia posicional y producir una similitud
    coseno más alta que la de un chunk que realmente comparte contenido con
    la consulta (confirmado empíricamente: un chunk dominado por 'B'/'C'
    resultaba "más similar" a una consulta "AAAA..." que el chunk que de
    verdad contenía las 'A'). Indexar por `ord(ch) % EMBEDDING_DIM` (la
    IDENTIDAD del carácter) hace que el mismo carácter siempre incremente la
    misma dimensión del vector sin importar en qué posición aparezca,
    dando una similitud tipo "bag of characters" que sí correlaciona con el
    solapamiento real de contenido.
    """
    vector = [0.0] * EMBEDDING_DIM
    for ch in text:
        vector[ord(ch) % EMBEDDING_DIM] += 1.0
    # Normaliza a una escala estable para que la distancia coseno no quede
    # dominada por la longitud del texto.
    norm = sum(v * v for v in vector) ** 0.5 or 1.0
    return [v / norm for v in vector]


class FakeEmbeddingResult:
    def __init__(self, vector: list[float]):
        self.vector = vector
        self.model = "nomic-embed-text-fake"
        self.dimension = len(vector)


class FakeChatResult:
    def __init__(self, content: str):
        self.content = content
        self.model = "qwen2.5-fake"
        self.raw: dict = {}


class FakeAIClient:
    """Doble de prueba de `AIClient`: embeddings/generación 100% locales al
    proceso de test, cero llamadas HTTP (cumple el mismo espíritu del
    CHECKPOINT SENSIBLE que el `AIClient` real: nunca sale a la red)."""

    def __init__(self, *, unavailable: bool = False, chat_response: str | None = None):
        self.unavailable = unavailable
        self.chat_response = chat_response
        self.embed_calls: list[str] = []
        self.chat_calls: list[list[dict[str, str]]] = []

    def embed(self, text: str, *, model: str | None = None) -> FakeEmbeddingResult:
        if self.unavailable:
            raise AIServiceUnavailableError("servicio de IA no disponible (fake)")
        self.embed_calls.append(text)
        return FakeEmbeddingResult(_vector_for_text(text))

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        stream: bool = False,
    ) -> FakeChatResult:
        if self.unavailable:
            raise AIServiceUnavailableError("servicio de IA no disponible (fake)")
        self.chat_calls.append(messages)
        content = self.chat_response or (
            "Borrador generado a partir del contexto recuperado "
            "[Fuente 1] [Fuente 2] [Fuente 3]."
        )
        return FakeChatResult(content)

    def is_available(self) -> bool:
        return not self.unavailable
