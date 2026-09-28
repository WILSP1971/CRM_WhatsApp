"""
Benchmark de latencia — `GET /api/v1/analytics/business` (SPEC-063/SPEC-062)
— THOR, CE-74 de SPEC-065.

Objetivo de latencia (definido y justificado por THOR):

    p95 <= 1500 ms (rango de 30 días, volumen representativo, canal=None)

Justificación: el endpoint es ON-DEMAND (Q2 del Lead, PLAN-007), invocado
desde un dashboard de negocio (`AnalyticsPage`, SPEC-064) al cargar la
página o cambiar el filtro de rango/canal — NO es un endpoint de alta
frecuencia ni conversacional (no es autocomplete, no es el envío de un
mensaje, no bloquea una conversación con un contacto). Un usuario humano
mirando un dashboard tolera perfectamente 1-2s de "loading" ocasional; el
propio SPEC-063 (RNF-73) ya contempla cache/ETag como mitigación OPCIONAL
si esto no se cumple, precisamente porque no se asumía p95 sub-200ms como
en `GET /api/v1/contacts` (ver `loadtest/locustfile.py`, RNF-04 SPEC-022:
p95 API no-IA <= 200 ms — ese objetivo NO aplica aquí a propósito, es un
endpoint distinto con un patrón de uso distinto). 1500 ms de techo (no
2000ms) porque el endpoint NO hace ninguna llamada a IA/red externa (a
diferencia de `/rag/draft`, con techo de 6s) — es 100% cómputo SQL local
contra Postgres, por lo que un margen menor que el "peor caso" de 2s deja
holgura para detectar regresiones antes de que se vuelvan dolorosas, sin
ser tan estricto como para forzar cache prematuro en Fase 3.

Qué mide este script (contra el endpoint HTTP COMPLETO, no solo la función
de servicio — a diferencia de la medición de `get_response_time_metrics`
hecha durante SPEC-062, que fue directa a la función Python):

  1. Siembra de forma DETERMINISTA (semilla fija) un tenant sintético con
     un volumen representativo: ~2.500 conversaciones / ~85.000 mensajes
     en una ventana de 30 días (mismo orden de magnitud que el benchmark de
     `analytics_service` documentado en el docstring de
     `get_response_time_metrics`) + ~500 `rag_drafts` (para ejercer
     `get_ai_assistance_metrics`, la 4ta función que dispara el endpoint).
  2. Corre `ANALYZE` sobre `conversations`/`messages`/`rag_drafts` (el
     planner de Postgres necesita estadísticas actualizadas tras un INSERT
     masivo o puede elegir planes pobres — mismo criterio que la iteración
     final de SPEC-062).
  3. Ejercita el endpoint vía `TestClient` + `api_as_tenant` (mismo patrón
     RLS real que `tests/test_calls_api.py`/`tests/conftest.py`: rol
     `omnicore_app`, `app.tenant_id` fijado, JWT simulado) con 3 requests de
     "cache caliente" DESCARTADAS (warm-up: primera conexión, plan caching,
     etc. — evita medir el artefacto de cold-cache ya documentado en este
     proyecto) y luego mide 30 requests consecutivas sobre
     `desde=hoy-30d, hasta=hoy, canal=None` (el caso más costoso: sin
     filtro de canal, rango completo).
  4. Reporta p50/p95/p99 + min/max/mean.
  5. Limpia TODO el dato sintético insertado (tenant, contacto,
     conversaciones, mensajes, drafts) en un `finally`, incluso si el
     benchmark falla a medio camino.

Requiere Postgres real accesible (mismas variables que el resto de la
suite, ver `tests/conftest.py`: `DATABASE_URL_MIGRATIONS`/`DATABASE_URL`,
`DB_APP_PASSWORD`) — NO se ejecuta como parte de la suite normal de pytest
(es lento a propósito: ~85k inserts). Uso:

    cd backend
    DATABASE_URL_MIGRATIONS=postgresql://postgres:<pw>@localhost:5432/omnicore_ai \
    DB_APP_PASSWORD=<pw omnicore_app> \
    .venv/bin/python -m tests.perf.bench_analytics_business_endpoint

Requiere Docker (`docker compose up db`) o un Postgres real equivalente con
`init-sql/01-roles-app.sh` aplicado (rol `omnicore_app`, ADR-008) — este
script NO se pudo ejecutar en el sandbox de esta sesión de THOR (sin acceso
a Docker ni a un Postgres real, ver reporte de THOR en SPEC-065/CE-74): se
deja aquí como artefacto reproducible para QUICKSILVER/CI/HAWKEYE.
"""

from __future__ import annotations

import os
import statistics
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import sqlalchemy as sa

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

