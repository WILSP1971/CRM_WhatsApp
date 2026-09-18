# Ejemplos OpenAPI — OmniCore AI (SPEC-023)

> Colección de ejemplos ejecutables de requests/responses reales para la SPA y consumidores de APIs.
> **IMPORTANTE:** Reemplazar `http://localhost:8000` con `https://app.tudominio.com` en PROD.

## Tabla de contenidos

1. [Health checks](#health-checks)
2. [Autenticación (Login)](#autenticación-login)
3. [Conversaciones](#conversaciones)
4. [Mensajes y WebChat](#mensajes-y-webchat)
5. [Contactos](#contactos)
6. [RAG — Borrador con citas](#rag--borrador-con-citas)
7. [Análisis de sentimiento](#análisis-de-sentimiento)
8. [Derechos de datos personales (HABEAS DATA)](#derechos-de-datos-personales-habeas-data)
9. [Métricas y observabilidad](#métricas-y-observabilidad)
10. [WebSocket: Chat en tiempo real](#websocket-chat-en-tiempo-real)

---

## Health checks

### Health check básico

**Endpoint:** `GET /healthz`

**Descripción:** Verifica que la API está respondiendo.

```bash
curl -X GET http://localhost:8000/healthz
```

**Response (200 OK):**

```json
{
  "status": "ok",
  "timestamp": "2026-09-18T15:30:00Z",
  "version": "1.0.0"
}
```

---

### Readiness check (dependencias)

**Endpoint:** `GET /readyz`

**Descripción:** Verifica que la API y todas sus dependencias (DB, Redis, Ollama) están listas.

```bash
curl -X GET http://localhost:8000/readyz
```

**Response (200 OK):**

```json
{
  "ready": true,
  "timestamp": "2026-09-18T15:30:00Z",
  "dependencies": {
    "db": "ok",
    "redis": "ok",
    "ollama": "ok"
  }
}
```

**Response (503 Service Unavailable) — si una dependencia falla:**

```json
{
  "ready": false,
  "timestamp": "2026-09-18T15:30:00Z",
  "dependencies": {
    "db": "error: connection refused",
    "redis": "ok",
    "ollama": "error: timeout"
  }
}
```

---

## Autenticación (Login)

### Login de usuario (obtener JWT)

**Endpoint:** `POST /api/v1/auth/login`

**Descripción:** Autentica un usuario del tenant y devuelve un token JWT.

```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_slug": "demo",
    "email": "agente@demo.local",
    "password": "contraseña-del-seed"
  }'
```

**Request (JSON):**

```json
{
  "tenant_slug": "demo",
  "email": "agente@demo.local",
  "password": "contraseña-del-seed"
}
```

**Response (200 OK):**

```json
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGc....<TRUNCADO_PARA_DOCUMENTACION>",
  "token_type": "bearer",
  "expires_in": 1800
}
```

**Response (401 Unauthorized) — credenciales incorrectas:**

```json
{
  "detail": "Invalid credentials"
}
```

**Response (429 Too Many Requests) — rate limit excedido:**

```json
{
  "detail": "Too many login attempts. Try again later."
}
```

---

### Verificar token actual (opcional)

**Endpoint:** `GET /api/v1/auth/me`

**Descripción:** Devuelve info del usuario actual (requiere JWT en header).

```bash
curl -X GET http://localhost:8000/api/v1/auth/me \
  -H "Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGc..."
```

**Response (200 OK):**

```json
{
  "id": "4ec9171e-049f-4715-8936-ad6ea46c248a",
  "email": "agente@demo.local",
  "tenant_id": "4ec9171e-049f-4715-8936-ad6ea46c248a",
  "tenant_slug": "demo",
  "roles": ["agent"]
}
```

---

## Conversaciones

### Listar conversaciones del tenant actual

**Endpoint:** `GET /api/v1/conversations`

**Descripción:** Lista todas las conversaciones activas del tenant.

```bash
curl -X GET http://localhost:8000/api/v1/conversations \
  -H "Authorization: Bearer eyJ0eXAi..." \
  -H "Accept: application/json"
```

**Query parameters (opcionales):**
- `skip`: número de items a saltar (default: 0)
- `limit`: número de items a retornar (default: 50, máximo: 100)
- `status`: filtrar por estado (`active`, `closed`)

**Response (200 OK):**

```json
{
  "items": [
    {
      "id": "b1a2c3d4-e5f6-47a8-9f0e-1d2c3b4a5f6e",
      "contact_id": "a1b2c3d4-e5f6-4718-9f0e-1d2c3b4a5f6e",
      "tenant_id": "4ec9171e-049f-4715-8936-ad6ea46c248a",
      "created_at": "2026-09-18T14:00:00Z",
      "updated_at": "2026-09-18T15:30:00Z",
      "subject": "Consulta sobre disponibilidad de stock",
      "status": "active",
      "message_count": 5,
      "last_message_at": "2026-09-18T15:25:00Z",
      "unread_count": 1
    }
  ],
  "total": 1,
  "skip": 0,
  "limit": 50
}
```

---

### Crear una nueva conversación

**Endpoint:** `POST /api/v1/conversations`

**Descripción:** Inicia una nueva conversación con un contacto.

```bash
curl -X POST http://localhost:8000/api/v1/conversations \
  -H "Authorization: Bearer eyJ0eXAi..." \
  -H "Content-Type: application/json" \
  -d '{
    "contact_id": "a1b2c3d4-e5f6-4718-9f0e-1d2c3b4a5f6e",
    "subject": "Nuevo pedido",
    "channel": "webchat"
  }'
```

**Request (JSON):**

```json
{
  "contact_id": "a1b2c3d4-e5f6-4718-9f0e-1d2c3b4a5f6e",
  "subject": "Nuevo pedido",
  "channel": "webchat"
}
```

**Response (201 Created):**

```json
{
  "id": "b1a2c3d4-e5f6-47a8-9f0e-1d2c3b4a5f6e",
  "contact_id": "a1b2c3d4-e5f6-4718-9f0e-1d2c3b4a5f6e",
  "tenant_id": "4ec9171e-049f-4715-8936-ad6ea46c248a",
  "created_at": "2026-09-18T15:35:00Z",
  "subject": "Nuevo pedido",
  "status": "active",
  "message_count": 0,
  "channel": "webchat"
}
```

---

### Obtener detalles de una conversación

**Endpoint:** `GET /api/v1/conversations/{id}`

**Descripción:** Obtiene la conversación y su historial de mensajes.

```bash
curl -X GET "http://localhost:8000/api/v1/conversations/b1a2c3d4-e5f6-47a8-9f0e-1d2c3b4a5f6e" \
  -H "Authorization: Bearer eyJ0eXAi..."
```

**Response (200 OK):**

```json
{
  "id": "b1a2c3d4-e5f6-47a8-9f0e-1d2c3b4a5f6e",
  "contact_id": "a1b2c3d4-e5f6-4718-9f0e-1d2c3b4a5f6e",
  "tenant_id": "4ec9171e-049f-4715-8936-ad6ea46c248a",
  "subject": "Nuevo pedido",
  "status": "active",
  "created_at": "2026-09-18T14:00:00Z",
  "updated_at": "2026-09-18T15:30:00Z",
  "messages": [
    {
      "id": "m1a2b3c4-d5e6-47a8-9f0e-1d2c3b4a5f6e",
      "conversation_id": "b1a2c3d4-e5f6-47a8-9f0e-1d2c3b4a5f6e",
      "sender_role": "customer",
      "content": "¿Tenéis stock de producto X?",
      "sent_at": "2026-09-18T14:05:00Z",
      "sentimiento": "neutral",
      "estado_entrega": "entregado"
    },
    {
      "id": "m2b3c4d5-e6f7-47a8-9f0e-1d2c3b4a5f6e",
      "conversation_id": "b1a2c3d4-e5f6-47a8-9f0e-1d2c3b4a5f6e",
      "sender_role": "agent",
      "content": "Sí, tenemos disponible. El precio es $100.",
      "sent_at": "2026-09-18T14:10:00Z",
      "rag": {
        "citations": [
          {
            "source": "inventario.pdf",
            "excerpt": "Producto X: stock actual 50 unidades",
            "similarityScore": 0.92
          }
        ]
      },
      "estado_entrega": "entregado"
    }
  ]
}
```

---

## Mensajes y WebChat

### Enviar mensaje en una conversación

**Endpoint:** `POST /api/v1/conversations/{conversation_id}/messages`

**Descripción:** Envía un nuevo mensaje en una conversación (desde el agente).

```bash
curl -X POST "http://localhost:8000/api/v1/conversations/b1a2c3d4-e5f6-47a8-9f0e-1d2c3b4a5f6e/messages" \
  -H "Authorization: Bearer eyJ0eXAi..." \
  -H "Content-Type: application/json" \
  -d '{
    "content": "Le enviaré los detalles por email."
  }'
```

**Request (JSON):**

```json
{
  "content": "Le enviaré los detalles por email."
}
```

**Response (201 Created):**

```json
{
  "id": "m3c4d5e6-f7a8-47a8-9f0e-1d2c3b4a5f6e",
  "conversation_id": "b1a2c3d4-e5f6-47a8-9f0e-1d2c3b4a5f6e",
  "sender_role": "agent",
  "content": "Le enviaré los detalles por email.",
  "sent_at": "2026-09-18T15:40:00Z",
  "estado_entrega": "pendiente"
}
```

---

## RAG — Borrador con citas

### Obtener borrador RAG (contexto + generación)

**Endpoint:** `POST /api/v1/rag/draft`

**Descripción:** Genera un borrador de respuesta basado en documentos similares (RAG). Requiere que haya documentos ingestados previo.

```bash
curl -X POST http://localhost:8000/api/v1/rag/draft \
  -H "Authorization: Bearer eyJ0eXAi..." \
  -H "Content-Type: application/json" \
  -d '{
    "conversation_id": "b1a2c3d4-e5f6-47a8-9f0e-1d2c3b4a5f6e",
    "query": "¿Cuál es el precio de producto X?"
  }'
```

**Request (JSON):**

```json
{
  "conversation_id": "b1a2c3d4-e5f6-47a8-9f0e-1d2c3b4a5f6e",
  "query": "¿Cuál es el precio de producto X?"
}
```

**Response (200 OK) — con ≥1 cita:**

```json
{
  "draft": "Según nuestros registros, el precio de producto X es $100. Ofrecemos descuentos por volumen a partir de 10 unidades.",
  "citations": [
    {
      "source": "catalogo.pdf",
      "excerpt": "Producto X: Precio base $100. Descuentos: 10+ unidades -10%, 50+ unidades -20%.",
      "similarityScore": 0.95,
      "page": 5
    },
    {
      "source": "politica_precios.md",
      "excerpt": "Todos los precios incluyen IVA. Válidos hasta 2026-12-31.",
      "similarityScore": 0.87,
      "page": null
    }
  ],
  "generated_at": "2026-09-18T15:42:00Z",
  "latency_ms": 3200
}
```

**Response (404 Not Found) — sin documentos ingestados:**

```json
{
  "detail": "No hay contexto RAG disponible para esta conversación. Ingesta documentos primero."
}
```

---

### Ingestar un documento para RAG

**Endpoint:** `POST /api/v1/documents`

**Descripción:** Sube un documento (PDF, MD, TXT, DOCX) para ingesta asíncrona en RAG.

```bash
curl -X POST http://localhost:8000/api/v1/documents \
  -H "Authorization: Bearer eyJ0eXAi..." \
  -F "file=@catalogo.pdf" \
  -F "title=Catálogo de Productos 2026"
```

**Form data:**
- `file`: archivo (PDF, MD, TXT, DOCX)
- `title`: título descriptivo
- `tags`: (opcional) categorías (ej. "precios, productos")

**Response (202 Accepted) — enviado a cola asíncrona:**

```json
{
  "id": "d4e5f6a7-b8c9-47a8-9f0e-1d2c3b4a5f6e",
  "title": "Catálogo de Productos 2026",
  "filename": "catalogo.pdf",
  "size_bytes": 524288,
  "status": "pending",
  "created_at": "2026-09-18T15:45:00Z",
  "estimated_completion": "2026-09-18T15:48:00Z"
}
```

**Nota:** El documento se ingesta de forma **asíncrona**. El estado pasará de `pending` → `indexing` → `indexed`.

---

## Análisis de sentimiento

### Obtener sentimiento de un mensaje

**Endpoint:** `GET /api/v1/messages/{message_id}/sentiment`

**Descripción:** Devuelve el análisis de sentimiento de un mensaje (clasificado por LLM local).

```bash
curl -X GET "http://localhost:8000/api/v1/messages/m1a2b3c4-d5e6-47a8-9f0e-1d2c3b4a5f6e/sentiment" \
  -H "Authorization: Bearer eyJ0eXAi..."
```

**Response (200 OK):**

```json
{
  "message_id": "m1a2b3c4-d5e6-47a8-9f0e-1d2c3b4a5f6e",
  "sentiment": "positive",
  "confidence": 0.89,
  "labels": {
    "positive": 0.89,
    "neutral": 0.08,
    "negative": 0.03
  },
  "analyzed_at": "2026-09-18T14:06:00Z"
}
```

---

## Derechos de datos personales (HABEAS DATA)

### Exportar datos personales de un contacto

**Endpoint:** `GET /api/v1/contacts/{contact_id}/personal-data/export`

**Descripción:** Exporta TODOS los datos personales de un contacto (HABEAS DATA, GDPR-like).

```bash
curl -X GET "http://localhost:8000/api/v1/contacts/a1b2c3d4-e5f6-4718-9f0e-1d2c3b4a5f6e/personal-data/export" \
  -H "Authorization: Bearer eyJ0eXAi..."
```

**Response (200 OK) — JSON con todos los datos:**

```json
{
  "contact_id": "a1b2c3d4-e5f6-4718-9f0e-1d2c3b4a5f6e",
  "email": "cliente@example.com",
  "phone": "+34-600-123456",
  "name": "Juan García",
  "company": "Acme Corp",
  "conversations": [
    {
      "id": "b1a2c3d4-e5f6-47a8-9f0e-1d2c3b4a5f6e",
      "subject": "Consulta sobre disponibilidad",
      "messages": [...]
    }
  ],
  "export_created_at": "2026-09-18T15:50:00Z"
}
```

---

### Solicitar anonimización de datos

**Endpoint:** `POST /api/v1/contacts/{contact_id}/personal-data/erase`

**Descripción:** Anonimiza un contacto (borrado lógico + enmascaramiento de PII). NO borra físicamente.

```bash
curl -X POST "http://localhost:8000/api/v1/contacts/a1b2c3d4-e5f6-4718-9f0e-1d2c3b4a5f6e/personal-data/erase" \
  -H "Authorization: Bearer eyJ0eXAi..." \
  -H "Content-Type: application/json" \
  -d '{
    "reason": "Derecho al olvido solicitado"
  }'
```

**Request (JSON):**

```json
{
  "reason": "Derecho al olvido solicitado"
}
```

**Response (202 Accepted) — enmascaramiento asíncrono:**

```json
{
  "contact_id": "a1b2c3d4-e5f6-4718-9f0e-1d2c3b4a5f6e",
  "status": "erase_pending",
  "reason": "Derecho al olvido solicitado",
  "requested_at": "2026-09-18T15:52:00Z",
  "estimated_completion": "2026-09-18T15:53:00Z"
}
```

---

## Contactos

### Listar contactos del tenant

**Endpoint:** `GET /api/v1/contacts`

**Descripción:** Lista todos los contactos activos del tenant.

```bash
curl -X GET http://localhost:8000/api/v1/contacts \
  -H "Authorization: Bearer eyJ0eXAi..." \
  -H "Accept: application/json"
```

**Query parameters (opcionales):**
- `skip`: default 0
- `limit`: default 50, máximo 100
- `search`: filtrar por nombre/email

**Response (200 OK):**

```json
{
  "items": [
    {
      "id": "a1b2c3d4-e5f6-4718-9f0e-1d2c3b4a5f6e",
      "name": "Juan García",
      "email": "juan@example.com",
      "phone": "+34-600-123456",
      "company": "Acme Corp",
      "created_at": "2026-09-10T10:00:00Z",
      "conversation_count": 3,
      "last_interaction": "2026-09-18T15:25:00Z",
      "sentiment_trend": "positive"
    }
  ],
  "total": 1,
  "skip": 0,
  "limit": 50
}
```

---

### Crear un nuevo contacto

**Endpoint:** `POST /api/v1/contacts`

**Descripción:** Registra un nuevo contacto en el tenant.

```bash
curl -X POST http://localhost:8000/api/v1/contacts \
  -H "Authorization: Bearer eyJ0eXAi..." \
  -H "Content-Type: application/json" \
  -d '{
    "name": "María López",
    "email": "maria@example.com",
    "phone": "+34-600-654321",
    "company": "XYZ Inc"
  }'
```

**Request (JSON):**

```json
{
  "name": "María López",
  "email": "maria@example.com",
  "phone": "+34-600-654321",
  "company": "XYZ Inc"
}
```

**Response (201 Created):**

```json
{
  "id": "c2d3e4f5-a6b7-4718-9f0e-1d2c3b4a5f6e",
  "name": "María López",
  "email": "maria@example.com",
  "phone": "+34-600-654321",
  "company": "XYZ Inc",
  "created_at": "2026-09-18T15:55:00Z",
  "is_active": true
}
```

---

## Métricas y observabilidad

### Obtener métricas Prometheus

**Endpoint:** `GET /metrics`

**Descripción:** Expone métricas en formato Prometheus/OpenMetrics.

```bash
curl -s http://localhost:8000/metrics | head -40
```

**Response (200 OK) — formato Prometheus:**

```
# HELP http_request_duration_seconds HTTP request latency in seconds
# TYPE http_request_duration_seconds histogram
http_request_duration_seconds_bucket{method="GET",path="/api/v1/contacts",le="0.005"} 45.0
http_request_duration_seconds_bucket{method="GET",path="/api/v1/contacts",le="0.01"} 98.0
http_request_duration_seconds_bucket{method="GET",path="/api/v1/contacts",le="0.05"} 502.0
http_request_duration_seconds_bucket{method="GET",path="/api/v1/contacts",le="0.1"} 998.0
http_request_duration_seconds_bucket{method="GET",path="/api/v1/contacts",le="0.5"} 1000.0

# HELP ai_request_duration_seconds AI inference request latency in seconds
# TYPE ai_request_duration_seconds histogram
ai_request_duration_seconds_bucket{operation="chat",le="1"} 2.0
ai_request_duration_seconds_bucket{operation="chat",le="6"} 85.0
ai_request_duration_seconds_bucket{operation="chat",le="30"} 86.0
ai_request_duration_seconds_bucket{operation="embed",le="0.1"} 500.0
```

**Query en Prometheus/Grafana:**

```
# p95 latencia REST
histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))

# p95 latencia RAG (IA)
histogram_quantile(0.95, rate(ai_request_duration_seconds_bucket{operation="chat"}[5m]))
```

---

## WebSocket: Chat en tiempo real

### Conectar al WebSocket de chat

**Endpoint:** `WebSocket ws://localhost:8000/api/v1/ws-chat`

**Descripción:** Conexión WebSocket bidireccional para chat en tiempo real (cliente ↔ agente).

```javascript
// Ejemplo en JavaScript/TypeScript
const conversationId = "b1a2c3d4-e5f6-47a8-9f0e-1d2c3b4a5f6e";
const token = "eyJ0eXAi..."; // JWT del cliente

const ws = new WebSocket(
  `ws://localhost:8000/api/v1/ws-chat?conversation_id=${conversationId}&token=${token}`
);

ws.onopen = () => {
  console.log("Conectado a WebSocket");
  
  // Enviar mensaje del cliente
  ws.send(JSON.stringify({
    type: "message",
    content: "¿Cuál es el precio de producto X?",
    sender_role: "customer"
  }));
};

ws.onmessage = (event) => {
  const message = JSON.parse(event.data);
  console.log("Mensaje recibido:", message);
  
  // Ejemplo:
  // {
  //   "id": "m5f6a7b8-c9d0-47a8-9f0e-1d2c3b4a5f6e",
  //   "type": "message",
  //   "sender_role": "agent",
  //   "content": "El precio es $100.",
  //   "estado_entrega": "entregado",
  //   "timestamp": "2026-09-18T15:58:00Z"
  // }
};

ws.onerror = (error) => {
  console.error("Error WebSocket:", error);
};

ws.onclose = () => {
  console.log("WebSocket cerrado");
};
```

**Protocolo WebSocket (messages):**

| Tipo | Descripción | Payload |
|---|---|---|
| `message` | Nuevo mensaje en conversación | `{ "content": "...", "sender_role": "customer\|agent" }` |
| `typing` | Usuario escribiendo | `{ "user_id": "..." }` |
| `delivered` | Confirmación de entrega | `{ "message_id": "...", "estado_entrega": "entregado" }` |
| `status` | Cambio de estado de conversación | `{ "status": "active\|closed" }` |

---

## Notas de implementación

### Autenticación en todos los endpoints (excepto `/healthz`, `/readyz`)

```bash
# SIEMPRE incluir header Authorization
-H "Authorization: Bearer <JWT_TOKEN>"
```

### Manejo de errores estándar

```json
{
  "detail": "Error message",
  "request_id": "a1b2c3d4",
  "timestamp": "2026-09-18T15:58:00Z"
}
```

**Status codes comunes:**
- `200 OK`: Éxito
- `201 Created`: Recurso creado
- `202 Accepted`: Operación asíncrona encolada
- `400 Bad Request`: Validación fallida
- `401 Unauthorized`: Token faltante o inválido
- `403 Forbidden`: No tienes permiso (ej. cross-tenant)
- `404 Not Found`: Recurso no existe
- `429 Too Many Requests`: Rate limit excedido
- `503 Service Unavailable`: Dependencia caída (BD, Redis, Ollama)

### URLs en producción

Reemplazar `http://localhost:8000` con `https://app.tudominio.com`:

```bash
# DEV
curl http://localhost:8000/api/v1/contacts

# PROD
curl https://app.tudominio.com/api/v1/contacts
```

---

## Cliente OpenAPI (Swagger UI)

Acceder a la interfaz interactiva en:

```
http://localhost:8000/docs    (Swagger UI)
http://localhost:8000/redoc   (ReDoc)
http://localhost:8000/openapi.json  (especificación OpenAPI JSON)
```

---

**Última actualización:** 2026-09-18 · Versión: 1.0.0

Referencia: SPEC-014 (API REST core), SPEC-015 (WebChat WebSocket), SPEC-017 (RAG local), SPEC-023 (Documentación).
