"""
Alembic environment — OmniCore AI backend (SPEC-012).

CHECKPOINT C3 (secretos): la cadena de conexión se toma de la variable de
entorno `DATABASE_URL` (o de las variables `DB_*` individuales vía
`app.core.config.Settings`), NUNCA de un valor hardcodeado en `alembic.ini`.
"""

import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# Permite `import app...` al ejecutar alembic desde `backend/`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import get_settings  # noqa: E402
from app.db.base import Base  # noqa: E402
import app.models  # noqa: F401,E402  (registra todos los modelos en Base.metadata)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Fuente de verdad del esquema para autogenerate/validación.
target_metadata = Base.metadata

# Sobreescribe sqlalchemy.url con la URL real desde variables de entorno (C3).
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.sqlalchemy_database_url)


def run_migrations_offline() -> None:
    """Modo offline: emite SQL sin necesitar conexión real a la BD.

    Usado para validar que las migraciones generan SQL correcto sin requerir
    un servidor PostgreSQL disponible (ver `scripts/alembic_sql_check.sh`).
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Modo online: aplica las migraciones contra una conexión real."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