UTC = timezone.utc

# --- Parámetros del volumen sintético (deterministas, ~mismo orden que el
# benchmark de SPEC-062 sobre `analytics_service`) --------------------------
N_DIAS = 30
CONVERSACIONES_POR_DIA = 84  # ~2.520 conversaciones en 30 días
MENSAJES_POR_CONVERSACION = 34  # ~85.680 mensajes en total
DRAFTS_APROBADOS_RATIO = 0.2  # ~1 de cada 5 conversaciones con draft aprobado
CANALES = ["whatsapp", "voz", "web"]
N_WARMUP = 3
N_MEDICIONES = 30
OBJETIVO_P95_MS = 1500.0


def _database_url() -> str:
    return os.getenv(
        "DATABASE_URL_MIGRATIONS",
        os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg://postgres:postgres@localhost:5432/omnicore_ai_test",
        ),
    )


def _app_database_url(owner_url) -> str:
    explicit = os.getenv("DATABASE_URL_APP")
    if explicit:
        return explicit
    app_password = os.getenv("DB_APP_PASSWORD")
    if not app_password:
        raise SystemExit(
            "DB_APP_PASSWORD no configurada — requerida para conectar como "
            "rol de aplicación 'omnicore_app' (ADR-008). Ver docstring de "
            "este script."
        )
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(owner_url)
    netloc_host = parts.hostname or "localhost"
    if parts.port:
        netloc_host = f"{netloc_host}:{parts.port}"
    netloc = f"omnicore_app:{app_password}@{netloc_host}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def _seed_tenant(owner_engine) -> dict:
    """Inserta el tenant/contacto/conversaciones/mensajes/drafts sintéticos
    con el rol OWNER (bypass de RLS a propósito, mismo patrón que
    `tests/conftest.py::two_tenants_with_data` / `tests/test_analytics_service.py`).
    Determinista: siempre la misma cantidad de filas y la misma distribución
    de fechas/canales/estados para poder comparar mediciones entre corridas.
    """
    tenant_id = uuid.uuid4()
    contact_id = uuid.uuid4()
    hoy = datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)
    inicio_rango = hoy - timedelta(days=N_DIAS - 1)

    with owner_engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO tenants (id, nombre, slug) VALUES (:id, :nombre, :slug)"
            ),
            {
                "id": tenant_id,
                "nombre": "THOR Bench Analytics",
                "slug": f"thor-bench-analytics-{tenant_id.hex[:8]}",
            },
        )
        conn.execute(
            sa.text(
                "INSERT INTO contacts (id, tenant_id, nombre, telefono) "
                "VALUES (:id, :tenant_id, :nombre, :telefono)"
            ),
            {
                "id": contact_id,
                "tenant_id": tenant_id,
                "nombre": "Contacto Bench THOR",
                "telefono": "3000009999",
            },
        )

        conversation_rows = []
        message_rows = []
        draft_rows = []

        remitentes_ciclo = ["contacto", "agente", "contacto", "ia"]
        for dia_idx in range(N_DIAS):
            dia = inicio_rango + timedelta(days=dia_idx)
            for c in range(CONVERSACIONES_POR_DIA):
                conv_id = uuid.uuid4()
                canal = CANALES[(dia_idx * CONVERSACIONES_POR_DIA + c) % len(CANALES)]
                estado = "cerrada" if c % 2 == 0 else "abierta"
                created_at = dia + timedelta(minutes=c)
                conversation_rows.append(
                    {
                        "id": conv_id,
                        "tenant_id": tenant_id,
                        "contact_id": contact_id,
                        "canal": canal,
                        "estado": estado,
                        "activo": True,
                        "created_at": created_at,
                    }
                )

                for m in range(MENSAJES_POR_CONVERSACION):
                    remitente = remitentes_ciclo[m % len(remitentes_ciclo)]
                    sentimiento = None
                    if remitente == "contacto":
                        sentimiento = ["positivo", "neutral", "negativo"][m % 3]
                    message_rows.append(
                        {
                            "id": uuid.uuid4(),
                            "tenant_id": tenant_id,
                            "conversation_id": conv_id,
                            "remitente": remitente,
                            "contenido": "mensaje sintético de benchmark THOR",
                            "activo": True,
                            "sentimiento": sentimiento,
                            "wamid": f"wamid.thor-bench-{uuid.uuid4().hex[:16]}",
                            "created_at": created_at + timedelta(seconds=m * 20),
                        }
                    )

                if c % int(1 / DRAFTS_APROBADOS_RATIO) == 0:
                    draft_rows.append(
                        {
                            "id": uuid.uuid4(),
                            "tenant_id": tenant_id,
                            "conversation_id": conv_id,
                            "query": "consulta sintética THOR",
                            "content_original": "respuesta original",
                            "content": "respuesta original",
                            "model": "modelo-bench",
                            "citations": "[]",
                            "estado": "aprobado",
                            "activo": True,
                        }
                    )

        conv_stmt = sa.text(
            "INSERT INTO conversations "
            "(id, tenant_id, contact_id, canal, estado, activo, created_at, updated_at) "
            "VALUES (:id, :tenant_id, :contact_id, :canal, :estado, :activo, "
            ":created_at, :created_at)"
        )
        msg_stmt = sa.text(
            "INSERT INTO messages "
            "(id, tenant_id, conversation_id, remitente, contenido, tipo, activo, "
            "estado_entrega, sentimiento, wamid, created_at, updated_at) "
            "VALUES (:id, :tenant_id, :conversation_id, :remitente, :contenido, "
            "'texto', :activo, 'enviado', :sentimiento, :wamid, :created_at, :created_at)"
        )
        draft_stmt = sa.text(
            "INSERT INTO rag_drafts "
            "(id, tenant_id, conversation_id, query, content_original, content, "
            "model, citations, estado, activo, created_at, updated_at) "
            "VALUES (:id, :tenant_id, :conversation_id, :query, :content_original, "
            ":content, :model, :citations, :estado, :activo, now(), now())"
        )

        BATCH = 2000
        for i in range(0, len(conversation_rows), BATCH):
            conn.execute(conv_stmt, conversation_rows[i : i + BATCH])
        for i in range(0, len(message_rows), BATCH):
            conn.execute(msg_stmt, message_rows[i : i + BATCH])
        for i in range(0, len(draft_rows), BATCH):
            conn.execute(draft_stmt, draft_rows[i : i + BATCH])

    print(
        f"[seed] tenant={tenant_id} conversaciones={len(conversation_rows)} "
        f"mensajes={len(message_rows)} drafts={len(draft_rows)}"
    )
    return {
        "tenant_id": tenant_id,
        "contact_id": contact_id,
        "desde": inicio_rango.date(),
        "hasta": hoy.date(),
    }


