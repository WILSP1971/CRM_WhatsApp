# Documentación de Métricas de Negocio — Dashboard Analytics (SPEC-064, SPEC-066)

> Definición precisa de cada métrica del dashboard de analítica de negocio. Incluye semántica de cálculo, casos límite y relación con el modelo de datos.
> Clasificación: SENSIBLE (`.no-externo`). Todos los cálculos respetan C2 (borrado lógico).

**Responsable:** QUICKSILVER (DevOps/docs) · **Revisado:** SPEC-064/SPEC-065 (implementación y tests) · **Fuente:** PLAN-007 (definiciones del Lead, Q1(a)–Q4).

---

## Tabla de contenidos

1. [Visión general](#visión-general)
2. [Volumen de conversaciones](#volumen-de-conversaciones)
3. [Tiempos de respuesta](#tiempos-de-respuesta)
4. [Tasa de conversión](#tasa-de-conversión)
5. [Asistencia IA (opcional)](#asistencia-ia-opcional)
6. [Semántica de rango y presets](#semántica-de-rango-y-presets)
7. [Modo on-demand (sin caché)](#modo-on-demand-sin-caché)
8. [Tratamiento de borrado lógico (C2)](#tratamiento-de-borrado-lógico-c2)
9. [Errores y casos límite](#errores-y-casos-límite)

---

## Visión general

El dashboard de analítica de negocio (`GET /api/v1/analytics/business`) devuelve KPIs agregados de un tenant autenticado dentro de un rango de fechas `[desde, hasta]` (inclusive). Los cálculos se realizan sin caché en cada request (on-demand, Q2 PLAN-007) sobre datos ya persistidos en PostgreSQL bajo **Row Level Security efectiva** (ADR-004/ADR-008).

**Respuesta JSON (estructura `BusinessAnalyticsOut`):**

```json
{
  "desde": "2026-09-20",
  "hasta": "2026-09-27",
  "canal": null,
  "conversaciones": {
    "total": 150,
    "abiertas": 25,
    "cerradas": 125,
    "por_canal": [
      {"canal": "whatsapp", "total": 80, "abiertas": 10, "cerradas": 70},
      {"canal": "webchat", "total": 70, "abiertas": 15, "cerradas": 55}
    ],
    "serie_diaria": [
      {"fecha": "2026-09-20", "total": 20},
      {"fecha": "2026-09-21", "total": 22},
      ...
      {"fecha": "2026-09-27", "total": 19}
    ]
  },
  "tiempos_respuesta": {
    "primera_respuesta_promedio_seg": 245.3,
    "respuesta_promedio_seg": 189.7,
    "conversaciones_con_respuesta": 140
  },
  "conversion": {
    "tasa": 0.8333,
    "cerradas": 125,
    "totales": 150
  },
  "ia_asistencia": {
    "pct_drafts_aprobados": 0.65,
    "conversaciones_con_draft_aprobado": 91,
    "conversaciones_total": 140,
    "sentimiento": {
      "positivo": 85,
      "neutral": 45,
      "negativo": 10,
      "sin_clasificar": 0
    }
  }
}
```

Ningún campo de la respuesta contiene datos de PII individual: **solo agregados** (conteos, promedios, porcentajes). Jamás expone IDs de contacto, contenido de mensajes ni información personalmente identificable.

---

## Volumen de conversaciones

### Definición general

**Universo:** `Conversation` con `is_active = True` (borrado lógico, C2) y `created_at` dentro de `[desde, hasta]` (ventana sobre fecha de creación de la conversación, **nunca sobre `updated_at`**, PLAN-007 §3.3).

**Desglose:**
- **`total`:** conteo de todas las conversaciones en el universo.
- **`abiertas`:** subconjunto con `estado = "abierta"` (conversación en progreso).
- **`cerradas`:** subconjunto con `estado = "cerrada"` (conversación finalizada, por acción humana o automática).

### Por canal

El endpoint permite filtrar por canal opcional (`canal` query param). Cuando se proporciona:

- **`por_canal`:** array con un MÁXIMO de una entrada (la del canal filtrado); si se especifica un canal que no tiene conversaciones en el rango, el array está vacío.
- **Desglose:** igual que arriba (total/abiertas/cerradas).

Cuando **no** se proporciona canal (valor `None`):

- **`por_canal`:** array con TODAS los canales que tienen conversaciones en el rango (sorted por nombre de canal). Cada entrada es un desglose por ese canal.
- Ejemplo: `whatsapp: {total: 80, abiertas: 10, cerradas: 70}`, `webchat: {total: 70, abiertas: 15, cerradas: 55}`.

### Serie diaria

**Estructura:** array de 1 entrada por día calendario (en orden cronológico), cubriendo completamente el rango `[desde, hasta]`.

- **`fecha`:** fecha ISO (YYYY-MM-DD).
- **`total`:** conteo de conversaciones CREADAS en ese día (campo `created_at`), en el mismo universo que el desglose por estado.

**Casos límite:**
- Un día **SIN ninguna conversación** en el rango: aparece con `total = 0` (**no se omite de la lista**, criterio explícito SPEC-062/RF-02).
- **Interpretación horaria:** `created_at` se compara con la ventana `[inicio-del-día, fin-del-día)` en UTC (zona horaria global, `app/db/session.py`). Un evento a las 23:55 UTC se cuenta en ese día; a las 00:05 UTC del día siguiente se cuenta en el siguiente.

**Ejemplo (rango de 3 días, 1 conversación el primer día):**

```json
"serie_diaria": [
  {"fecha": "2026-09-20", "total": 1},
  {"fecha": "2026-09-21", "total": 0},
  {"fecha": "2026-09-22", "total": 0}
]
```

---

## Tiempos de respuesta

### Definición general

Los tiempos de respuesta se calculan sobre la secuencia de **mensajes** de cada conversación (`Message.activo = True`, `Message.created_at` en rango de la conversación). Se definen dos métricas:

1. **Primera Respuesta (TPR):** tiempo desde el primer mensaje entrante de la conversación hasta la primera respuesta saliente.
2. **Respuesta Promedio:** promedio de TODAS las diferencias tiempo-entre-bloque-entrante-y-saliente-subsiguiente.

### Remitentes: qué cuenta como "saliente"

- **Saliente:** `remitente = "agente"` O `remitente = "ia"` — **ambos cuentan IGUAL** para efectos de tiempos de respuesta (no hay desglose; SPEC-062 no lo requiere).
- **Entrante:** `remitente = "contacto"`.

### Bloques de entrantes consecutivos

Una secuencia de mensajes entrantes consecutivos (sin una respuesta saliente en medio) se trata como **un solo bloque**. Para calcular el tiempo de respuesta:

1. Se identifica el inicio de cada **bloque entrante:** primer mensaje con `remitente = "contacto"` cuyo mensaje anterior (en esa conversación) NO es un entrante (o es el primer mensaje).
2. Se busca el PRIMER mensaje saliente (`remitente` in `{agente, ia}`) con `created_at` posterior al del inicio del bloque.
3. La diferencia `(saliente.created_at - entrante_inicio.created_at)` es **UNA** respuesta.

**Ejemplo (secuencia de mensajes en una conversación):**

```
1. Contacto "Hola"       ← inicio de bloque entrante
2. Contacto "¿Hay stock?" ← continúa bloque (no hay saliente en medio)
3. Agente "Sí, 10 unds." ← respuesta al bloque (diferencia = created_at(3) - created_at(1))
4. Contacto "Preciso"     ← nuevo bloque entrante
5. Agente "¿Qué precisa?" ← respuesta al nuevo bloque (diferencia = created_at(5) - created_at(4))
```

Resultado: 2 respuestas (no 3). La "Primera Respuesta" es la de entrada 3 (tiempo desde 1).

### Cálculo de promedios

- **`primera_respuesta_promedio_seg`:** promedio (mean) del TPR de TODAS las conversaciones del rango que tuvieron al menos una respuesta saliente. Medido en segundos (decimales). `null` si ninguna conversación del rango tuvo una respuesta saliente.

- **`respuesta_promedio_seg`:** promedio (mean) de TODAS las diferencias entrante→saliente acumuladas en TODAS las conversaciones del rango (incluyendo la primera, pero contando cada bloque por separado). `null` si no hay ninguna diferencia calculable (rango vacío o solo sin-respuestas).

- **`conversaciones_con_respuesta`:** cuántas conversaciones del rango contribuyeron AL MENOS una diferencia a los promedios arriba (denominador real; usar para validar/debuggear los promedios).

### Casos límite

1. **Conversación sin ningún mensaje entrante:** excluida completamente de los cálculos (no hay bloque de inicio).
2. **Conversación con solo mensajes salientes:** excluida (criterio anterior se aplica).
3. **Conversación con al menos un bloque entrante pero SIN respuesta posterior:** el bloque se excluye de ambos promedios — no se cuenta como `0` (no falsifica el promedio con un "tiempo de respuesta de 0 segundos"); la conversación tampoco cuenta en `conversaciones_con_respuesta`.
4. **Rango sin ninguna conversación:** ambos promedios son `null`, `conversaciones_con_respuesta = 0`.

### Interpretación operativa

Un operador vería:

- **TPR 245 segundos (≈4 min):** tiempo medio que tarda la primera respuesta desde que un contacto abre la conversación.
- **Respuesta promedio 189 segundos (≈3 min):** tiempo medio entre cada bloque entrante y su respuesta en toda la conversación (promedia respuestas subsiguientes también).
- **140 conversaciones con respuesta:** de 150 totales, 140 tuvieron al menos una respuesta; 10 se quedaron sin responder.

---

## Tasa de conversión

### Definición (Q1(a) PLAN-007)

**Conversión = conversaciones cerradas / conversaciones totales (en el rango).**

Expresada como:
- **`tasa`:** número decimal [0.0, 1.0]; ejemplo: `0.8333` = 83.33%.
- **`cerradas`:** conteo de conversaciones con `estado = "cerrada"`.
- **`totales`:** conteo de todas las conversaciones (`cerradas + abiertas`).

**Fórmula:**
```
tasa = cerradas / totales (si totales > 0)
tasa = null (si totales == 0)
```

### Criterio de `null` vs `0`

**CRÍTICO:** `tasa = null` (NUNCA `0`) cuando `totales == 0`.

- `0` comunicaría "0% de conversión" → hay datos pero ninguno convirtió (falso positivo si no hay datos).
- `null`/`JSON null` comunica honestamente "no hay datos para calcular una tasa" (ausencia de dato, no tasa del 0%).

Este criterio está documentado en SPEC-062/RF-03 (criterio de aceptación explícito). **NO es un ADR de dominio nuevo** (Q1(a) del Lead): es una definición operativa sobre la tabla `Conversation.estado`, ya persistida desde SPEC-007.

### Interpretación operativa

Un operador vería:

- **Tasa 83.33%:** de 150 conversaciones iniciadas, 125 se cerraron (conversión buena).
- **Tasa 50%:** de 100 conversaciones, 50 se cerraron (conversión baja — estudiar motivo).
- **Tasa `null` (mostrado como "—"):** sin conversaciones en el rango — dato no calculable.

---

## Asistencia IA (opcional)

### Disponibilidad

La sección `ia_asistencia` está habilitada si:
- El tenant tiene la feature activada (RF-04 SPEC-062).
- Existen datos de `RagDraft` o `Message.sentimiento` en el rango.

Si no: `ia_asistencia = null`.

### % de borradores RAG aprobados

- **Universo:** conversaciones del rango con `is_active = True` y `created_at` en `[desde, hasta]` (mismo universo que volumen).
- **Numerador:** conversaciones que tienen AL MENOS un `RagDraft` con `estado = "aprobado"` y `is_active = True`.
- **Denominador:** `conversaciones_total` (todas las conversaciones del universo).
- **Fórmula:** `pct_drafts_aprobados = conversaciones_con_draft_aprobado / conversaciones_total` (si `total > 0`), else `null`.

**Ejemplo:**
- 140 conversaciones en el rango.
- 91 tienen AL MENOS un draft aprobado.
- `pct_drafts_aprobados = 91 / 140 = 0.65` (65%).

### Distribución de sentimiento

- **Universo:** mensajes (`Message.activo = True`) con `created_at` en el rango (mismo rango que conversaciones, pero filtrado POR MENSAJE).
- **Filtro:** si el request incluye un `canal`, se filtra por conversación.canal (para mantener consistencia con otros cálculos).
- **Campos:** `sentimiento` = uno de: `"positivo"`, `"neutral"`, `"negativo"`, `null` (sin clasificar).
- **Conteo:** número de mensajes en cada categoría.

**Ejemplo (100 mensajes):**
```json
"sentimiento": {
  "positivo": 85,
  "neutral": 45,
  "negativo": 10,
  "sin_clasificar": 0
}
```

---

## Semántica de rango y presets

### Rango manual (`[desde, hasta]`)

- **Tipo:** parámetros query `desde` y `hasta` en formato ISO `YYYY-MM-DD`.
- **Validación:**
  - `desde <= hasta` (422 si no).
  - `(hasta - desde).days + 1 <= ANALYTICS_MAX_RANGE_DAYS` (env var, default 366 días; 422 si excede).
- **Interpretación:** INCLUSIVE en ambos extremos (un rango de 1 día es el mismo día).

**Ejemplo:** `desde=2026-09-20&hasta=2026-09-27` = 8 días (del 20 al 27 incluido).

### Presets de fecha (Q4 PLAN-007)

El frontend (`AnalyticsPage.tsx`) soporta presets reversibles (selector de rango):

1. **Hoy:** `desde = hoy`, `hasta = hoy` (un solo día).
2. **Últimos 7 días:** `desde = hoy - 6 días`, `hasta = hoy`.
3. **Últimos 30 días:** `desde = hoy - 29 días`, `hasta = hoy`.
4. **Custom:** rango manual (date picker).

**Reversibilidad:** los presets cambian dinámicamente con la fecha actual del operador, y los controles del frontend permiten volver atrás/adelante sin perder el estado anterior.

### Validación y error 422

El backend retorna HTTP 422 (Unprocessable Entity) con un `detail` descriptivo en estos casos:

1. `desde > hasta`: "El parámetro 'desde' no puede ser posterior a 'hasta'."
2. Rango excede `ANALYTICS_MAX_RANGE_DAYS`: "El rango solicitado (N días) supera el máximo permitido (M días). Acota 'desde'/'hasta' o realiza varias consultas por sub-rangos."
3. `canal` no válido: "canal inválido: debe ser uno de [...]."

---

## Modo on-demand (sin caché)

### Definición

**On-demand (Q2 PLAN-007):** cada request a `GET /api/v1/analytics/business` **recalcula los agregados en tiempo real** sobre el rango pedido, sin persistencia en caché (Redis o similar).

- **Sin WebSocket ni tiempo real** (fuera de alcance SPEC-063).
- **Sin bases de datos agregadas** (OLAP, data warehouse). Los cálculos se hacen contra la BD transaccional OLTP (PostgreSQL) con índices y RLS.

### Implicaciones operativas

1. **Latencia:** p95 objetivo ≤ 1500 ms para rangos típicos (≤30 días); medido en SPEC-065 como ~1025 ms sobre volumen representativo (2.500 conversaciones / ~87.500 mensajes en 30 días).

2. **Carga de BD:** un request de análisis consume:
   - 1 query de conteo de conversaciones (estado).
   - 1 query de desglose por canal.
   - 1 query de serie diaria.
   - 2 queries en LATERAL para tiempos de respuesta (mensajes entrantes + salientes).
   - 1 query de asistencia IA (conversaciones con drafts aprobados).
   - 1 query de sentimiento (distribución).

   La tasa de conversión se deriva del mismo resultado de conversaciones (sin reconsultar, fix de performance THOR/SPEC-065) — no suma queries adicionales. A escala (100 requests/min), la carga es manejable con los índices de la migración `b1c8f3d5a704` (SPEC-065).

3. **Índices requeridos:** la `check-externos-backend.sh` no valida esto, pero la migración es obligatoria:
   - `ix_messages_conversation_id_created_at` (compuesto, clave para tiempos de respuesta).
   - `ix_conversations_created_at` (filtro de rango de fechas).
   - `ix_conversations_canal` (filtro opcional por canal).

4. **Range limit:** para evitar queries runaway, `ANALYTICS_MAX_RANGE_DAYS` (default 366 en .env.example) detiene rangos muy grandes; un operador que necesite análisis de 2+ años debe usar múltiples queries.

---

## Tratamiento de borrado lógico (C2)

### Aplicación en cada métrica

Todas las métricas **excluyen** registros con `is_active = False`:

- **Conversaciones:** `Conversation.is_active = True`.
- **Mensajes:** `Message.is_active = True`.
- **Borradores IA:** `RagDraft.is_active = True`.

**Verificación:** tests de SPEC-065 cubren que un `SOFT DELETE` (UPDATE `is_active = false`) no es visible en ninguna métrica.

### Implicación para anonimización (HABEAS DATA)

- Anonimización (columna `Contact.anonymized_at`, SPEC-021) **no aplica directamente** a conversaciones/mensajes (el campo vive en `contacts`).
- Sin embargo, como la respuesta es **exclusivamente agregada** (conteos, promedios), jamás expone información individualizante de un contacto anónimo — el mensaje sigue contando en la métrica, pero sin PII (cero riesgo de re-anonimizar).

---

## Errores y casos límite

### Rango sin datos

```http
GET /api/v1/analytics/business?desde=2020-01-01&hasta=2020-01-02
```

Respuesta: HTTP 200 (no error). Todos los campos contienen valores "cero" o "nulo" según su semántica:

```json
{
  "desde": "2020-01-01",
  "hasta": "2020-01-02",
  "canal": null,
  "conversaciones": {
    "total": 0,
    "abiertas": 0,
    "cerradas": 0,
    "por_canal": [],
    "serie_diaria": [
      {"fecha": "2020-01-01", "total": 0},
      {"fecha": "2020-01-02", "total": 0}
    ]
  },
  "tiempos_respuesta": {
    "primera_respuesta_promedio_seg": null,
    "respuesta_promedio_seg": null,
    "conversaciones_con_respuesta": 0
  },
  "conversion": {
    "tasa": null,
    "cerradas": 0,
    "totales": 0
  },
  "ia_asistencia": null
}
```

**Rationale:** "no data" (200 + nulls/0s) vs "error" (4xx/5xx). Permite que el frontend maneje ausencia de datos de forma limpia, sin introducir try-catch innecesarios. El operador leerá "sin conversaciones en este rango" como expected.

### Canal no válido

```http
GET /api/v1/analytics/business?desde=2026-09-20&hasta=2026-09-27&canal=telegram
```

(Asumiendo que `CANALES_VALIDOS = {"whatsapp", "webchat", "email"}`)

Respuesta: HTTP 422 Unprocessable Entity.

```json
{
  "detail": "canal inválido: debe ser uno de ['email', 'webchat', 'whatsapp']"
}
```

### Rango invertido

```http
GET /api/v1/analytics/business?desde=2026-09-27&hasta=2026-09-20
```

Respuesta: HTTP 422.

```json
{
  "detail": "El parámetro 'desde' no puede ser posterior a 'hasta'."
}
```

### RLS efectiva (ninguna fuga de datos)

Cada request es ejecutado en una sesión PostgreSQL con `SET LOCAL app.tenant_id = '<id_del_jwt>'` (fijado en `get_tenant_db`). La política RLS en tablas `Conversation`, `Message`, `RagDraft` **FORCE ROW LEVEL SECURITY** (ADR-004/ADR-008) garantiza que:

- Un usuario del tenant A NUNCA ve conversaciones del tenant B, independientemente de lo que query haga.
- Los tests de SPEC-065 verifican esto con fixtures de múltiples tenants.

---

## Referencias

- **SPEC-064:** Implementación de vista de analítica de negocio (SPA + endpoint + tests).
- **SPEC-065:** Tests de cobertura y performance (p95 latencia, benchmarking).
- **SPEC-062:** Especificación de servicio de agregación (lógica de cálculo).
- **PLAN-007:** Plan de la fase de analítica de negocio (definiciones del Lead Q1–Q4).
- **ADR-004 / ADR-008:** Decisiones de Row Level Security.
- **SPEC-021:** HABEAS DATA y borrado lógico (C2).
- **backend/app/services/analytics_service.py:** Implementación de cálculos.
- **backend/app/api/analytics.py:** Router HTTP y validación.

---

**Última actualización:** 2026-09-28 (SPEC-066) · **Clasificación:** SENSIBLE (`.no-externo`)
