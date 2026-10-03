"""
Configuración central de la aplicación — OmniCore AI backend (SPEC-012).

CHECKPOINT C3 (secretos): toda credencial/cadena de conexión se lee EXCLUSIVAMENTE
de variables de entorno (`.env` vía docker-compose o entorno del proceso). Nunca se
hardcodea un valor real en el código fuente; los valores por defecto aquí son
únicamente para desarrollo local y NO son secretos de producción.
"""

import os
from functools import lru_cache

# CHECKPOINT C3 (BLACK WIDOW, SPEC-013): valores de secretos débiles/genéricos
# que NUNCA deben aceptarse fuera de `development` (fail-fast en `Settings`).
_WEAK_SECRET_VALUES = {
    "",
    "changeme",
    "change-me",
    "dev-only-change-me",
    "secret",
    "postgres",
}
_MIN_SECRET_LENGTH = 32


class ConfigurationError(RuntimeError):
    """Configuración insegura para el entorno actual (fail-fast al arrancar)."""


class Settings:
    """Lee la configuración desde variables de entorno (C3: sin secretos en claro)."""

    def __init__(self) -> None:
        self.environment: str = os.getenv("ENVIRONMENT", "development")
        self._is_development = self.environment.strip().lower() == "development"

        # --- Base de datos (PostgreSQL 16 + pgvector) ---
        self.db_host: str = os.getenv("DB_HOST", "localhost")
        self.db_port: str = os.getenv("DB_PORT", "5432")
        self.db_name: str = os.getenv("DB_NAME", "omnicore_ai")
        self.db_user: str = os.getenv("DB_USER", "postgres")
        self.db_password: str = self._require_strong_secret(
            "DB_PASSWORD", os.getenv("DB_PASSWORD"), dev_default="postgres"
        )

        # DATABASE_URL explícita tiene prioridad (permite override total desde env/secret manager).
        self.database_url: str = os.getenv(
            "DATABASE_URL",
            f"postgresql+psycopg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}",
        )

        # --- Rol privilegiado para DDL/migraciones (ADR-008) ---
        # `DATABASE_URL`/`DB_USER` de arriba son el rol de RUNTIME de la app
        # (api/workers): `omnicore_app`, NOSUPERUSER/NOBYPASSRLS, para que RLS
        # (ADR-004) se aplique de verdad. Alembic (DDL: CREATE/ALTER/DROP) NO
        # puede correr con ese rol -> usa un rol PRIVILEGIADO separado
        # (owner del esquema, por defecto `postgres`), configurado con estas
        # variables independientes. Si `DATABASE_URL_MIGRATIONS` no está
        # definida, se arma a partir de `DB_MIGRATION_USER`/
        # `DB_MIGRATION_PASSWORD` (por defecto el mismo `DB_PASSWORD`, para no
        # romper entornos de desarrollo que aún no separaron credenciales).
        self.db_migration_user: str = os.getenv("DB_MIGRATION_USER", "postgres")
        self.db_migration_password: str = os.getenv(
            "DB_MIGRATION_PASSWORD", self.db_password
        )
        self.database_url_migrations: str = os.getenv(
            "DATABASE_URL_MIGRATIONS",
            f"postgresql+psycopg://{self.db_migration_user}:{self.db_migration_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}",
        )

        # --- Multi-tenant / RLS (ADR-004) ---
        # Nombre del parámetro de sesión de PostgreSQL que las políticas RLS usan
        # como predicado (SET LOCAL app.tenant_id = '<uuid>').
        self.tenant_session_var: str = os.getenv("TENANT_SESSION_VAR", "app.tenant_id")

        # --- Autenticación / JWT (SPEC-013) ---
        # CHECKPOINT C3 (BLACK WIDOW): sin default inseguro. Fuera de
        # `development`, el arranque ABORTA si `JWT_SECRET_KEY` falta o es
        # débil (< 32 caracteres o en la lista negra) — un secreto conocido
        # permitiría forjar tokens y hacer bypass de RLS (ADR-004).
        self.jwt_secret_key: str = self._require_strong_secret(
            "JWT_SECRET_KEY",
            os.getenv("JWT_SECRET_KEY"),
            dev_default="dev-only-change-me",
        )
        self.jwt_algorithm: str = os.getenv("JWT_ALGORITHM", "HS256")
        self.jwt_access_token_expire_minutes: int = int(
            os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "30")
        )

        # --- Rate-limit de login (SPEC-013 RF, mitigación de fuerza bruta) ---
        self.login_rate_limit_max_attempts: int = int(
            os.getenv("LOGIN_RATE_LIMIT_MAX_ATTEMPTS", "5")
        )
        self.login_rate_limit_window_seconds: int = int(
            os.getenv("LOGIN_RATE_LIMIT_WINDOW_SECONDS", "300")
        )
        # Fuera de development, por defecto se exige Redis real para el
        # rate-limit (evita degradar silenciosamente a memoria per-worker en
        # producción); en development degrada con warning (ver rate_limit.py).
        self.login_rate_limit_strict_redis: bool = os.getenv(
            "LOGIN_RATE_LIMIT_STRICT_REDIS",
            "false" if self._is_development else "true",
        ).strip().lower() in ("1", "true", "yes")

        # --- Redis (usado por el rate-limit de login; SPEC-011 ya lo define) ---
        self.redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379")

        # --- Rate-limiting GENERAL de API por IP/endpoint (SPEC-081, PLAN-011
        # F1, CAPA 2 — complementa, NUNCA sustituye, al `LoginRateLimiter` de
        # arriba) ---
        # `GENERAL_RATE_LIMIT_DEFAULT`: límite por defecto aplicado a
        # cualquier endpoint REST que no declare uno propio (RF-01/RF-05).
        self.general_rate_limit_default: str = os.getenv(
            "GENERAL_RATE_LIMIT_DEFAULT", "60/minute"
        )
        # `GENERAL_RATE_LIMIT_RAG_DRAFT`: límite específico de `/rag/draft`
        # (RF-01) — más bajo que el default porque invoca el LLM local en el
        # camino síncrono de la petición (protege la cola de inferencia
        # compartida, R-103).
        self.general_rate_limit_rag_draft: str = os.getenv(
            "GENERAL_RATE_LIMIT_RAG_DRAFT", "20/minute"
        )
        # `GENERAL_RATE_LIMIT_WEBHOOK`: umbral HOLGADO específico para los
        # webhooks públicos de WhatsApp/PBX (RF-03, R-105 — el riesgo TOP de
        # esta SPEC): ambos SOLO validan firma HMAC + encolan (coste
        # bajísimo por petición), y pueden recibir ráfagas legítimas (lotes/
        # reintentos de Meta, varias grabaciones casi simultáneas del PBX en
        # hora pico). 300/minuto (5/s sostenido) por IP queda muy por encima
        # de cualquier ráfaga legítima razonable sin dejar el endpoint sin
        # protección frente a abuso real.
        self.general_rate_limit_webhook: str = os.getenv(
            "GENERAL_RATE_LIMIT_WEBHOOK", "300/minute"
        )

        # --- IA local self-hosted (Ollama) — SPEC-016, SENSIBLE (.no-externo) ---
        # CHECKPOINT C3/RNF-01: el host del modelo se configura SOLO por env y
        # DEBE apuntar al servicio interno de la red `ia_internal` (SPEC-011,
        # `internal: true`). Nunca a un dominio de internet. `_require_internal_ai_host`
        # falla-rápido (arranque) si detecta un host que no es el interno esperado,
        # para que un error de configuración no abra una ruta de egress de inferencia.
        self.ai_base_url: str = self._require_internal_ai_host(
            "OLLAMA_BASE_URL",
            os.getenv("OLLAMA_BASE_URL", "http://ia:11434"),
        )
        self.ai_llm_model: str = os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct")
        self.ai_embedding_model: str = os.getenv(
            "OLLAMA_EMBED_MODEL", "nomic-embed-text"
        )
        self.ai_request_timeout_seconds: float = float(
            os.getenv("AI_REQUEST_TIMEOUT_SECONDS", "30")
        )
        self.ai_connect_timeout_seconds: float = float(
            os.getenv("AI_CONNECT_TIMEOUT_SECONDS", "5")
        )

        # --- Datos personales: minimización y retención (SPEC-021, HABEAS
        # DATA/GDPR-like) ---
        # `DATA_RETENTION_DAYS`: ventana (en días) tras la cual un contacto
        # inactivo (borrado lógico, C2) es candidato a anonimización por el
        # job de retención (`app.services.retention_service`). No aplica a
        # contactos activos: la retención opera SOLO sobre lo que ya fue
        # marcado `activo=False` (p.ej. por el titular vía HABEAS DATA o por
        # el agente), nunca borra/anonimiza datos en uso.
        self.data_retention_days: int = int(os.getenv("DATA_RETENTION_DAYS", "90"))
        # `ENABLE_DATA_ANONYMIZATION`: por defecto `false` — el job de
        # retención puede ejecutarse en modo "solo reporte" (dry-run) sin
        # tocar datos hasta que se habilite explícitamente. Evita que un
        # despliegue nuevo anonimice datos sin que el Lead lo haya decidido.
        self.enable_data_anonymization: bool = os.getenv(
            "ENABLE_DATA_ANONYMIZATION", "false"
        ).strip().lower() in ("1", "true", "yes")

        # --- WhatsApp Business Cloud API (SPEC-024/025/026, SENSIBLE) ---
        # `WHATSAPP_APP_SECRET`: clave HMAC para validar `X-Hub-Signature-256`
        # del webhook (SPEC-026 RF-02). `WHATSAPP_VERIFY_TOKEN`: token del
        # challenge GET de suscripción (SPEC-026 RF-01). CHECKPOINT C3:
        # fail-fast fuera de `development` igual que JWT_SECRET_KEY/DB_PASSWORD
        # (mismo `_require_strong_secret`) — un valor débil/ausente permitiría
        # falsificar webhooks o bloquear la verificación de Meta.
        self.whatsapp_app_secret: str = self._require_strong_secret(
            "WHATSAPP_APP_SECRET",
            os.getenv("WHATSAPP_APP_SECRET"),
            dev_default="dev-only-change-me-whatsapp-app-secret",
        )
        self.whatsapp_verify_token: str = self._require_strong_secret(
            "WHATSAPP_VERIFY_TOKEN",
            os.getenv("WHATSAPP_VERIFY_TOKEN"),
            dev_default="dev-only-change-me-whatsapp-verify-token",
        )

        # --- WhatsApp Business Cloud API — envío saliente (SPEC-029, SENSIBLE,
        # ADR-006 excepción acotada de egress) ---
        # `WHATSAPP_TOKEN`: access token del WABA (Bearer) usado por
        # `app/integrations/whatsapp/graph_client.py` para autenticar contra
        # la Graph API de Meta (host fijo, allowlist ADR-006). CHECKPOINT C3:
        # fail-fast fuera de `development`, igual que el resto de secretos
        # del canal — un token débil/ausente en producción bloquearía el
        # arranque del worker de envío en vez de fallar silenciosamente en
        # cada request a Meta.
        self.whatsapp_token: str = self._require_strong_secret(
            "WHATSAPP_TOKEN",
            os.getenv("WHATSAPP_TOKEN"),
            dev_default="dev-only-change-me-whatsapp-token-not-a-real-secret",
        )
        # `WHATSAPP_PHONE_NUMBER_ID` por defecto (fallback): en multi-tenant
        # el `phone_number_id` real de cada envío proviene de la conversación/
        # `whatsapp_accounts` (SPEC-025); esta variable solo cubre el caso de
        # un único número configurado por entorno (mismo criterio que otros
        # defaults de `Settings`, nunca sustituye el dato de la fila cuando
        # existe).
        self.whatsapp_phone_number_id: str | None = os.getenv(
            "WHATSAPP_PHONE_NUMBER_ID"
        )
        # Versión de la Graph API: configurable por env, el HOST queda FIJO
        # (allowlist en `graph_client.py`, RNF-01 SPEC-029) — cambiar esta
        # variable nunca puede reapuntar a otro dominio.
        self.whatsapp_api_version: str = os.getenv("WHATSAPP_API_VERSION", "v21.0")
        # Ventana de servicio (RF-03 SPEC-029): horas desde el último mensaje
        # del CONTACTO dentro de las cuales se permite texto libre; fuera de
        # ventana se exige plantilla HSM utilitaria.
        self.whatsapp_session_window_hours: int = int(
            os.getenv("WHATSAPP_SESSION_WINDOW_HOURS", "24")
        )
        # Plantilla HSM utilitaria mínima (≥1, RF-03) para reabrir la
        # conversación fuera de ventana. Sin plantilla configurada, un envío
        # fuera de ventana se bloquea con motivo explícito (criterio de
        # aceptación SPEC-029) en vez de arriesgarse a que Meta rechace un
        # texto libre inválido.
        self.whatsapp_template_name: str | None = os.getenv("WHATSAPP_TEMPLATE_NAME")
        self.whatsapp_template_language: str = os.getenv(
            "WHATSAPP_TEMPLATE_LANGUAGE", "es"
        )
        # Timeouts/reintentos del cliente de transporte hacia Meta (RNF-05).
        self.whatsapp_send_timeout_seconds: float = float(
            os.getenv("WHATSAPP_SEND_TIMEOUT_SECONDS", "10")
        )
        self.whatsapp_send_max_retries: int = int(
            os.getenv("WHATSAPP_SEND_MAX_RETRIES", "3")
        )
        self.whatsapp_send_backoff_base_seconds: float = float(
            os.getenv("WHATSAPP_SEND_BACKOFF_BASE_SECONDS", "1")
        )

        # --- Instagram Direct Message (SPEC-085, F0, SENSIBLE, espejo del
        # bloque WhatsApp de arriba) ---
        # `INSTAGRAM_APP_SECRET`: clave HMAC para validar `X-Hub-Signature-256`
        # del webhook de Instagram (SPEC-086, fuera de alcance de SPEC-085).
        # `INSTAGRAM_VERIFY_TOKEN`: token del challenge GET de suscripción del
        # webhook. CHECKPOINT C3: fail-fast fuera de `development` igual que
        # WHATSAPP_APP_SECRET/WHATSAPP_VERIFY_TOKEN (mismo
        # `_require_strong_secret`) — un valor débil/ausente permitiría
        # falsificar webhooks o bloquear la verificación de Meta.
        self.instagram_app_secret: str = self._require_strong_secret(
            "INSTAGRAM_APP_SECRET",
            os.getenv("INSTAGRAM_APP_SECRET"),
            dev_default="dev-only-change-me-instagram-app-secret",
        )
        self.instagram_verify_token: str = self._require_strong_secret(
            "INSTAGRAM_VERIFY_TOKEN",
            os.getenv("INSTAGRAM_VERIFY_TOKEN"),
            dev_default="dev-only-change-me-instagram-verify-token",
        )

        # --- Instagram Direct Message — envío saliente (SPEC-089, fuera de
        # alcance de SPEC-085, ADR-006 ampliado: mismo host de Graph API ya
        # autorizado para WhatsApp, egress NO nuevo) ---
        # `INSTAGRAM_PAGE_ACCESS_TOKEN`: access token de la Página/cuenta de
        # Instagram Business (Bearer) usado por
        # `app/integrations/instagram/graph_client.py` (SPEC-089, fuera de
        # alcance aquí) para autenticar contra la Graph API de Meta (host
        # fijo, allowlist ADR-006 ampliado). CHECKPOINT C3: fail-fast fuera de
        # `development`, igual que el resto de secretos del canal.
        self.instagram_page_access_token: str = self._require_strong_secret(
            "INSTAGRAM_PAGE_ACCESS_TOKEN",
            os.getenv("INSTAGRAM_PAGE_ACCESS_TOKEN"),
            dev_default="dev-only-change-me-instagram-page-token-not-a-real-secret",
        )
        # `INSTAGRAM_BUSINESS_ACCOUNT_ID` por defecto (fallback): en
        # multi-tenant el `instagram_business_account_id` real de cada envío
        # proviene de la conversación/`instagram_accounts` (SPEC-085); esta
        # variable solo cubre el caso de una única cuenta configurada por
        # entorno (mismo criterio que WHATSAPP_PHONE_NUMBER_ID, nunca
        # sustituye el dato de la fila cuando existe). No es secreto fuerte
        # (id público de cuenta, no credencial).
        self.instagram_business_account_id: str | None = os.getenv(
            "INSTAGRAM_BUSINESS_ACCOUNT_ID"
        )
        # Versión de la Graph API: configurable por env, el HOST queda FIJO
        # (allowlist en `graph_client.py` de Instagram, RNF-EGRESS-NO-NUEVO
        # SPEC-085) — cambiar esta variable nunca puede reapuntar a otro
        # dominio. Default alineado con `whatsapp_api_version`.
        self.instagram_api_version: str = os.getenv("INSTAGRAM_API_VERSION", "v21.0")

        # --- STT local self-hosted (faster-whisper) — SPEC-035/037/038,
        # SENSIBLE (.no-externo), ADR-009 ---
        # Modelo/idioma/dispositivo del `stt_worker` (SPEC-038, fuera de
        # alcance de SPEC-037): se leen aquí también porque `api` los expone
        # en logs de diagnóstico y porque mantener una única fuente de verdad
        # (`Settings`) evita que cada módulo relea `os.environ` por su cuenta.
        self.stt_model: str = os.getenv("STT_MODEL", "large-v3")
        self.stt_model_dir: str = os.getenv(
            "STT_MODEL_DIR", "/root/.cache/huggingface/models"
        )
        self.stt_language: str = os.getenv("STT_LANGUAGE", "es")
        self.stt_device: str = os.getenv("STT_DEVICE", "cuda")
        # Modelo de repliegue (RNF-42, R-42): si `STT_DEVICE=cpu` o la carga
        # en GPU falla (driver/CUDA ausente, OOM), `stt_worker` cae a este
        # modelo más liviano en CPU en vez de fallar el job — RTF degradado
        # pero DOCUMENTADO (SPEC-038), nunca un job perdido silenciosamente.
        self.stt_fallback_model: str = os.getenv("STT_FALLBACK_MODEL", "medium")
        self.stt_fallback_device: str = os.getenv("STT_FALLBACK_DEVICE", "cpu")
        # `STT_COMPUTE_TYPE`: cuantización de CTranslate2 (float16 en GPU,
        # int8 recomendado en CPU por rendimiento) — parametrizable porque el
        # tipo óptimo depende del hardware real de despliegue (SUP-44).
        self.stt_compute_type: str = os.getenv("STT_COMPUTE_TYPE", "float16")
        self.stt_fallback_compute_type: str = os.getenv(
            "STT_FALLBACK_COMPUTE_TYPE", "int8"
        )
        # VAD (voice activity detection) integrado de faster-whisper: filtra
        # silencios antes de transcribir (RF de SPEC-038 "VAD para saltar
        # silencios") y es la base de la heurística de diarización básica de
        # abajo. Activable/desactivable por env (RF-04).
        self.stt_vad_filter_enabled: bool = (
            os.getenv("STT_VAD_FILTER_ENABLED", "true").strip().lower() == "true"
        )
        # Diarización básica opcional (RF-02): activable/desactivable por env
        # sin tocar código. Heurística: alternancia de hablante `agente`/
        # `cliente` cada vez que el hueco de silencio entre dos segmentos
        # consecutivos (detectado por VAD) supera este umbral — ver docstring
        # de `app/services/telefonia/stt_engine.py::_diarizar_segmentos` para
        # el detalle de la decisión de diseño.
        self.stt_diarization_enabled: bool = (
            os.getenv("STT_DIARIZATION_ENABLED", "true").strip().lower() == "true"
        )
        self.stt_diarization_silence_gap_seconds: float = float(
            os.getenv("STT_DIARIZATION_SILENCE_GAP_SECONDS", "1.5")
        )

        # --- Almacén de audio cifrado en reposo on-prem (SPEC-035/037,
        # ADR-009) ---
        # `AUDIO_STORAGE_PATH`: ruta del volumen (montado en `api`/
        # `recording_ingest_worker`/`stt_worker`) donde se escribe el audio ya
        # cifrado. `AUDIO_ENCRYPTION_KEY`: clave simétrica del cifrado en
        # reposo (C3: fail-fast fuera de development, igual que el resto de
        # secretos — un audio de llamada es dato personal/posible PHI).
        self.audio_storage_path: str = os.getenv("AUDIO_STORAGE_PATH", "/audio_store")
        self.audio_encryption_key: str = self._require_strong_secret(
            "AUDIO_ENCRYPTION_KEY",
            os.getenv("AUDIO_ENCRYPTION_KEY"),
            dev_default="dev-only-change-me-audio-encryption-key-32chars",
        )
        self.audio_retention_days: int = int(os.getenv("AUDIO_RETENTION_DAYS", "30"))

        # --- Retención/anonimización de audio y transcripción — SPEC-041,
        # extiende SPEC-021 (HABEAS DATA/GDPR-like), ADR-009 ---
        # `CALL_TRANSCRIPT_RETENTION_DAYS`: ventana (días) de retención de la
        # TRANSCRIPCIÓN de la llamada, independiente de `AUDIO_RETENTION_DAYS`
        # (RF-01 SPEC-041: "retención configurable... de audio y de
        # transcripción"). Por defecto igual a `DATA_RETENTION_DAYS` (90,
        # SPEC-021): el texto de la transcripción es dato personal/PHI
        # potencial pero de menor sensibilidad de almacenamiento que el
        # binario de audio (SUP-49 fija 30 días para el AUDIO; la SPEC no fija
        # un default distinto para la transcripción, así que se alinea con la
        # retención general de datos personales ya aprobada en SPEC-021 en vez
        # de inventar un tercer valor sin base en una SPEC/ADR aprobados).
        self.call_transcript_retention_days: int = int(
            os.getenv("CALL_TRANSCRIPT_RETENTION_DAYS", "90")
        )
        # `AUDIO_RETENTION_ACTION`: acción al vencer la retención del AUDIO
        # (RF-02). `"purge"` (default, SUP-49): borra físicamente el blob del
        # almacén cifrado y limpia `audio_ref`. `"anonymize"`: alias
        # documentado de `"purge"` para el audio — a diferencia de un campo de
        # texto, un blob de audio no tiene una forma "anonimizada" útil
        # distinta de eliminarlo (no hay PII parcial que tachar dentro de un
        # WAV); se deja la variable configurable (no hardcodeada, RF-01) para
        # que un cambio de política futuro sea un cambio de env, pero HOY solo
        # `"purge"` tiene efecto real sobre el audio. Un valor no reconocido
        # cae a `"purge"` (fail-safe: nunca retiene audio más allá de la
        # ventana por un typo de configuración).
        self.audio_retention_action: str = (
            os.getenv("AUDIO_RETENTION_ACTION", "purge").strip().lower()
        )
        if self.audio_retention_action not in ("purge", "anonymize"):
            self.audio_retention_action = "purge"
        # `CALL_TRANSCRIPT_RETENTION_ACTION`: acción al vencer la retención de
        # la TRANSCRIPCIÓN (RF-02). `"anonymize"` (default): sobrescribe
        # `segmentos` con un marcador no identificante (mismo patrón que
        # `contacts` en `erase_contact_personal_data`, SPEC-021) y conserva la
        # fila para trazabilidad (WER/idioma/modelo_stt). `"purge"`: además
        # de anonimizar el texto, aplica borrado lógico (`activo=False`) de
        # forma explícita si aún no lo estaba (ya ocurre siempre antes por
        # C2, ver `call_retention_service`).
        self.call_transcript_retention_action: str = (
            os.getenv("CALL_TRANSCRIPT_RETENTION_ACTION", "anonymize").strip().lower()
        )
        if self.call_transcript_retention_action not in ("purge", "anonymize"):
            self.call_transcript_retention_action = "anonymize"
        # `ENABLE_CALL_RETENTION_PURGE`: por defecto `false` — mismo criterio
        # que `ENABLE_DATA_ANONYMIZATION` (SPEC-021): el job de retención de
        # audio/transcripción corre en modo dry-run (solo reporta candidatos)
        # hasta que se habilite explícitamente en el entorno, para evitar que
        # un despliegue nuevo purgue audio sin decisión explícita del Lead.
        self.enable_call_retention_purge: bool = os.getenv(
            "ENABLE_CALL_RETENTION_PURGE", "false"
        ).strip().lower() in ("1", "true", "yes")

        # --- Puntos de extensión PHI (ADR-009 endurecido) — NO activos por
        # defecto, preparados para cuando el Lead confirme dominio de
        # salud/PHI (SUP-45 hoy fija HABEAS DATA/comercial, no PHI) ---
        # `PHI_MODE_ENABLED`: interruptor maestro del endurecimiento PHI.
        # Mientras sea `false` (default), el resto de flags PHI de abajo son
        # ignorados por el código de aplicación (documentado, no implementado
        # con lógica condicional en el resto del backend todavía — ese es
        # justamente el alcance que esta SPEC deja preparado sin activar).
        self.phi_mode_enabled: bool = os.getenv(
            "PHI_MODE_ENABLED", "false"
        ).strip().lower() in ("1", "true", "yes")
        # `TRANSCRIPT_FIELD_ENCRYPTION_ENABLED`: TODO (SPEC-041 RNF-44, si
        # PHI) — cuando el Lead confirme PHI y active `PHI_MODE_ENABLED`, este
        # flag debe activar cifrado de CAMPO (a nivel de columna, no solo de
        # volumen) de `call_transcripts.segmentos` con una clave separada de
        # `AUDIO_ENCRYPTION_KEY` (rotación independiente). La lógica de
        # cifrado/descifrado de campo NO está implementada todavía (esfuerzo
        # significativo: requiere decidir mecanismo — pgcrypto a nivel de BD
        # vs. cifrado en aplicación con SQLAlchemy `TypeDecorator`, migración
        # de datos existentes, y coordinación con `stt_worker`/`app/api/calls.py`
        # para leer/escribir el campo cifrado — fuera de alcance de SPEC-041,
        # que solo deja el flag y este TODO documentado). Mientras
        # `PHI_MODE_ENABLED=false` este flag no tiene efecto.
        self.transcript_field_encryption_enabled: bool = os.getenv(
            "TRANSCRIPT_FIELD_ENCRYPTION_ENABLED", "false"
        ).strip().lower() in ("1", "true", "yes")

        # --- Webhook de grabaciones del PBX (SPEC-037, ADR-007) ---
        # `WEBHOOK_VERIFY_TOKEN`: token del challenge/verificación inicial (si
        # el PBX lo soporta, análogo a `WHATSAPP_VERIFY_TOKEN`).
        # `WEBHOOK_SECRET`: clave HMAC para validar la firma
        # `X-Webhook-Signature-256` del POST con el fichero + metadatos
        # (mismo patrón que `WHATSAPP_APP_SECRET`/SPEC-026). CHECKPOINT C3:
        # fail-fast fuera de `development`.
        self.webhook_verify_token: str = self._require_strong_secret(
            "WEBHOOK_VERIFY_TOKEN",
            os.getenv("WEBHOOK_VERIFY_TOKEN"),
            dev_default="dev-only-change-me-webhook-verify-token",
        )
        self.webhook_secret: str = self._require_strong_secret(
            "WEBHOOK_SECRET",
            os.getenv("WEBHOOK_SECRET"),
            dev_default="dev-only-change-me-webhook-secret-not-real",
        )

        # --- PBX externo (SOLO transporte de descarga, SPEC-037, ADR-010) ---
        # Por defecto DESACTIVADO (SUP-42: PBX on-prem que entrega el fichero
        # directamente por webhook -> sin egress nuevo). Si el Lead confirma
        # PBX externo (`PBX_EXTERNAL_ENABLED=true`), `recording_fetch_worker`
        # (`app/services/telefonia/`) descarga SOLO desde `PBX_EXTERNAL_HOST`
        # (allowlist, `check-externos-backend.sh` sección 11).
        self.pbx_external_enabled: bool = os.getenv(
            "PBX_EXTERNAL_ENABLED", "false"
        ).strip().lower() in ("1", "true", "yes")
        self.pbx_external_host: str = os.getenv("PBX_EXTERNAL_HOST", "")
        self.pbx_external_port: int = int(os.getenv("PBX_EXTERNAL_PORT", "443"))
        # `PBX_EXTERNAL_AUTH_TOKEN`: CHECKPOINT C3, fail-fast CONDICIONADO
        # (mismo patrón que `WEBHOOK_SECRET`) — solo se exige robusto cuando
        # `PBX_EXTERNAL_ENABLED=true` (el Lead confirmó PBX externo): un
        # token débil/ausente en ese escenario permitiría a un PBX
        # comprometido/atacante autenticarse contra el proveedor real, o
        # dejaría la descarga sin autenticar. Con `PBX_EXTERNAL_ENABLED=false`
        # (default, SUP-42, PBX on-prem) NO se exige nada, para no romper el
        # arranque en desarrollo/on-prem donde esta variable ni se usa.
        self.pbx_external_auth_token: str = (
            self._require_strong_secret(
                "PBX_EXTERNAL_AUTH_TOKEN",
                os.getenv("PBX_EXTERNAL_AUTH_TOKEN"),
                dev_default="dev-only-change-me-pbx-external-auth-token",
            )
            if self.pbx_external_enabled
            else os.getenv("PBX_EXTERNAL_AUTH_TOKEN", "")
        )

        # --- VoiceBot en vivo (Entregable #5, F0, SPEC-044, ADR-011/ADR-012) ---
        # STT en vivo: modelo ligero para clasificación de intent contra catálogo
        # cerrado (no transcripción legal, esa es batch con large-v3 de #4).
        # Modelos: distil-whisper, faster-whisper small/medium cuantizado.
        self.stt_live_model: str = os.getenv("STT_LIVE_MODEL", "distil-whisper")
        self.stt_live_language: str = os.getenv("STT_LIVE_LANGUAGE", "es")
        self.stt_live_device: str = os.getenv("STT_LIVE_DEVICE", "cuda")
        # Cuantización del modelo STT en vivo (int8 recomendado para GPU
        # compartida bajo presupuesto de latencia, ADR-011 §3).
        self.stt_live_compute_type: str = os.getenv("STT_LIVE_COMPUTE_TYPE", "int8")

        # TTS de respuesta en notas de voz (Entregable #6, CPU-only, ADR-014/
        # SPEC-067/SPEC-068). Limpieza de residuos de la fase GPU archivada
        # (PLAN-005/ADR-011/ADR-012, VoiceBot en vivo con barge-in ≤700ms):
        # ese vector NO se implementó (memoria de proyecto: "No GPU / VoiceBot
        # pivot") y sus 3 claves de config (`TTS_MODE`, `PIPER_VOICE`,
        # `TTS_VRAM_FRACTION`) eran residuos sin consumidor real en el código
        # (verificado: ningún `app/` importa `settings.tts_mode` ni
        # `settings.tts_vram_fraction`). Decisión R-87 (SPEC-068):
        #   - `TTS_MODE` se ELIMINA: describía una interfaz conmutable
        #     "piper generativo ↔ modo bajo-cómputo pregrabado" para el
        #     orquestador de voz EN VIVO (barge-in en tiempo real, SPEC-048,
        #     archivado). El TTS asíncrono de #6 (ADR-014) no tiene esa
        #     disyuntiva: el motor está fijado por evidencia (SPEC-067,
        #     Piper TTS 1.8.0) y la generación siempre corre en background
        #     tras la aprobación del guion — no hay modo "en vivo" que
        #     conmutar. Si en el futuro se necesitara un modo pregrabado,
        #     eso es una SPEC nueva, no la reactivación de este flag.
        #   - `TTS_VRAM_FRACTION` se ELIMINA: no aplica en CPU-only (ninguna
        #     GPU en esta máquina objetivo, R-87). El throttling/concurrencia
        #     de `tts:jobs` (SPEC-069) se dimensiona por CPU (worker
        #     pool/Redis), no por fracción de VRAM.
        #   - `PIPER_VOICE` se CONSERVA, pero su valor por defecto se
        #     corrige: `es_CO-pablo-medium` (residuo GPU) no existe en el
        #     catálogo real de Piper (404, hallazgo de SPEC-067) — no hay voz
        #     colombiana auténtica disponible en ninguna librería evaluada.
        #     El Lead confirmó `es_ES-davefx-medium` (ADR-014 decisión 4):
        #     única combinación motor+voz que cumple el techo ≤10s en las 8
        #     categorías de guion probadas (peor caso p95 = 7.19s), preferida
        #     sobre `es_MX-ald-medium` (acento más cercano a LatAm, pero
        #     incumple por poco el techo en el guion más largo, 10.137s).
        #     Documentado como trade-off de acento aceptado, no como error.
        self.piper_voice: str = os.getenv("PIPER_VOICE", "es_ES-davefx-medium")
        # `PIPER_VOICE_DIR`: directorio de pesos Piper montado por volumen
        # (SPEC-069, mismo criterio que `STT_MODEL_DIR`/`whisper_models`,
        # ADR-009): nunca se descarga en runtime. Compartido conceptualmente
        # entre el `voice_tts` archivado (que monta `voice_piper_voices` en
        # `/root/.local/share/piper`) y este servicio nuevo — variable
        # PROPIA para no acoplar el path del servicio nuevo al volumen legado
        # inerte; en `docker-compose.yml` el volumen nuevo
        # (`respuesta_tts_piper_voices`) se monta en esta misma ruta.
        self.piper_voice_dir: str = os.getenv("PIPER_VOICE_DIR", "/piper_voices")

        # --- TTS asíncrono de respuesta (Entregable #6, SPEC-069, ADR-014) ---
        # DECISIÓN DE NOMBRES (confirmada por el Lead, PLAN-008 Entregable #6):
        # el bloque `voice_tts` de `docker-compose.yml` (servicio INERTE del
        # VoiceBot en vivo archivado, PLAN-005/ADR-011/ADR-012, nunca
        # implementado) ya usa `TTS_MODE`/`PIPER_VOICE`/`TTS_VRAM_FRACTION` —
        # se DEJA INTACTO a propósito (no se reactiva, no se borra). Este
        # servicio nuevo (asíncrono, CPU-only, notas de voz de WhatsApp) usa
        # el prefijo `RESPUESTA_TTS_*`, deliberadamente DISTINTO, para que
        # nadie confunda ambos vectores en logs/deploy/runbook. `PIPER_VOICE`
        # de arriba SÍ se reutiliza tal cual (misma voz, mismo motor Piper,
        # sin necesidad de una segunda variable de voz): `es_ES-davefx-medium`
        # es el único valor válido según la evidencia de SPEC-067; conservar
        # una sola fuente de verdad para la voz evita que este servicio y un
        # futuro reuso de `voice_tts` (si algún día se reactiva) diverjan sin
        # querer.
        #
        # `RESPUESTA_TTS_ENGINE`: motor de síntesis (SPEC-067/ADR-014, Piper
        # TTS 1.8.0, ÚNICO validado hoy). Configurable para no hardcodear un
        # string mágico en el worker, pero SIN una segunda implementación de
        # motor: un valor distinto de "piper" no tiene efecto (el worker no
        # sabe sintetizar con nada más) — existe para dejar explícita la
        # decisión en el runbook (SPEC-072) y facilitar una migración futura
        # documentada, no para conmutar en runtime.
        self.respuesta_tts_engine: str = os.getenv("RESPUESTA_TTS_ENGINE", "piper")
        # `RESPUESTA_TTS_MAX_CHARS`: límite de longitud sintetizable. THOR
        # (SPEC-071, CE-84) midió el motor REAL bajo carga CPU concurrente
        # (proxy de STT/RAG/sentimiento): los guiones largos (600-750 chars,
        # el rango que la Adenda de SPEC-067/069 daba por aceptable SIN
        # concurrencia) superaban el techo de 10s de forma reproducible
        # (11-15s medidos). El Lead decidió bajar el límite a 420 — dentro
        # del rango que THOR confirmó que SÍ cumple el techo incluso bajo
        # carga concurrente (categorías corta/media, máximo observado
        # 3.67s) — en vez de aceptar audios largos best-effort. Un guion más
        # largo NO se sintetiza (cae a `tts_estado="error"`, fallback a
        # texto) en vez de arriesgar exceder el techo de latencia.
        try:
            self.respuesta_tts_max_chars: int = int(
                os.getenv("RESPUESTA_TTS_MAX_CHARS", "420")
            )
            if self.respuesta_tts_max_chars <= 0:
                self.respuesta_tts_max_chars = 420
        except ValueError:
            self.respuesta_tts_max_chars = 420
        # `RESPUESTA_TTS_TIMEOUT_SECONDS`: techo de latencia (Q4-b, ADR-014,
        # ≤5-10s) que el worker aplica a la síntesis+transcodificación de un
        # job individual; si se excede, el job se marca `tts_estado="error"`
        # sin enviar audio a medias (RF-07).
        try:
            self.respuesta_tts_timeout_seconds: float = float(
                os.getenv("RESPUESTA_TTS_TIMEOUT_SECONDS", "10")
            )
            if self.respuesta_tts_timeout_seconds <= 0:
                self.respuesta_tts_timeout_seconds = 10.0
        except ValueError:
            self.respuesta_tts_timeout_seconds = 10.0
        # `RESPUESTA_TTS_CONCURRENCIA`: throttling de `tts:jobs` (Adenda
        # SPEC-067/SPEC-069, R-84) — concurrencia inicial = 1 (no medido con
        # workers reales en el sandbox del spike; SPEC-071 re-valida). El
        # worker corre N tareas concurrentes internas (asyncio.Semaphore)
        # sobre la misma cola, sin escalar réplicas por defecto.
        try:
            self.respuesta_tts_concurrencia: int = int(
                os.getenv("RESPUESTA_TTS_CONCURRENCIA", "1")
            )
            if self.respuesta_tts_concurrencia <= 0:
                self.respuesta_tts_concurrencia = 1
        except ValueError:
            self.respuesta_tts_concurrencia = 1
        # `RESPUESTA_TTS_PERSIST_ENABLED`: retención por defecto = NO
        # persistir el clip (ADR-012 §5/ADR-014 decisión 5, herencia). Solo
        # una política explícita de auditoría activa la persistencia cifrada
        # (`audio_store.py` + `audio_salida_ref`, régimen SPEC-041) — cambio
        # SENSIBLE (C6) que requiere decisión separada del Lead, no un default.
        self.respuesta_tts_persist_enabled: bool = os.getenv(
            "RESPUESTA_TTS_PERSIST_ENABLED", "false"
        ).strip().lower() in ("1", "true", "yes")

        # NLU de intent: confianza mínima de clasificación contra catálogo
        # cerrado (SPEC-045). Respuestas con confianza < umbral se escalan a
        # humano en vez de responder con bajo confidence.
        try:
            self.intent_confidence_threshold: float = float(
                os.getenv("INTENT_CONFIDENCE_THRESHOLD", "0.7")
            )
            if not 0.0 <= self.intent_confidence_threshold <= 1.0:
                self.intent_confidence_threshold = 0.7
        except ValueError:
            self.intent_confidence_threshold = 0.7

        # Concurrencia máxima de llamadas en vivo (C, ADR-011 §4): límite
        # conservador (1-3 por defecto piloto), fijado empíricamente por THOR
        # (F6) compartiendo GPU con batch. Al llegar C+1, la nueva llamada
        # recibe IVR mínimo + escalación (nunca se degrada una activa).
        self.max_concurrent_calls: int = int(os.getenv("MAX_CONCURRENT_CALLS", "1"))

        # PBX de media en vivo (SPEC-044, SPEC-046, ADR-011 §7): host/puerto
        # del PBX que transporta media/SIP. Por defecto (vacío): PBX on-prem en
        # red local, sin egress nuevo (P-M, topología preferida). Si el Lead
        # confirma PBX externo (cloud), habilitar host/puerto + firewall host +
        # allowlist CI, cambio sensible → C6.
        self.pbx_media_host: str = os.getenv("PBX_MEDIA_HOST", "")
        self.pbx_media_port: int = int(os.getenv("PBX_MEDIA_PORT", "5060"))
        # PBX_MEDIA_AUTH_TOKEN: credencial del PBX de media (si aplica).
        # CHECKPOINT C3: solo se exige robusto si PBX_MEDIA_HOST no está vacío
        # (PBX externo confirmado).
        self.pbx_media_auth_token: str = (
            self._require_strong_secret(
                "PBX_MEDIA_AUTH_TOKEN",
                os.getenv("PBX_MEDIA_AUTH_TOKEN"),
                dev_default="dev-only-change-me-pbx-media-auth-token",
            )
            if self.pbx_media_host
            else os.getenv("PBX_MEDIA_AUTH_TOKEN", "")
        )

        # --- Notas de voz de WhatsApp — límite de duración (SPEC-055, F2,
        # PLAN-006 R-66) ---
        # `VOICE_NOTE_MAX_DURATION_SECONDS`: duración máxima (segundos) de
        # una nota de voz de WhatsApp que se acepta para transcripción
        # (`stt:jobs`). Default 600 (10 min, P1). Una nota que la excede se
        # descarta amablemente (auto-respuesta al contacto vía `graph_client`,
        # `transcripcion_estado="descartada_por_duracion"`), NUNCA se encola
        # STT (RF-04/RNF-65). Configurable por env para permitir ajustar la
        # política sin cambio de código (RF-05) y para poder probar el
        # descarte con un límite reducido en tests.
        self.voice_note_max_duration_seconds: int = int(
            os.getenv("VOICE_NOTE_MAX_DURATION_SECONDS", "600")
        )

        # --- Analytics de negocio — límite de rango (SPEC-063, PLAN-007 F1)
        # ---
        # `ANALYTICS_MAX_RANGE_DAYS`: tope superior (días, inclusive) del
        # rango `[desde, hasta]` aceptado por `GET /analytics/business`
        # (RF-02 SPEC-063, R-73 performance): acota el coste de la agregación
        # on-demand (SPEC-062) ante un rango arbitrariamente grande pedido
        # por un cliente. Default 366 (cubre un año calendario completo,
        # incl. año bisiesto) — configurable por env sin cambio de código si
        # THOR/el Lead deciden un tope distinto tras medir latencia real.
        self.analytics_max_range_days: int = int(
            os.getenv("ANALYTICS_MAX_RANGE_DAYS", "366")
        )

    # Hosts permitidos para el servicio de IA: nombre de servicio Docker
    # (`ia`, resuelto en la red interna `ia_internal`) o loopback (para
    # ejecutar Ollama directamente en el host durante desarrollo local sin
    # Docker). Cualquier otro host se considera una fuga potencial de egress
    # de inferencia (RNF-01/CE-21) y aborta el arranque.
    _ALLOWED_AI_HOSTS = {"ia", "localhost", "127.0.0.1", "0.0.0.0", "[::1]"}

    def _require_internal_ai_host(self, var_name: str, raw_url: str) -> str:
        """Valida que la URL del servicio de IA apunte SOLO a la red interna.

        Defensa en profundidad (ADR-005): además del aislamiento de red
        Docker (`ia_internal` con `internal: true`) y del auditor estático
        `check-externos-backend.sh`, la propia aplicación rechaza arrancar
        si `OLLAMA_BASE_URL`/`AI_BASE_URL` no resuelve a un host interno
        conocido (servicio `ia` o loopback). Esto evita que un error de
        configuración (p.ej. pegar por accidente un endpoint de internet)
        active una ruta de inferencia externa.
        """
        from urllib.parse import urlparse

        parsed = urlparse(raw_url)
        host = (parsed.hostname or "").strip().lower()
        if host not in self._ALLOWED_AI_HOSTS:
            raise ConfigurationError(
                f"{var_name}='{raw_url}' no apunta a un host interno permitido "
                f"({sorted(self._ALLOWED_AI_HOSTS)}). CHECKPOINT SENSIBLE "
                "(.no-externo, RNF-01/CE-21): la inferencia de IA SOLO puede "
                "hablar con el servicio interno de la red `ia_internal` "
                "(SPEC-011). Revisa la variable de entorno antes de arrancar."
            )
        return raw_url

    def _require_strong_secret(
        self, var_name: str, raw_value: str | None, *, dev_default: str
    ) -> str:
        """Fail-fast (C3, BLACK WIDOW SPEC-013): exige un secreto robusto fuera
        de `development`.

        - En `development`: si la variable no está definida, se usa
          `dev_default` (documentado como valor de desarrollo, nunca válido
          en producción). Si SÍ está definida mantiene el valor dado aunque
          sea débil, para no romper flujos locales existentes.
        - Fuera de `development` (staging/production/cualquier otro valor):
          la variable es OBLIGATORIA, no puede estar en la lista negra de
          valores débiles/genéricos, y debe tener al menos
          `_MIN_SECRET_LENGTH` caracteres. Si no se cumple, se aborta el
          arranque con `ConfigurationError` (evita arrancar con un secreto
          conocido que permitiría forjar tokens o adivinar credenciales de BD).
        """
        if self._is_development:
            return raw_value if raw_value else dev_default

        if not raw_value:
            raise ConfigurationError(
                f"{var_name} es obligatorio cuando ENVIRONMENT="
                f"'{self.environment}' (no development). Configúralo como "
                "variable de entorno/secret manager (CHECKPOINT C3)."
            )
        if raw_value.strip().lower() in _WEAK_SECRET_VALUES:
            raise ConfigurationError(
                f"{var_name} tiene un valor débil/genérico no permitido fuera "
                "de development (CHECKPOINT C3). Usa un secreto robusto y "
                "único por entorno."
            )
        if len(raw_value) < _MIN_SECRET_LENGTH:
            raise ConfigurationError(
                f"{var_name} debe tener al menos {_MIN_SECRET_LENGTH} "
                f"caracteres fuera de development (longitud actual: "
                f"{len(raw_value)})."
            )
        return raw_value

    @property
    def sqlalchemy_database_url(self) -> str:
        return self.database_url

    @property
    def sqlalchemy_database_url_migrations(self) -> str:
        """URL de conexión con el rol PRIVILEGIADO (owner/DDL), solo para
        Alembic (ADR-008). Nunca usar esta URL en el runtime de api/workers."""
        return self.database_url_migrations


@lru_cache
def get_settings() -> Settings:
    return Settings()