def _cleanup(owner_engine, tenant_id) -> None:
    with owner_engine.begin() as conn:
        conn.execute(
            sa.text("DELETE FROM rag_drafts WHERE tenant_id = :t"), {"t": tenant_id}
        )
        conn.execute(
            sa.text("DELETE FROM messages WHERE tenant_id = :t"), {"t": tenant_id}
        )
        conn.execute(
            sa.text("DELETE FROM conversations WHERE tenant_id = :t"), {"t": tenant_id}
        )
        conn.execute(
            sa.text("DELETE FROM contacts WHERE tenant_id = :t"), {"t": tenant_id}
        )
        conn.execute(sa.text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id})
    print(f"[cleanup] datos sintéticos del tenant {tenant_id} eliminados")


def _explain_analyze_queries(owner_engine, tenant_id, desde, hasta) -> None:
    """`EXPLAIN (ANALYZE, BUFFERS)` de la query más costosa del endpoint
    (`get_response_time_metrics`, doble LATERAL) directamente en SQL crudo,
    fijando `app.tenant_id` vía SET LOCAL dentro de la misma transacción con
    el rol owner (para EXPLAIN; el aislamiento de RLS ya está cubierto por
    `tests/test_analytics_service.py::test_rls_*`, esto es solo para
    inspeccionar el plan/spill a disco)."""
    from app.db.session import set_tenant_session

    with owner_engine.begin() as conn:
        set_tenant_session(conn, str(tenant_id))
        sql = sa.text(
            """
            EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
            WITH conv AS (
                SELECT id FROM conversations
                WHERE activo = true
                  AND tenant_id = :tenant_id
                  AND created_at >= :desde AND created_at < :hasta
            )
            SELECT
                count(delta.delta_seg) AS n_respuestas,
                avg(delta.delta_seg) AS respuesta_promedio_seg
            FROM conv
            JOIN LATERAL (
                SELECT m.created_at AS entrante_ts
                FROM (
                    SELECT created_at, remitente,
                           lag(remitente) OVER (ORDER BY created_at) AS remitente_anterior
                    FROM messages
                    WHERE activo = true AND conversation_id = conv.id
                ) m
                WHERE m.remitente = 'contacto'
                  AND (m.remitente_anterior IS NULL OR m.remitente_anterior <> 'contacto')
            ) entrante ON true
            JOIN LATERAL (
                SELECT created_at AS saliente_ts
                FROM messages
                WHERE activo = true AND conversation_id = conv.id
                  AND remitente IN ('agente', 'ia')
                  AND created_at > entrante.entrante_ts
                ORDER BY created_at
                LIMIT 1
            ) saliente ON true
            JOIN LATERAL (
                SELECT extract(epoch FROM saliente.saliente_ts - entrante.entrante_ts) AS delta_seg
            ) delta ON true
            """
        )
        result = conn.execute(
            sql,
            {
                "tenant_id": tenant_id,
                "desde": datetime.combine(desde, datetime.min.time()),
                "hasta": datetime.combine(hasta, datetime.min.time()) + timedelta(days=1),
            },
        )
        plan_lines = [row[0] for row in result]
        plan_text = "\n".join(plan_lines)
        print("\n[EXPLAIN ANALYZE] get_response_time_metrics (query dominante):")
        print(plan_text)
        disk_spill = "external merge" in plan_text or "Disk" in plan_text
        print(f"\n[EXPLAIN ANALYZE] ¿disk spill detectado? {disk_spill}")


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return float("nan")
    k = (len(sorted_values) - 1) * pct
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    if f == c:
        return sorted_values[f]
    return sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f)


