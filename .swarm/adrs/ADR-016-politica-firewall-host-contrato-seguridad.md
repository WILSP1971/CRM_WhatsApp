# ADR-016 — Política de firewall de host (`nftables`) como contrato de seguridad estructural por encima del aislamiento de red de Docker

> Autor: 🔮 DOCTOR STRANGE — Lead de Arquitectura y Specs (Nivel 1)
> Proyecto: `/home/swarm/proyectos/CRM_WhatsApp` · Clasificación: **SENSIBLE** (`.no-externo`)
> Origen: `PLAN-011.md` (§1 H-4/D-2, §3.1 (dos planos), §3.3, §3.5, §4 F3, §11.1 (ADR recomendado), R-108, CE-109/CE-111), `SPEC-083`

- **Estado:** Aceptada — aceptada implícitamente al aprobar el Lead el bloque completo de PLAN-011 §11.1 (recomendación del ADR) con "APROBADO PLAN-011" (2026-10-02).
- **Fecha:** 2026-10-02
- **Plan:** PLAN-011

---

## Contexto

Hasta hoy, la garantía de "cero externos" del backend on-prem se apoya en **dos mecanismos a nivel de aplicación/Docker**: (a) el **aislamiento de red de Docker** —`ia_internal` con `internal: true`, que bloquea el egress a internet de los servicios de IA/STT/observabilidad (ADR-005), y la red `app` con egress acotado solo a `graph.facebook.com` (ADR-006)—, más (b) el guardarraíl `check-externos-backend.sh`, que audita en CI que el **código/runtime** no introduce transportes externos no autorizados. Complementariamente, la app tiene defensa en profundidad propia: `_require_internal_ai_host()` (`config.py:609–632`) rechaza arrancar si `OLLAMA_BASE_URL` no resuelve a un host interno permitido.

**El hueco real está en la capa host/kernel, no en la app** (patrón idéntico al de PLAN-010/PLAN-011 §1.4): `DEPLOYMENT_CHECKLIST.md` (Fase 2) pide reglas `iptables`/`nftables` con DROP de egress de Ollama y restricción de los puertos `8000`/`5432`/`6379`/`11434`, pero **NO existe ningún script de firewall de host versionado** — es un checkbox fantasma, igual que el `backup-crm.sh` ausente de PLAN-010. Además, en `docker-compose.yml`, `db`/`redis`/`api` se publican a `0.0.0.0` (todas las interfaces), dependiendo enteramente de un firewall de host que hoy **no existe como artefacto**.

Añadir un **firewall de host (`nftables`)** que haga DROP del egress de IA y restrinja los puertos del host introduce un **segundo plano de control** que vive **por encima** del aislamiento de red de Docker: opera a nivel de **kernel del host**, independiente de que un contenedor, una red de Docker o una variable de entorno se reconfiguren mal en el futuro. No es "un detalle de implementación de la SPEC-083": define una **invariante estructural y duradera** —el host NO permite egress de IA ni expone `db`/`redis` a internet— que condiciona todo despliegue futuro y que BLACK WIDOW debe poder **citar como contrato auditable**, al mismo nivel que ADR-005/006/010 fijan el egress. Un script sin ADR sería un artefacto frágil, sin la fuerza normativa del resto de decisiones de egress del proyecto.

Decisiones del Lead ya **VINCULANTES** que enmarcan este ADR (PLAN-011 §7.1, no se reabren): hardening SOBRE el `docker-compose` actual, deploy manual, **sin CD/staging** (Q3=A); **sin servidor de producción dedicado confirmado** todavía; el escaneo de CVEs online corre en el **runner de CI**, nunca desde el host aislado (Q5=A); backups **DIFERIDOS** (Q6=A, fuera de alcance).

Este ADR **NO es un ADR de egress nuevo**: el firewall **REDUCE** egress (DROP de IA), no lo amplía — por eso **refuerza** ADR-005, no lo contradice. Es un ADR de **contrato de hardening de host**.

---

## Decisión

Se adopta la **política de firewall de host (`nftables`) como contrato de seguridad estructural**, versionado en el repo (`scripts/ops/`), con las siguientes reglas duras:

1. **El firewall de host es defensa en profundidad POR ENCIMA de `ia_internal`, NO una sustitución.** El aislamiento de red de Docker (`ia_internal internal: true`, ADR-005) **se conserva intacto** como primera línea; el firewall de host es una **segunda línea independiente** a nivel de kernel. Ninguno sustituye al otro: si uno falla o se reconfigura mal, el otro sigue conteniendo el egress. **PROHIBIDO** relajar `ia_internal` apoyándose en que "ya está el firewall", y viceversa. Ambos deben estar presentes.

