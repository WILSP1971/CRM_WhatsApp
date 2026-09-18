"""esquema multi-tenant inicial + RLS + pgvector

SPEC-012 — Modelo de datos multi-tenant, migraciones, RLS FORCE por tenant_id,
borrado lógico (C2) y pgvector.

Revision ID: 192207b090b0
Revises:
Create Date: 2026-09-18 00:38:21.915710
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

from app.db.rls import TENANT_SCOPED_TABLES, disable_rls_sql, enable_rls_sql
from app.models.embedding import EMBEDDING_DIM

# revision identifiers, used by Alembic.
revision: str = "192207b090b0"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _audit_columns():
    """Columnas de auditoría comunes a toda entidad transaccional (C2)."""
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.String(length=255), nullable=True),
    ]


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Extensiones requeridas
    # ------------------------------------------------------------------
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")  # gen_random_uuid()
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")  # pgvector

    # ------------------------------------------------------------------
    # tenants (raíz; NO lleva tenant_id ni RLS por fila)
    # ------------------------------------------------------------------
    op.create_table(
        "tenants",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("nombre", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        *_audit_columns(),
        sa.UniqueConstraint("slug", name="uq_tenants_slug"),
    )
    op.create_index("ix_tenants_slug", "tenants", ["slug"])
    op.create_index("ix_tenants_activo", "tenants", ["activo"])

    # ------------------------------------------------------------------
    # users
    # ------------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("nombre", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("rol", sa.String(length=50), nullable=False, server_default="agente"),
        *_audit_columns(),
        sa.UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
    )
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])
    op.create_index("ix_users_email", "users", ["email"])
    op.create_index("ix_users_activo", "users", ["activo"])

    # ------------------------------------------------------------------
    # contacts
    # ------------------------------------------------------------------
    op.create_table(
        "contacts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("nombre", sa.String(length=255), nullable=False),
        sa.Column("telefono", sa.String(length=50), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        *_audit_columns(),
        sa.UniqueConstraint(
            "tenant_id", "telefono", name="uq_contacts_tenant_telefono"
        ),
    )
    op.create_index("ix_contacts_tenant_id", "contacts", ["tenant_id"])
    op.create_index("ix_contacts_activo", "contacts", ["activo"])

    # ------------------------------------------------------------------
    # conversations
    # ------------------------------------------------------------------
    op.create_table(
        "conversations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "contact_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("contacts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "canal", sa.String(length=50), nullable=False, server_default="webchat"
        ),
        sa.Column(
            "estado", sa.String(length=50), nullable=False, server_default="abierta"
        ),
        *_audit_columns(),
    )
    op.create_index("ix_conversations_tenant_id", "conversations", ["tenant_id"])
    op.create_index("ix_conversations_contact_id", "conversations", ["contact_id"])
    op.create_index("ix_conversations_activo", "conversations", ["activo"])

    # ------------------------------------------------------------------
    # messages
    # ------------------------------------------------------------------
    op.create_table(
        "messages",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("remitente", sa.String(length=20), nullable=False),
        sa.Column("contenido", sa.Text(), nullable=False),
        sa.Column("sentimiento", sa.String(length=20), nullable=True),
        *_audit_columns(),
    )
    op.create_index("ix_messages_tenant_id", "messages", ["tenant_id"])
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])
    op.create_index("ix_messages_activo", "messages", ["activo"])

    # ------------------------------------------------------------------
    # documents (RAG)
    # ------------------------------------------------------------------
    op.create_table(
        "documents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("nombre_archivo", sa.String(length=500), nullable=False),
        sa.Column("tipo", sa.String(length=20), nullable=False),
        sa.Column(
            "estado", sa.String(length=20), nullable=False, server_default="pendiente"
        ),
        *_audit_columns(),
    )
    op.create_index("ix_documents_tenant_id", "documents", ["tenant_id"])
    op.create_index("ix_documents_activo", "documents", ["activo"])

    # ------------------------------------------------------------------
    # chunks (RAG)
    # ------------------------------------------------------------------
    op.create_table(
        "chunks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("orden", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("contenido", sa.Text(), nullable=False),
        *_audit_columns(),
    )
    op.create_index("ix_chunks_tenant_id", "chunks", ["tenant_id"])
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"])
    op.create_index("ix_chunks_activo", "chunks", ["activo"])

    # ------------------------------------------------------------------
    # embeddings (RAG, pgvector)
    # ------------------------------------------------------------------
    op.create_table(
        "embeddings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "chunk_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chunks.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "vector", sa.String(), nullable=False
        ),  # placeholder; se altera abajo a vector(N)
        *_audit_columns(),
    )
    # `pgvector.sqlalchemy.Vector` no siempre resuelve limpio con create_table
    # en offline SQL; se define la columna con tipo `vector(N)` directamente
    # vía SQL crudo para máxima compatibilidad con `--sql` (modo offline).
    op.execute("ALTER TABLE embeddings DROP COLUMN vector;")
    op.execute(
        f"ALTER TABLE embeddings ADD COLUMN vector vector({EMBEDDING_DIM}) NOT NULL;"
    )

    op.create_index("ix_embeddings_tenant_id", "embeddings", ["tenant_id"])
    op.create_index("ix_embeddings_chunk_id", "embeddings", ["chunk_id"])
    op.create_index("ix_embeddings_activo", "embeddings", ["activo"])

    # Índice vectorial HNSW para recuperación top-k (RNF: p95 <= 300ms, SPEC-017/022).
    # cosine ops: coherente con embeddings normalizados de nomic-embed-text.
    op.execute(
        "CREATE INDEX ix_embeddings_vector_hnsw ON embeddings "
        "USING hnsw (vector vector_cosine_ops);"
    )

    # ------------------------------------------------------------------
    # Row Level Security — ADR-004 (ENABLE + FORCE por tenant_id)
    # ------------------------------------------------------------------
    for table in TENANT_SCOPED_TABLES:
        for statement in enable_rls_sql(table):
            op.execute(statement)


def downgrade() -> None:
    # Revertir RLS antes de dropear tablas.
    for table in reversed(TENANT_SCOPED_TABLES):
        for statement in disable_rls_sql(table):
            op.execute(statement)

    op.execute("DROP INDEX IF EXISTS ix_embeddings_vector_hnsw;")

    op.drop_table("embeddings")
    op.drop_table("chunks")
    op.drop_table("documents")
    op.drop_table("messages")
    op.drop_table("conversations")
    op.drop_table("contacts")
    op.drop_table("users")
    op.drop_table("tenants")

    # No se dropean las extensiones (pueden ser usadas por otros esquemas/DBs).