def main() -> None:
    owner_url = _database_url()
    app_url = _app_database_url(owner_url)

    owner_engine = sa.create_engine(owner_url, pool_pre_ping=True, future=True)

    # Aplica migraciones igual que `tests/conftest.py::postgres_engine`.
    from alembic import command
    from alembic.config import Config

    alembic_cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    os.environ["DATABASE_URL_MIGRATIONS"] = owner_url
    command.upgrade(alembic_cfg, "head")

    seed = _seed_tenant(owner_engine)
    tenant_id = seed["tenant_id"]

    try:
        with owner_engine.begin() as conn:
            conn.execute(sa.text("ANALYZE conversations"))
            conn.execute(sa.text("ANALYZE messages"))
            conn.execute(sa.text("ANALYZE rag_drafts"))
        print("[analyze] estadísticas actualizadas")

        _explain_analyze_queries(owner_engine, tenant_id, seed["desde"], seed["hasta"])

        # --- Endpoint HTTP completo vía TestClient + RLS real -------------
        app_engine = sa.create_engine(app_url, pool_pre_ping=True, future=True)
        from sqlalchemy.orm import sessionmaker

        from app.api import deps
        from app.db.session import set_tenant_session
        from app.main import app
        from fastapi.testclient import TestClient

        AppSessionLocal = sessionmaker(bind=app_engine, future=True)

        def fake_get_current_user():
            return SimpleNamespace(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                email="thor-bench@tenant.test",
                nombre="THOR Bench",
                rol="agente",
                activo=True,
            )

        def fake_get_tenant_db():
            db = AppSessionLocal()
            try:
                with db.begin():
                    set_tenant_session(db, str(tenant_id))
                    yield db
            finally:
                db.close()

        app.dependency_overrides[deps.get_current_user] = fake_get_current_user
        app.dependency_overrides[deps.get_tenant_db] = fake_get_tenant_db

        client = TestClient(app)
        params = {"desde": seed["desde"].isoformat(), "hasta": seed["hasta"].isoformat()}

        for _ in range(N_WARMUP):
            r = client.get("/api/v1/analytics/business", params=params)
            assert r.status_code == 200, r.text

        latencias_ms: list[float] = []
        for _ in range(N_MEDICIONES):
            t0 = time.perf_counter()
            r = client.get("/api/v1/analytics/business", params=params)
            t1 = time.perf_counter()
            assert r.status_code == 200, r.text
            latencias_ms.append((t1 - t0) * 1000.0)

        app.dependency_overrides.clear()
        app_engine.dispose()

        latencias_ms.sort()
        p50 = _percentile(latencias_ms, 0.50)
        p95 = _percentile(latencias_ms, 0.95)
        p99 = _percentile(latencias_ms, 0.99)

        print("\n[latencia] GET /api/v1/analytics/business "
              f"(rango {N_DIAS}d, sin filtro canal, N={N_MEDICIONES}):")
        print(f"  min={min(latencias_ms):.1f}ms  mean={statistics.mean(latencias_ms):.1f}ms  "
              f"max={max(latencias_ms):.1f}ms")
        print(f"  p50={p50:.1f}ms  p95={p95:.1f}ms  p99={p99:.1f}ms")
        print(f"  objetivo p95 THOR = {OBJETIVO_P95_MS:.0f}ms -> "
              f"{'CUMPLE' if p95 <= OBJETIVO_P95_MS else 'NO CUMPLE'}")

    finally:
        _cleanup(owner_engine, tenant_id)
        owner_engine.dispose()


if __name__ == "__main__":
    main()