2. **Invariante de egress/exposición del host (lo que el firewall garantiza).** El host, con la política aplicada:
   - **DENIEGA (DROP)** el egress de IA a internet (refuerza `ia_internal`/`_require_internal_ai_host`, ADR-005).
   - **NO expone** `db` (`5432`), `redis` (`6379`) ni `11434` (Ollama) a interfaces públicas; `db`/`redis` quedan en red Docker interna/loopback (SPEC-083 retira sus `ports:` de `0.0.0.0`); `11434` ya está en `127.0.0.1` (patrón `ia`).
   - **PERMITE** únicamente los puertos entrantes legítimos del borde: el del reverse-proxy/TLS entrante de Caddy (p. ej. `443`/`80` para ACME cuando haya dominio real) y `api` **solo tras loopback/reverse-proxy** (`127.0.0.1:8000`), nunca `0.0.0.0:8000`.
   - El egress entrante/saliente del único transporte externo autorizado (`graph.facebook.com`, ADR-006) **no se altera**.

3. **El script de firewall NO se aplica automáticamente en NINGÚN pipeline (C6).** Se entrega **versionado + documentado**, pero su aplicación en un entorno real es un **cambio sensible** (C6) que requiere **aprobación explícita del Lead + notificación** antes de ejecutarse. Ningún workflow de CI/CD aplica `nftables` al host. Esto es coherente con "deploy manual, sin CD" (Q3=A) y evita que un pipeline deje un host incomunicado.

4. **La validación ACME/TLS entrante es un borde ENTRANTE acotado, no un egress de datos nuevo.** Cuando se active el TLS de producción de Caddy con un dominio real (SPEC-083), ACME/Let's Encrypt requerirá un intercambio en el **borde entrante** (emisión/renovación del certificado). Esto es **transporte de borde entrante acotado**, análogo a cómo ADR-010 distingue "descargar una grabación" (transporte del canal) de "una llamada de inferencia": **no es un egress de datos de negocio/PHI**, no envía audio/transcripciones ni datos de tenant a terceros. Por tanto **no contradice ADR-005/006/010** ni exige un ADR de egress de datos; la política de firewall debe **permitir** ese borde entrante acotado sin abrir egress de datos.

**Este ADR consume, no rediseña, ADR-005 (aislamiento `ia_internal`/self-hosted) y ADR-006/010 (egress acotado del canal).** El aislamiento de red ya funciona; este ADR fija la capa de host que lo envuelve y lo refuerza.

---

## Alternativas consideradas

| Alternativa | Por qué se descartó |
| ----------- | ------------------- |
| **Ningún firewall de host: confiar solo en `ia_internal` + `check-externos-backend.sh`** | Deja el checkbox del `DEPLOYMENT_CHECKLIST.md` como fantasma (igual que el `backup-crm.sh` ausente de PLAN-010) y `db`/`redis`/`api` publicados a `0.0.0.0` dependientes de un firewall inexistente. Una sola capa (red de Docker) sin defensa en profundidad a nivel de host es frágil ante una reconfiguración futura de contenedores/redes. Descartada: el hardening exige la segunda línea a nivel de kernel. |
| **Script de firewall SIN ADR (solo artefacto en `scripts/ops/`)** | Un script sin registro arquitectónico es frágil y sin fuerza normativa: futuros cambios podrían erosionar la invariante sin que nadie pueda citar el contrato. BLACK WIDOW no tendría un documento auditable al nivel de ADR-005/006/010. Descartada: la política trasciende la SPEC-083 y merece ADR propio (§11.1). |
| **Aplicar el firewall automáticamente en un pipeline de deploy** | Contrario a Q3=A (deploy manual, sin CD) y peligroso: un pipeline que aplica `nftables` podría dejar el host incomunicado sin supervisión. Aplicar el firewall es C6 (cambio sensible → aprobación + notificación). Descartada. |
| **Tratar la validación ACME entrante como un egress nuevo que exige ADR de egress de datos** | ACME/TLS entrante es transporte de **borde entrante acotado** (emisión de certificado), no envío de datos de negocio/PHI a terceros — análogo a la distinción de ADR-010. Modelarlo como egress de datos sería incorrecto y añadiría un ADR de egress innecesario. Descartada: se fija como borde entrante acotado dentro de ESTE ADR. |
| **Un firewall de host que SUSTITUYA a `ia_internal`** (quitar `internal: true` confiando en el firewall) | Elimina la defensa en profundidad: una sola capa a nivel de kernel es tan frágil como una sola capa de Docker. PROHIBIDO relajar `ia_internal` apoyándose en el firewall. Descartada: ambas capas coexisten. |

---

## Consecuencias

