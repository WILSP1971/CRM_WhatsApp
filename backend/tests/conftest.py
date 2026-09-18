"""
Fixtures compartidos de pytest para tests de integración contra PostgreSQL real
(SPEC-012). Estos tests requieren el `db` del `docker-compose.yml` del proyecto
(PostgreSQL 16 + pgvector) arriba y accesible vía `DATABASE_URL`.

Si `DATABASE_URL` no apunta a un Postgres accesible, los tests que dependen de
este fixture se SKIPEAN automáticamente (no fallan) para no romper el resto de
la suite en entornos sin Docker (p.ej. este sandbox de implementación).
"""

import os
import uuid
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _database_url() -> str:
    return os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://postgres:postgres@localhost:5432/omnicore_ai_test",
    )


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
    Motor conectado a PostgreSQL real con el esquema de SPEC-012 aplicado
    (`alembic upgrade head`). Si no hay Postgres accesible, se saltan los
    tests que dependan de este fixture (se documenta en el resumen de
    ejecución, no se marcan como aprobados en falso).
    """
    if not _postgres_available(database_url):
        pytest.skip(
            "PostgreSQL no accesible en este entorno (sin daemon Docker/DB real). "
            "Este test corre en CI contra el `db` del docker-compose.yml (SPEC-012)."
        )

    alembic_cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    alembic_cfg.set_main_option("script_location", os.path.join(BACKEND_DIR, "alembic"))
    os.environ["DATABASE_URL"] = database_url
    command.upgrade(alembic_cfg, "head")

    engine = sa.create_engine(database_url, pool_pre_ping=True, future=True)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(postgres_engine) -> Session:
    with Session(postgres_engine) as session:
        yield session


@pytest.fixture
def two_tenants_with_data(postgres_engine):
    """
    Crea 2 tenants (A y B) con datos disjuntos (un contacto cada uno) fuera de
    cualquier RLS de sesión (usando el rol de owner de la migración, que por
    defecto NO está sujeto a FORCE RLS al ser el dueño de la tabla salvo que se
    configure lo contrario — aquí insertamos vía `session.begin()` sin fijar
    `app.tenant_id`, como owner de BD de test, para preparar el fixture).
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
