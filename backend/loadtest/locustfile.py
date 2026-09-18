"""Arnés de carga/latencia — SPEC-022 (RNF-04, coordinado con THOR).

Mide los DOS objetivos de rendimiento de SPEC-022 contra un backend REAL
(API + Postgres + Redis + Ollama vivos, p.ej. `docker compose up`, o el
entorno de CI con services):

  1. **p95 API no-IA <= 200 ms**: `login` + lecturas de `/api/v1/contacts`
     (CRUD que NO llama al LLM).
  2. **p95 RAG <= 6 s (GPU)** / degradación CPU documentada: `POST
     /api/v1/rag/draft`, que sí atraviesa el LLM local (Ollama).

No corre contra ninguna API de inferencia externa de terceros: `HOST` debe
apuntar SIEMPRE al backend interno (por defecto `http://localhost:8000`,
o el servicio `api` de `docker-compose.yml` en CI). Este arnés NO hace
ninguna llamada de red fuera del propio backend bajo prueba (verificado por
`check-externos-backend.sh`, que también escanea `loadtest/`).

Uso local (requiere backend real levantado, fuera de este sandbox):

    locust -f backend/loadtest/locustfile.py --host http://localhost:8000 \
        --headless -u 20 -r 5 -t 2m --csv=loadtest_report

Luego revisar `loadtest_report_stats.csv`: columna `95%` de la fila
`POST /api/v1/rag/draft` debe ser <= 6000 (ms) en GPU; la fila de
`GET /api/v1/contacts` debe ser <= 200 (ms).

Variables de entorno (todas opcionales, con defaults seguros para CI):
  - LOADTEST_TENANT_SLUG / LOADTEST_EMAIL / LOADTEST_PASSWORD: credenciales
    de un usuario de prueba ya sembrado (ver `loadtest/seed_loadtest_user.py`
    o el fixture de CI). Si el login falla, el usuario Locust se detiene
    (no genera tráfico "de mentira" contra endpoints protegidos).
  - LOADTEST_RAG_QUERY: pregunta usada contra `/rag/draft` (debe tener
    contexto ingerido previamente para no recibir 404 por falta de citas).
"""

from __future__ import annotations

import os

from locust import HttpUser, between, task

TENANT_SLUG = os.getenv("LOADTEST_TENANT_SLUG", "tenant-loadtest")
EMAIL = os.getenv("LOADTEST_EMAIL", "loadtest@tenant-loadtest.test")
PASSWORD = os.getenv("LOADTEST_PASSWORD", "LoadTest#2026")
RAG_QUERY = os.getenv("LOADTEST_RAG_QUERY", "¿Cuál es la política de garantía?")


class OmniCoreApiUser(HttpUser):
    """Simula un agente autenticado consultando la API core y pidiendo
    borradores RAG. Cada usuario Locust hace login UNA vez y reutiliza el
    JWT (igual que la SPA)."""

    wait_time = between(1, 3)
    token: str | None = None

    def on_start(self) -> None:
        response = self.client.post(
            "/api/v1/auth/login",
            json={
                "tenant_slug": TENANT_SLUG,
                "email": EMAIL,
                "password": PASSWORD,
            },
            name="POST /api/v1/auth/login",
        )
        if response.status_code == 200:
            self.token = response.json().get("access_token")
        else:
            # No generamos tráfico autenticado de mentira: si el login
            # falla (usuario de carga no sembrado), este Locust user
            # se detiene y el fallo queda visible en el reporte.
            self.environment.runner.quit()

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    @task(6)
    def list_contacts(self) -> None:
        """Objetivo RNF-04: p95 API no-IA <= 200 ms."""
        self.client.get(
            "/api/v1/contacts",
            headers=self._auth_headers(),
            name="GET /api/v1/contacts",
        )

    @task(3)
    def health_check(self) -> None:
        self.client.get("/healthz", name="GET /healthz")

    @task(1)
    def rag_draft(self) -> None:
        """Objetivo RNF-04: p95 RAG <= 6 s (GPU); degradación CPU documentada.

        Baja frecuencia relativa (peso 1 vs 6+3) porque el RAG es la
        operación más costosa: en un CRM real la proporción de mensajes
        que requieren un borrador asistido por IA es minoritaria frente a
        lecturas de bandeja/CRM. Ajustar el peso si THOR define otro mix.
        """
        self.client.post(
            "/api/v1/rag/draft",
            json={"query": RAG_QUERY, "top_k": 5},
            headers=self._auth_headers(),
            name="POST /api/v1/rag/draft",
        )
