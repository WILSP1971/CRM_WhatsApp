"""
Fixtures compartidos de pytest para tests de integración contra PostgreSQL real
(SPEC-012). Estos tests requieren el `db` del `docker-compose.yml` del proyecto
(PostgreSQL 16 + pgvector) arriba y accesible vía `DATABASE_URL`.

Si `DATABASE_URL` no apunta a un Postgres accesible, los tests que dependen de
este fixture se SKIPEAN automáticamente (no fallan) para no romper el resto de
la suite en entornos sin Docker (p.ej. este sandbox de implementación).

Roles de BD (ADR-008, RLS efectiva) — MARCADOS PARA CI (requieren Postgres
real con `init-sql/01-roles-app.sh` aplicado, ver `docker-compose.yml`):
  - `postgres_engine` (este módulo): conecta con el rol PRIVILEGIADO/owner
    (`DATABASE_URL`, típicamente `postgres`). Se usa SOLO para bootstrap de
    fixtures (crear tenants/contactos de prueba fuera de cualquier filtro de
    RLS) y para verificaciones de "estado administrativo" (p.ej. que un dato
    no fue alterado). PostgreSQL NUNCA aplica RLS a un superusuario/owner, así
    que un test que solo use `postgres_engine` para EJERCER el aislamiento
    sería un falso positivo (el defecto original detectado por BLACK PANTHER
    en SPEC-025/ADR-008).
  - `app_engine`: conecta con el rol de APLICACIÓN NO-superusuario
    `omnicore_app` (NOSUPERUSER NOBYPASSRLS, GRANTs mínimos DML). Es el rol
    con el que corre `api`/workers en runtime. Los tests que EJERCEN RLS de
    verdad (aislamiento cross-tenant, `SECURITY DEFINER`) deben usar este
    fixture, no `postgres_engine`, para no ser falsos positivos.
"""

import os
import uuid
from types import SimpleNamespace
from urllib.parse import urlsplit, urlunsplit

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Rol de aplicación NO-superusuario (ADR-008). Debe coincidir con
# `DB_APP_ROLE`/`omnicore_app` creado por `init-sql/01-roles-app.sh`.
_APP_ROLE = os.getenv("DB_APP_ROLE", "omnicore_app")


def _database_url() -> str:
    """URL de conexión con el rol PRIVILEGIADO/owner (bootstrap/Alembic).

    Prioridad: `DATABASE_URL_MIGRATIONS` (ADR-008, mismo nombre que usa
    `alembic/env.py` en runtime real) y, si no está definida, `DATABASE_URL`
    (compatibilidad con entornos de test que aún no separaron variables).
    """
    return os.getenv(
        "DATABASE_URL_MIGRATIONS",
        os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg://postgres:postgres@localhost:5432/omnicore_ai_test",
        ),
    )


