"""
Engine y sesión de SQLAlchemy + mecanismo de fijación del tenant de sesión
para Row Level Security (ADR-004).

IMPORTANTE (alcance SPEC-012 vs SPEC-013):
- SPEC-012 (esta SPEC) provee el MECANISMO `set_tenant_session()` que ejecuta
  `SET LOCAL app.tenant_id = '<uuid>'` sobre una conexión/transacción.
- La INYECCIÓN automática de ese tenant_id a partir del JWT autenticado en cada
  request es responsabilidad del middleware de auth (SPEC-013, fuera de alcance
  aquí). SPEC-012 solo deja la pieza de infraestructura lista y probada.
"""

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

# `future=True` (comportamiento por defecto en SQLAlchemy 2.x) + pool_pre_ping
# para conexiones resilientes frente a reinicios del contenedor de PostgreSQL.
engine = create_engine(
    settings.sqlalchemy_database_url, pool_pre_ping=True, future=True
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def set_tenant_session(db, tenant_id: str) -> None:
    """
    Fija el `tenant_id` de la sesión de PostgreSQL para la transacción actual.

    Acepta tanto un `sqlalchemy.orm.Session` como una `sqlalchemy.engine.Connection`
    (Core) — ambos exponen `.execute()` con la misma semántica transaccional.

    Usa `SET LOCAL` (no `SET SESSION`): el valor solo vive dentro de la
    transacción en curso y se descarta automáticamente al hacer COMMIT/ROLLBACK,
    evitando fugas de tenant_id entre transacciones que reutilicen la misma
    conexión física (pool de conexiones).

    Las políticas RLS (`app/db/rls.py`) usan
    `current_setting('app.tenant_id', true)::uuid` como predicado.
    """
    db.execute(
        text(f"SET LOCAL {settings.tenant_session_var} = :tenant_id"),
        {"tenant_id": str(tenant_id)},
    )


def clear_tenant_session(db) -> None:
    """Limpia el tenant de sesión (útil en tests y en pool de conexiones reutilizadas)."""
    db.execute(text(f"RESET {settings.tenant_session_var}"))


@contextmanager
def tenant_scoped_session(tenant_id: str) -> Generator[Session, None, None]:
    """
    Context manager que abre una sesión con el `tenant_id` ya fijado (SET LOCAL)
    dentro de una transacción explícita. Pensado para uso en servicios/tests;
    el middleware real de request (SPEC-013) tendrá su propia dependencia FastAPI.
    """
    db = SessionLocal()
    try:
        with db.begin():
            set_tenant_session(db, tenant_id)
            yield db
    finally:
        db.close()


def get_db() -> Generator[Session, None, None]:
    """Dependencia FastAPI genérica (sin tenant fijado). Uso: migraciones/seed/tests."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
