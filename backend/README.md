# Backend API — OmniCore AI (Entregable #2 — SPEC-011)

## Visión general

API FastAPI stateless que expone REST + WebSocket para el CRM omnicanal con IA 100% local. Infraestructura base de la Fase F0 del PLAN-002.

## Estructura

```
backend/
├── Dockerfile              # Imagen Docker de la API
├── requirements.txt        # Dependencias Python
├── check-externos-backend.sh  # Auditoría de "cero egress" de IA
├── app/
│   ├── main.py            # Entrada FastAPI (healthz, OpenAPI, placeholders)
│   ├── api/               # Rutas REST (SPEC-014)
│   ├── models/            # Modelos de BD (SQLAlchemy; SPEC-012)
│   ├── schemas/           # Schemas Pydantic (peticiones/respuestas)
│   ├── services/          # Lógica de negocio (RAG, auth, etc.)
│   ├── security/          # JWT, autenticación (SPEC-013)
│   └── utils/             # Utilidades generales
└── tests/                 # Suite de pruebas
    └── test_healthz.py    # Tests de health check
```

## Levantar la infraestructura

### Requisitos previos

- Docker y Docker Compose instalados.
- `.env` configurado (copiar desde `.env.example` y actualizar valores).

### Pasos

1. **Copiar `.env.example` a `.env`:**
   ```bash
   cp ../.env.example ../.env
   ```

2. **Configurar secretos en `.env`** (NUNCA en el código):
   ```bash
   # Editar ../.env con valores reales
   # - DB_PASSWORD: contraseña de PostgreSQL
   # - JWT_SECRET_KEY: clave secreta para JWT
   # Nota: .env está en .gitignore y nunca se commiteará
   ```

3. **Validar `docker-compose.yml`:**
   ```bash
   docker compose config
   ```

4. **Levantar los servicios:**
   ```bash
   docker compose up -d
   ```

5. **Verificar que todo está saludable:**
   ```bash
   # PostgreSQL
   docker compose exec db pg_isready -U postgres
   
   # Redis
   docker compose exec redis redis-cli ping
   
   # Ollama (IA local)
   docker compose exec ia curl http://localhost:11434/api/tags
   
   # API
   curl http://localhost:8000/healthz
   ```

6. **Acceder a OpenAPI:**
   - Swagger UI: `http://localhost:8000/docs`
   - ReDoc: `http://localhost:8000/redoc`
   - OpenAPI JSON: `http://localhost:8000/openapi.json`

## Servicios principales

### PostgreSQL 16 + pgvector
- **Host:** `db:5432`
- **Volumen:** `db_data` (persistencia)
- **Extensión:** `pgvector` habilitada para embeddings
- **RLS:** fuerza aislamiento por `tenant_id` (SPEC-012)

### Redis
- **Host:** `redis:6379`
- **Volumen:** `redis_data` (persistencia con AOF)
- **Uso:** colas de ingesta/indexado, pub/sub WebChat

### Ollama (IA local en red interna)
- **Host interno:** `ia:11434` (NO accesible desde fuera)
- **Red:** `ia_internal` (sin egress a internet)
- **Modelos:** montados en volumen `ollama_models`
- **Variables:** `OLLAMA_MODEL`, `OLLAMA_EMBED_MODEL`
- **Auditoría:** `check-externos-backend.sh` verifica cero egress

### API FastAPI
- **Host:** `0.0.0.0:8000` (dentro del contenedor)
- **Endpoints base:**
  - `GET /healthz` → health check (SPEC-011 RF-02)
  - `GET /docs` → Swagger UI (OpenAPI)
  - `GET /api/v1/tenants` → placeholder (SPEC-014)
  - `GET /api/v1/conversations` → placeholder (SPEC-014)

## Desarrollo

### Instalar dependencias localmente

```bash
python -m venv venv
source venv/bin/activate  # o .venv\Scripts\activate en Windows
pip install -r requirements.txt
```

### Ejecutar tests locales

```bash
pytest tests/ -v --cov=app
```

### Linting

```bash
black app/
flake8 app/
mypy app/ --ignore-missing-imports
```

### Auditar "cero egress" de IA

```bash
bash check-externos-backend.sh .
```

Falla el script si encuentra:
- URLs de APIs de IA externas (OpenAI, Anthropic, Google, etc.)
- SDKs de terceros (openai, anthropic, etc.)
- Importes prohibidos en código Python

## Variables de entorno (`.env`)

Ver `.env.example` para la lista completa. **CRÍTICO:**

- **C3 (Secretos):** `JWT_SECRET_KEY`, `DB_PASSWORD`, etc. NUNCA en el código.
- **C2 (Datos personales):** usar `DATA_RETENTION_DAYS` y borrado lógico (Activo/Inactivo).