def _app_database_url(owner_url: str) -> str:
    """URL de conexión con el rol de APLICACIÓN `omnicore_app` (ADR-008).

    Prioridad: `DATABASE_URL_APP` explícita (si el entorno de CI la define)
    y, si no, se deriva de la URL del owner sustituyendo usuario/contraseña
    por `DB_APP_ROLE`/`DB_APP_PASSWORD` — evita duplicar host/puerto/db en
    dos variables cuando basta con cambiar las credenciales.
    """
    explicit = os.getenv("DATABASE_URL_APP")
    if explicit:
        return explicit

    app_password = os.getenv("DB_APP_PASSWORD")
    if not app_password:
        # Sin contraseña de app configurada no se puede derivar una URL
        # válida; se deja que `_postgres_available` falle al conectar y el
        # fixture se SKIPee (no es un Postgres con ADR-008 aplicado).
        return owner_url

    parts = urlsplit(owner_url)
    netloc_host = parts.hostname or "localhost"
    if parts.port:
        netloc_host = f"{netloc_host}:{parts.port}"
    netloc = f"{_APP_ROLE}:{app_password}@{netloc_host}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def _postgres_available(url: str) -> bool:
    try:
        engine = sa.create_engine(url, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(sa.text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def database_url() -> str:
    return _database_url()


@pytest.fixture(scope="session")
def postgres_engine(database_url):
    """
    Motor conectado a PostgreSQL real CON EL ROL PRIVILEGIADO/owner, con el
    esquema de SPEC-012 aplicado (`alembic upgrade head`, ADR-008: Alembic
    siempre corre con este rol). Si no hay Postgres accesible, se saltan los
    tests que dependan de este fixture (se documenta en el resumen de
    ejecución, no se marcan como aprobados en falso).

    IMPORTANTE (ADR-008): este motor NO debe usarse para EJERCER RLS (el
    owner nunca está sujeto a RLS/FORCE RLS). Úsalo solo para bootstrap de
    datos de fixtures o para verificar estado "fuera de RLS" explícitamente.
    Para ejercer RLS real usa el fixture `app_engine`.
    """
    if not _postgres_available(database_url):
        pytest.skip(
            "PostgreSQL no accesible en este entorno (sin daemon Docker/DB real). "
            "Este test corre en CI contra el `db` del docker-compose.yml (SPEC-012)."
        )

    alembic_cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    alembic_cfg.set_main_option("script_location", os.path.join(BACKEND_DIR, "alembic"))
    os.environ["DATABASE_URL_MIGRATIONS"] = database_url
    command.upgrade(alembic_cfg, "head")

    engine = sa.create_engine(database_url, pool_pre_ping=True, future=True)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def app_engine(database_url, postgres_engine):
    """
    Motor conectado a PostgreSQL real con el rol de APLICACIÓN NO-superusuario
    `omnicore_app` (ADR-008: NOSUPERUSER NOBYPASSRLS, GRANTs mínimos DML). Es
    el mismo rol con el que corren `api`/`rag_worker`/`sentiment_worker` en
    runtime (`docker-compose.yml`).

    A diferencia de `postgres_engine` (owner, nunca sujeto a RLS), las
    consultas hechas con este motor SÍ están sujetas a Row Level Security
    (ENABLE+FORCE, ADR-004) — es el motor correcto para EJERCER el
    aislamiento cross-tenant y la función `SECURITY DEFINER` tal como los
    ejecutaría la aplicación real.

    REQUIERE Postgres real con `init-sql/01-roles-app.sh` (ADR-008) ya
    aplicado (rol `omnicore_app` existente con `DB_APP_PASSWORD` conocida).
    Si el rol de aplicación no está disponible, se SKIPEA (no se marca en
    falso) — MARCADO PARA CI: correr contra el `db` de `docker-compose.yml`
    con `.env` completo (incluye `DB_APP_PASSWORD`).
    """
    app_url = _app_database_url(database_url)
    if not _postgres_available(app_url):
        pytest.skip(
            "Rol de aplicación 'omnicore_app' no accesible en este entorno "
            "(falta DB_APP_PASSWORD o init-sql/01-roles-app.sh no se aplicó "
            "sobre este volumen de Postgres). MARCADO PARA CI: correr contra "
            "el `db` de docker-compose.yml con `.env` completo (ADR-008)."
        )

    engine = sa.create_engine(app_url, pool_pre_ping=True, future=True)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(postgres_engine) -> Session:
    with Session(postgres_engine) as session:
        yield session


@pytest.fixture
def two_tenants_with_data(postgres_engine):
    """
    Crea 2 tenants (A y B) con datos disjuntos (un contacto cada uno) usando
    `postgres_engine` (rol PRIVILEGIADO/owner, ADR-008): a propósito, para
    preparar el fixture, sin fijar `app.tenant_id`.

    CORRECCIÓN (ADR-008, hallazgo BLACK PANTHER en SPEC-025): estos inserts
    "pasan" SIN necesidad de fijar `app.tenant_id` NO porque el owner de la
    tabla esté exento de RLS "salvo que se configure lo contrario" — eso es
    falso y engañoso. La razón real es una regla FIJA del motor: **PostgreSQL
    NUNCA aplica Row Level Security a superusuarios ni a roles con
    `BYPASSRLS`**, ni siquiera con `FORCE ROW LEVEL SECURITY` (`ALTER TABLE
    ... FORCE ROW LEVEL SECURITY` documentado explícitamente así). El owner
    de las tablas aquí es el rol privilegiado que ejecuta Alembic
    (típicamente `postgres`, superusuario), así que este fixture SIEMPRE
    bypasea RLS por diseño (es intencional: así se preparan los datos de
    ambos tenants sin restricción). Para EJERCER el aislamiento de verdad hay
    que usar el fixture `app_engine` (rol `omnicore_app`, NOSUPERUSER
    NOBYPASSRLS) — ver `tests/test_rls_isolation.py` y
    `tests/test_whatsapp_routing.py` para los tests que sí ejercen RLS real.
    """
    tenant_a_id = uuid.uuid4()
    tenant_b_id = uuid.uuid4()
    contact_a_id = uuid.uuid4()
    contact_b_id = uuid.uuid4()

    with postgres_engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO tenants (id, nombre, slug) VALUES " "(:id, :nombre, :slug)"
            ),
            [
                {
                    "id": tenant_a_id,
                    "nombre": "Tenant A",
                    "slug": f"tenant-a-{tenant_a_id.hex[:8]}",
                },
                {
                    "id": tenant_b_id,
                    "nombre": "Tenant B",
                    "slug": f"tenant-b-{tenant_b_id.hex[:8]}",
                },
            ],
        )
        conn.execute(
            sa.text(
                "INSERT INTO contacts (id, tenant_id, nombre, telefono) VALUES "
                "(:id, :tenant_id, :nombre, :telefono)"
            ),
            [
                {
                    "id": contact_a_id,
                    "tenant_id": tenant_a_id,
                    "nombre": "Contacto Confidencial A",
                    "telefono": "3000000001",
                },
                {
                    "id": contact_b_id,
                    "tenant_id": tenant_b_id,
                    "nombre": "Contacto Confidencial B",
                    "telefono": "3000000002",
                },
            ],
        )

    return {
        "tenant_a_id": tenant_a_id,
        "tenant_b_id": tenant_b_id,
        "contact_a_id": contact_a_id,
        "contact_b_id": contact_b_id,
    }


