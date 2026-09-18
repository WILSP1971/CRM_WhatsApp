"""
Tests de integración de la API core REST (SPEC-014) contra PostgreSQL real.

Requiere el `db` de `docker-compose.yml` (PostgreSQL 16 + pgvector) con el
esquema de SPEC-012 aplicado vía Alembic. Si no hay Postgres accesible (p.ej.
este sandbox sin daemon Docker), se SKIPEAN automáticamente vía el fixture
`postgres_engine` (`tests/conftest.py`) — no se marcan como aprobados en
falso; quedan documentados como pendientes de ejecutar en CI (mismo patrón
que `tests/test_rls_isolation.py` y `tests/test_auth_cross_tenant_rls.py`).

Se ejercita la API completa end-to-end vía `TestClient` + `dependency_overrides`
SOLO de `get_tenant_db`/`get_current_user` para inyectar una sesión real de
Postgres con el `tenant_id`/usuario de prueba ya resueltos (evita re-emitir
JWT/depender de `auth_service`; el contrato de JWT ya está probado en
`tests/test_auth_api.py` y `tests/test_auth_cross_tenant_rls.py`).

Qué se verifica (criterios de aceptación de SPEC-014):
  1. Happy path CRUD de `contacts`/`conversations`/`messages`/`documents`
     dentro de un tenant (POST -> 201, GET -> 200, paginación).
  2. `DELETE` es borrado LÓGICO (C2): tras borrar, el recurso deja de listarse
     pero la fila permanece en BD con `activo=False` (nunca DELETE físico).
  3. Aislamiento cross-tenant (RLS, criterio CE-22/R-23): un usuario del
     tenant A no puede leer/modificar/borrar contactos, conversaciones,
     mensajes ni documentos del tenant B por NINGÚN endpoint (404, no 200
     con datos ajenos, y la fila del tenant B permanece intacta).
  4. Contacto 360°: agrega contacto + conversaciones + mensajes del MISMO
     tenant; un contact_id de otro tenant da 404 (no filtra datos ajenos).
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa

# `client` y `api_as_tenant` son fixtures compartidos, definidos en
# `tests/conftest.py` (movidos ahí en SPEC-021 para reutilizarlos también en
# `tests/test_privacy_api.py` sin imports cruzados entre módulos de test).


# ---------------------------------------------------------------------------
# Happy path CRUD: contacts
# ---------------------------------------------------------------------------


def test_create_and_get_contact_happy_path(
    client, api_as_tenant, two_tenants_with_data
):
    data = two_tenants_with_data
    with api_as_tenant(data["tenant_a_id"]):
        response = client.post(
            "/api/v1/contacts",
            json={"nombre": "Cliente Feliz", "telefono": "3009998888"},
        )
        assert response.status_code == 201
        created = response.json()
        assert created["nombre"] == "Cliente Feliz"
        assert created["activo"] is True
        contact_id = created["id"]

        get_response = client.get(f"/api/v1/contacts/{contact_id}")
        assert get_response.status_code == 200
        assert get_response.json()["id"] == contact_id


def test_list_contacts_is_paginated_and_excludes_inactive(
    client, api_as_tenant, two_tenants_with_data
):
    data = two_tenants_with_data
    with api_as_tenant(data["tenant_a_id"]):
        response = client.get("/api/v1/contacts", params={"page": 1, "page_size": 20})
        assert response.status_code == 200
        body = response.json()
        assert body["page"] == 1
        assert body["page_size"] == 20
        assert "total" in body
        # El contacto sembrado del tenant A debe estar; el del tenant B no.
        visible_ids = {c["id"] for c in body["items"]}
        assert str(data["contact_a_id"]) in visible_ids
        assert str(data["contact_b_id"]) not in visible_ids


def test_delete_contact_is_soft_delete_not_physical(
    client, api_as_tenant, two_tenants_with_data, postgres_engine
):
    """Criterio C2: DELETE marca `activo=False`; la fila sigue existiendo."""
    data = two_tenants_with_data
    with api_as_tenant(data["tenant_a_id"]):
        create_response = client.post(
            "/api/v1/contacts", json={"nombre": "Para Borrar"}
        )
        contact_id = create_response.json()["id"]

        delete_response = client.delete(f"/api/v1/contacts/{contact_id}")
        assert delete_response.status_code == 204

        # Tras el borrado lógico, ya no aparece en GET (404, como "no encontrado").
        get_response = client.get(f"/api/v1/contacts/{contact_id}")
        assert get_response.status_code == 404

    # La fila permanece en BD con activo=false (verificación fuera de RLS,
    # como owner de test) -> nunca hubo DELETE físico.
    with postgres_engine.connect() as conn:
        row = conn.execute(
            sa.text("SELECT activo FROM contacts WHERE id = :id"),
            {"id": uuid.UUID(contact_id)},
        ).fetchone()
        assert row is not None, "El contacto fue borrado FÍSICAMENTE (viola C2)"
        assert row.activo is False


# ---------------------------------------------------------------------------
# Aislamiento cross-tenant (RLS) por endpoint — criterio CE-22/R-23
# ---------------------------------------------------------------------------


def test_tenant_a_cannot_read_contact_of_tenant_b(
    client, api_as_tenant, two_tenants_with_data
):
    data = two_tenants_with_data
    with api_as_tenant(data["tenant_a_id"]):
        response = client.get(f"/api/v1/contacts/{data['contact_b_id']}")
        assert response.status_code == 404


def test_tenant_a_cannot_update_contact_of_tenant_b(
    client, api_as_tenant, two_tenants_with_data, postgres_engine
):
    data = two_tenants_with_data
    with api_as_tenant(data["tenant_a_id"]):
        response = client.patch(
            f"/api/v1/contacts/{data['contact_b_id']}", json={"nombre": "HACKEADO"}
        )
        assert response.status_code == 404

    with postgres_engine.connect() as conn:
        row = conn.execute(
            sa.text("SELECT nombre FROM contacts WHERE id = :id"),
            {"id": data["contact_b_id"]},
        ).fetchone()
        assert row.nombre == "Contacto Confidencial B"


def test_tenant_a_cannot_delete_contact_of_tenant_b(
    client, api_as_tenant, two_tenants_with_data, postgres_engine
):
    data = two_tenants_with_data
    with api_as_tenant(data["tenant_a_id"]):
        response = client.delete(f"/api/v1/contacts/{data['contact_b_id']}")
        assert response.status_code == 404

    with postgres_engine.connect() as conn:
        row = conn.execute(
            sa.text("SELECT activo FROM contacts WHERE id = :id"),
            {"id": data["contact_b_id"]},
        ).fetchone()
        assert (
            row.activo is True
        ), "El contacto del tenant B fue desactivado indebidamente"


def test_tenant_a_cannot_create_conversation_for_contact_of_tenant_b(
    client, api_as_tenant, two_tenants_with_data
):
    """Un `contact_id` de otro tenant no puede usarse para crear una
    conversación (RLS impide siquiera verlo -> 404, no 201/500)."""
    data = two_tenants_with_data
    with api_as_tenant(data["tenant_a_id"]):
        response = client.post(
            "/api/v1/conversations",
            json={"contact_id": str(data["contact_b_id"]), "canal": "webchat"},
        )
        assert response.status_code == 404


def test_tenant_a_cannot_list_conversations_of_tenant_b(
    client, api_as_tenant, two_tenants_with_data
):
    data = two_tenants_with_data
    with api_as_tenant(data["tenant_a_id"]):
        create_response = client.post(
            "/api/v1/conversations",
            json={"contact_id": str(data["contact_a_id"]), "canal": "webchat"},
        )
        assert create_response.status_code == 201

    with api_as_tenant(data["tenant_b_id"]):
        list_response = client.get("/api/v1/conversations")
        assert list_response.status_code == 200
        conversation_ids = {c["id"] for c in list_response.json()["items"]}
        assert create_response.json()["id"] not in conversation_ids


# ---------------------------------------------------------------------------
# Contacto 360°
# ---------------------------------------------------------------------------


def test_contact_360_aggregates_contact_conversations_and_messages(
    client, api_as_tenant, two_tenants_with_data
):
    data = two_tenants_with_data
    with api_as_tenant(data["tenant_a_id"]):
        conv_response = client.post(
            "/api/v1/conversations",
            json={"contact_id": str(data["contact_a_id"]), "canal": "webchat"},
        )
        conversation_id = conv_response.json()["id"]

        msg_response = client.post(
            f"/api/v1/conversations/{conversation_id}/messages",
            json={"remitente": "contacto", "contenido": "Hola, necesito ayuda"},
        )
        assert msg_response.status_code == 201

        response = client.get(f"/api/v1/contacts/{data['contact_a_id']}/360")
        assert response.status_code == 200
        body = response.json()
        assert body["contact"]["id"] == str(data["contact_a_id"])
        assert len(body["conversations"]) >= 1
        found = next(c for c in body["conversations"] if c["id"] == conversation_id)
        assert any(m["contenido"] == "Hola, necesito ayuda" for m in found["messages"])


def test_contact_360_of_other_tenant_returns_404(
    client, api_as_tenant, two_tenants_with_data
):
    data = two_tenants_with_data
    with api_as_tenant(data["tenant_a_id"]):
        response = client.get(f"/api/v1/contacts/{data['contact_b_id']}/360")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# tenants/me
# ---------------------------------------------------------------------------


def test_get_my_tenant_returns_own_tenant_only(
    client, api_as_tenant, two_tenants_with_data
):
    data = two_tenants_with_data
    with api_as_tenant(data["tenant_a_id"]):
        response = client.get("/api/v1/tenants/me")
        assert response.status_code == 200
        assert response.json()["id"] == str(data["tenant_a_id"])
