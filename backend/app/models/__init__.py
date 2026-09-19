"""
Modelos ORM del dominio OmniCore AI (SPEC-012).

Importar todos los módulos aquí garantiza que `Base.metadata` los conozca
antes de que Alembic autogenere/valide migraciones.
"""

from app.models.tenant import Tenant  # noqa: F401
from app.models.user import User  # noqa: F401
from app.models.contact import Contact  # noqa: F401
from app.models.conversation import Conversation  # noqa: F401
from app.models.message import Message  # noqa: F401
from app.models.document import Document  # noqa: F401
from app.models.chunk import Chunk  # noqa: F401
from app.models.embedding import Embedding  # noqa: F401
from app.models.rag_draft import RagDraft  # noqa: F401
from app.models.whatsapp_account import WhatsappAccount  # noqa: F401

__all__ = [
    "Tenant",
    "User",
    "Contact",
    "Conversation",
    "Message",
    "Document",
    "Chunk",
    "Embedding",
    "RagDraft",
    "WhatsappAccount",
]