@pytest.fixture
def client():
    """`TestClient` genérico sobre `app.main.app` (importado perezosamente
    para no forzar la carga de la app en tests que no la necesitan)."""
    from app.main import app

    return TestClient(app)


@pytest.fixture
def api_as_tenant(postgres_engine):
    """Devuelve una función `as_tenant(tenant_id, user_email="...")` que
    activa `dependency_overrides` de `get_current_user`/`get_tenant_db` con
    una sesión de Postgres real acotada a ese tenant, usable como context
    manager: `with api_as_tenant(tenant_id): ...peticiones HTTP...`.

    Fixture compartido por `test_api_v1_integration.py` (SPEC-014) y
    `test_privacy_api.py` (SPEC-021, derechos del titular) — centralizado
    aquí para que ambos módulos lo usen sin duplicar código ni recurrir a
    imports cruzados entre módulos de test (que `flake8` marca como F811 al
    confundir el nombre del fixture con una redefinición del import)."""
    from app.api import deps
    from app.db.session import set_tenant_session
    from app.main import app

    class _Activator:
        def __init__(self, tenant_id, user_email):
            self.tenant_id = tenant_id
            self.user_email = user_email

        def __enter__(self):
            def fake_get_current_user():
                return SimpleNamespace(
                    id=uuid.uuid4(),
                    tenant_id=self.tenant_id,
                    email=self.user_email,
                    nombre="Agente de Prueba",
                    rol="agente",
                    activo=True,
                )

            def fake_get_tenant_db():
                with postgres_engine.connect() as conn:
                    with conn.begin():
                        set_tenant_session(conn, str(self.tenant_id))
                        yield conn

            app.dependency_overrides[deps.get_current_user] = fake_get_current_user
            app.dependency_overrides[deps.get_tenant_db] = fake_get_tenant_db
            return self

        def __exit__(self, exc_type, exc, tb):
            app.dependency_overrides.clear()

    def _factory(tenant_id, user_email="agente@tenant.test"):
        return _Activator(tenant_id, user_email)

    return _factory