**Pros**
- **Defensa en profundidad real:** el host contiene el egress de IA y la exposición de `db`/`redis` incluso si una red/contenedor de Docker se reconfigura mal en el futuro; `ia_internal` (ADR-005) y el firewall se cubren mutuamente.
- **Contrato auditable y citable:** la invariante "el host no permite egress de IA ni expone `db`/`redis` a internet" queda registrada al nivel de ADR-005/006/010; BLACK WIDOW puede citarla; el checkbox del `DEPLOYMENT_CHECKLIST.md` deja de ser fantasma y apunta a un artefacto real (`scripts/ops/`, CE-113/SPEC-084).
- **Refuerza, no amplía, el egress:** el firewall hace DROP de IA → es coherente con y refuerza ADR-005; `check-externos-backend.sh` sigue verde sin relajar su allowlist.
- **Sin egress de datos nuevo:** la validación ACME entrante es un borde entrante acotado (no PHI/negocio a terceros); no contradice ADR-005/006/010.
- **Aditivo y seguro por defecto:** el script se entrega versionado pero **no se aplica automáticamente** (C6); no hay riesgo de que un pipeline incomunique un host.

**Cons / mitigaciones**
- **Introduce una capa operativa a nivel de host** (aplicar `nftables` en el entorno real) → se documenta en `DEPLOYMENT_CHECKLIST.md` (SPEC-084, CE-113); su aplicación es C6 (aprobación del Lead + notificación). El `RUNBOOK.md` operativo no se reescribe (Q2=A).
- **Un firewall mal aplicado podría romper el acceso legítimo** (healthchecks, migraciones, el borde entrante de Caddy) → SPEC-083 verifica que healthchecks (por red Docker interna) y migraciones siguen funcionando y que `api` queda tras loopback/reverse-proxy (R-108/CE-109); el script permite el borde entrante acotado de Caddy/ACME.
- **No hay servidor de producción dedicado confirmado todavía** (Q3=A) → el script se dimensiona como parametrizable/documentado sobre el `docker-compose` actual, listo para aplicarse cuando exista el entorno real, sin asumir topología concreta.
- **Secretos (C3):** el script de firewall **no** contiene credenciales; cualquier parámetro sensible (dominio/ACME del TLS asociado) va por env, nunca en el repo ni en logs, nunca generado por el agente.

**Criterio de verificación (objetivo y verificable — consolidado en SPEC-083/SPEC-084)**
- **Puertos restringidos (CE-109):** `nmap`/`ss` del host sin `5432`/`6379` en `0.0.0.0`; `api` tras loopback/reverse-proxy; healthchecks *healthy* y migraciones OK.
- **Firewall versionado + aislamiento reforzado (CE-111):** script `nftables` (DROP egress IA + restricción de puertos) presente y documentado; `ia_internal` reforzado; `check-externos-backend.sh` verde sin relajar allowlist; este ADR presente.
- **No se aplica automáticamente (C6):** ningún pipeline aplica el firewall; documentado como cambio sensible.
- **Sin egress de datos nuevo:** `check-externos-backend.sh` verde; `graph.facebook.com` (ADR-006) intacto; la validación ACME entrante es borde entrante acotado, no egress de datos.

---

## Referencias

- `PLAN-011.md` — §1 (H-4/D-2, invariantes §1.4), §3.1 (dos planos CI vs runtime), §3.3 (red y puertos), §3.5 (por qué no hay egress nuevo y qué ADR sí se justifica), §4 F3, §11.1 (ADR recomendado — aceptado en bloque), R-108, CE-109/CE-111, DoD §10.
- `SPEC-083` — Materializa este ADR: script de firewall `nftables` versionado (`scripts/ops/`), `db`/`redis`/`api` sin `ports:` a `0.0.0.0`, config TLS de producción de Caddy (ACME/dominio por env).
- `SPEC-084` — Verifica la invariante (puertos cerrados, `ia_internal` reforzado, `check-externos-backend.sh` verde sin relajar allowlist) y la referencia en `DEPLOYMENT_CHECKLIST.md` (CE-113); cierra el DoD de PLAN-011.
- **Consume (no rediseña):** `ADR-005` (aislamiento `ia_internal`/self-hosted CPU-only, sin egress de IA), `ADR-006` (egress acotado a `graph.facebook.com`), `ADR-010` (egress acotado del PBX externo / distinción transporte vs egress de datos).
- Código/artefactos: `docker-compose.yml` (`ports:` de `db`/`redis`/`api`; `ia` `127.0.0.1:11434`; observabilidad sin `ports:`), `backend/app/core/config.py:609–632` (`_require_internal_ai_host`), `backend/check-externos-backend.sh`, `Caddyfile` (borde entrante / TLS), `DEPLOYMENT_CHECKLIST.md` (Fase 2), `scripts/ops/` (script de firewall, nuevo en SPEC-083).
