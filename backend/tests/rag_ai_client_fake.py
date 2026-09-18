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
    """Vector determinístico y estable para un texto dado.

    No pretende tener semántica real: solo garantiza que textos idénticos
    producen vectores idénticos (para reproducibilidad del test) y que
    textos distintos producen vectores distintos (para poder comprobar el
    ordenamiento por similitud coseno).
    """
    vector = [0.0] * EMBEDDING_DIM
    for i, ch in enumerate(text):
        vector[i % EMBEDDING_DIM] += (ord(ch) % 13) + 1
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
