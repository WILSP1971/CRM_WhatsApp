"""Cliente de IA local self-hosted (Ollama) — SPEC-016.

CHECKPOINT SENSIBLE (`.no-externo`, RNF-01/CE-21): este módulo es el ÚNICO
punto de la aplicación que habla con el servicio de inferencia. SOLO se
comunica con el host interno configurado en `Settings.ai_base_url`
(`app/core/config.py`), que a su vez está validado en el arranque para
apuntar exclusivamente al servicio `ia` de la red Docker `ia_internal`
(`internal: true`, SPEC-011) o a loopback (desarrollo local sin Docker).

No importa ningún SDK de terceros (OpenAI/Anthropic/HF/etc.) — SOLO usa
`httpx`, que ya es una dependencia del backend (SPEC-011), para hablar HTTP
con Ollama. `check-externos-backend.sh` (ADR-005) audita este archivo junto
al resto del backend para detectar cualquier regresión de egress.

Modo degradado (RF, R-21): si el servicio de IA no responde (timeout, error
de red, modelo no descargado) las funciones no lanzan una excepción genérica
sin control — devuelven/propagan `AIServiceUnavailableError`, para que el
llamador decida cómo degradar (p.ej. SPEC-017/018/019 mostrarán un aviso en
vez de romper la petición completa).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.metrics import observe_ai_request


class AIServiceError(RuntimeError):
    """Error base al hablar con el servicio de IA local."""


class AIServiceUnavailableError(AIServiceError):
    """El servicio de IA local no respondió (timeout, conexión rechazada,
    modelo no cargado, etc.) — modo degradado esperado (R-21)."""


class AIServiceResponseError(AIServiceError):
    """El servicio de IA local respondió pero con un error/formato inesperado."""


@dataclass(frozen=True)
class ChatResult:
    """Resultado de una generación de chat/completion del LLM local."""

    content: str
    model: str
    raw: dict[str, Any]


@dataclass(frozen=True)
class EmbeddingResult:
    """Resultado de una vectorización de texto (embeddings locales)."""

    vector: list[float]
    model: str
    dimension: int


class AIClient:
    """Cliente tipado para el servicio Ollama interno (LLM + embeddings).

    El host base (`base_url`) proviene EXCLUSIVAMENTE de `Settings.ai_base_url`
    salvo que se inyecte explícitamente (útil en tests). Nunca se construye a
    partir de entrada de usuario ni de un dominio hardcodeado externo.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        llm_model: str | None = None,
        embedding_model: str | None = None,
        connect_timeout: float | None = None,
        request_timeout: float | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        settings = get_settings()
        self.base_url = (base_url or settings.ai_base_url).rstrip("/")
        self.llm_model = llm_model or settings.ai_llm_model
        self.embedding_model = embedding_model or settings.ai_embedding_model
        self._connect_timeout = (
            connect_timeout
            if connect_timeout is not None
            else settings.ai_connect_timeout_seconds
        )
        self._request_timeout = (
            request_timeout
            if request_timeout is not None
            else settings.ai_request_timeout_seconds
        )
        self._external_client = client

    def _timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            connect=self._connect_timeout,
            read=self._request_timeout,
            write=self._request_timeout,
            pool=self._request_timeout,
        )

    def _get_client(self) -> httpx.Client:
        if self._external_client is not None:
            return self._external_client
        return httpx.Client(base_url=self.base_url, timeout=self._timeout())

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        owns_client = self._external_client is None
        client = self._get_client()
        try:
            response = client.post(path, json=payload)
        except httpx.TimeoutException as exc:
            raise AIServiceUnavailableError(
                f"Timeout al contactar el servicio de IA local ({self.base_url}{path})"
            ) from exc
        except httpx.ConnectError as exc:
            raise AIServiceUnavailableError(
                f"No se pudo conectar al servicio de IA local ({self.base_url}{path})"
            ) from exc
        except httpx.HTTPError as exc:
            raise AIServiceUnavailableError(
                f"Error de red al contactar el servicio de IA local: {exc}"
            ) from exc
        finally:
            if owns_client:
                client.close()

        if response.status_code >= 500:
            raise AIServiceUnavailableError(
                f"Servicio de IA local respondió {response.status_code} "
                f"(posible modelo no cargado/no descargado)"
            )
        if response.status_code >= 400:
            raise AIServiceResponseError(
                f"Servicio de IA local rechazó la petición: "
                f"{response.status_code} {response.text[:200]}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise AIServiceResponseError(
                "Respuesta del servicio de IA local no es JSON válido"
            ) from exc

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        stream: bool = False,
    ) -> ChatResult:
        """Genera una respuesta de chat con el LLM local (API `/api/chat` de Ollama).

        `messages` sigue el formato estándar `[{"role": "user", "content": "..."}]`.
        """
        used_model = model or self.llm_model
        with observe_ai_request("chat", used_model):
            data = self._post(
                "/api/chat",
                {
                    "model": used_model,
                    "messages": messages,
                    "stream": stream,
                    "options": {"temperature": temperature},
                },
            )
        message = data.get("message")
        if not isinstance(message, dict) or "content" not in message:
            raise AIServiceResponseError(
                "Respuesta del LLM local sin campo 'message.content' esperado"
            )
        content = message["content"]
        if not isinstance(content, str):
            raise AIServiceResponseError(
                "Respuesta del LLM local con 'message.content' de tipo inesperado"
            )
        return ChatResult(content=content, model=used_model, raw=data)

    def embed(self, text: str, *, model: str | None = None) -> EmbeddingResult:
        """Genera el vector de embedding local para un texto (API `/api/embeddings`)."""
        used_model = model or self.embedding_model
        with observe_ai_request("embed", used_model):
            data = self._post(
                "/api/embeddings",
                {"model": used_model, "prompt": text},
            )
        vector = data.get("embedding")
        if not isinstance(vector, list) or not vector:
            raise AIServiceResponseError(
                "Respuesta de embeddings local sin campo 'embedding' esperado"
            )
        return EmbeddingResult(
            vector=[float(v) for v in vector],
            model=used_model,
            dimension=len(vector),
        )

    def is_available(self) -> bool:
        """Chequeo ligero de disponibilidad (usado por el endpoint de salud)."""
        owns_client = self._external_client is None
        client = self._get_client()
        try:
            response = client.get("/api/tags")
            return response.status_code == 200
        except httpx.HTTPError:
            return False
        finally:
            if owns_client:
                client.close()


def get_ai_client() -> AIClient:
    """Factory para inyección de dependencias (FastAPI `Depends`)."""
    return AIClient()