## Seguridad

### Red del contenedor IA sin egress
- Contenedor `ia` está en red `ia_internal` con `internal: true`.
- No puede alcanzar internet; solo conecta con la API por red interna.
- Firewall a nivel host (recomendado): DROP saliente del contenedor IA.

### TLS en tránsito (SPEC-021)
- La API FastAPI (`uvicorn`) es **stateless** y **no termina TLS ella misma**
  en este piloto: la terminación HTTPS/WSS es responsabilidad del
  **reverse proxy** que se coloque delante de `api:8000` en el despliegue
  on-prem (QUICKSILVER), p. ej. Nginx/Traefik/Caddy con certificado válido
  (Let's Encrypt o CA interna de la Clínica). El proxy:
  - Redirige/rechaza todo tráfico HTTP plano (fuerza HTTPS).
  - Reenvía a `api:8000` por la red interna de Docker (nunca expone el
    puerto 8000 directamente a internet).
  - Hace terminación WSS para el canal WebChat (`/api/v1/ws-chat`, SPEC-015).
- La API añade `Strict-Transport-Security` (HSTS) y demás cabeceras de
  seguridad (`app/core/security_headers.py`) para que, una vez el proxy
  sirve por HTTPS, el navegador nunca vuelva a intentar HTTP plano con este
  host.
- En `docker-compose.yml` de este piloto (SUP-23, un solo host) el proxy TLS
  NO está incluido como servicio (fuera de alcance de SPEC-021, que es la
  capa de aplicación); se documenta aquí como requisito de despliegue.

### Datos personales (HABEAS DATA/GDPR-like, SPEC-021)
- **Registro de acceso/auditoría:** todo acceso a datos personales de
  contactos (lectura, listado, alta, edición, borrado lógico, exportación,
  anonimización) queda registrado vía `app.core.audit_log` (log estructurado
  JSON, mismo pipeline `structlog` que el resto del backend) con
  `tenant_id`/`user_id`/`resource`/`resource_id`/`action`, correlacionado por
  `request_id` (`app.core.request_id`, cabecera `X-Request-ID`). **Nunca** se
  vuelca el contenido del dato personal ni secretos en el log de auditoría.
- **Derechos del titular:** `GET /api/v1/contacts/{id}/personal-data`
  (exportar) y `POST /api/v1/contacts/{id}/personal-data/erase` (anonimizar +
  borrado lógico) — protegidos por JWT + aislamiento de tenant (RLS,
  ADR-004); ver `app/api/privacy.py`.
- **Retención configurable:** `DATA_RETENTION_DAYS`/`ENABLE_DATA_ANONYMIZATION`
  (`.env`) controlan el job `python -m app.workers.retention_job`
  (`app/services/retention_service.py`), que anonimiza contactos YA
  inactivos vencidos según la política — nunca actúa sobre contactos
  activos ni hace DELETE físico (C2).

### Auditoría
- **CI:** workflow `backend-ci.yml` ejecuta `check-externos-backend.sh` en cada push/PR.
- **Egress test:** HAWKEYE verifica que `curl` desde el contenedor `ia` a dominios externos **falla**.

## Checkpoints aplicables (PROCESO.md)

- **C2 (Borrado lógico):** entidades transaccionales llevan flags Activo/Inactivo.
- **C3 (Secretos):** `.env` en `.gitignore`; `.env.example` sin valores reales.
- **C4 (Criterios verificables):** health check, docker-compose config, `check-externos-backend.sh`.
- **C8 (Origen):** SPEC-011 de PLAN-002.

## Roadmap (SPECs posteriores)

- **SPEC-012:** Modelo de datos (tenants, users, contacts, conversations, messages, documents, embeddings).
- **SPEC-013:** Auth + JWT + multi-tenant RLS.
- **SPEC-014:** API REST core (CRUD de tenants, contactos, conversaciones, mensajes).
- **SPEC-015:** WebChat WebSocket + Redis pub/sub.
- **SPEC-016:** Ollama operativo + embeddings locales.
- **SPEC-017:** Pipeline RAG local (ingesta → chunking → pgvector → top-k → borrador con citas).
- **SPEC-018..SPEC-023:** Sentimiento, human-in-the-loop, SPA integration, seguridad, tests, deploy.

## Estado

- **SPEC-011:** Implementada (infra base + CI).
- **Estado:** EN_VERIFICACION (listo para IRON MAN).

---

**Clasificación:** SENSIBLE (`.no-externo`). Prohibido usar APIs externas de IA o procesamiento de datos personales.
