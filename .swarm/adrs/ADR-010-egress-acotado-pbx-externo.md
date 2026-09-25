# ADR-010 — Egress acotado del PBX externo para la descarga de grabaciones (análogo a ADR-006) — SOLO si el PBX es externo

> Autor: 🔮 DOCTOR STRANGE — Lead de Arquitectura y Specs (Nivel 1)
> Proyecto: `/home/swarm/proyectos/CRM_WhatsApp` · Clasificación: **SENSIBLE** (`.no-externo`)
> Origen: `PLAN-004.md` (§3.2/§3.3/§3.4, F0/F2, riesgo R-45, CE-42), `SPEC-035`, `SPEC-037`, `SPEC-042`

- **Estado:** Aceptada — **condicionada** (aplica SOLO si el PBX es externo; contingencia documentada bajo SUP-42, PBX preferido on-prem)
- **Fecha:** 2026-09-19

---

## Contexto

El Entregable #4 ingiere grabaciones de llamadas. Por **SUP-42** (aprobado con el PLAN-004), el PBX se asume
**on-prem** (Asterisk/FreeSWITCH) que entrega el **fichero por webhook/spool**: en esa topología preferida **no
hay egress nuevo** y este ADR **no aplica en operación**. Sin embargo, si el Lead confirma que el PBX es
**externo** (p. ej. un proveedor cloud) y solo notifica una **URL**, hay que **descargar** la grabación desde
un host público, lo que introduce un borde de egress. Se documenta este ADR como **decisión firme y
contingencia lista** para ese caso, análogo a ADR-006 (transporte del canal WhatsApp a `graph.facebook.com`).

La distinción clave: descargar la grabación es **TRANSPORTE del canal** (traer el audio que el PBX ya generó),
**no una llamada de inferencia** ni un envío de audio-a-terceros. El invariante duro de la fase (ADR-009) sigue
intacto: el **audio y el STT/IA nunca salen**; lo único que puede salir es la **petición de descarga al PBX**.

---

## Decisión

Se adopta una **excepción acotada y auditable** a `.no-externo` para la descarga de grabaciones, **activable
solo si el PBX es externo**, con las siguientes reglas duras:

1. **Egress permitido SOLO desde `api` y/o un `recording_fetch_worker`** en la red `app`, y **SOLO** hacia el
   **único host del PBX** (allowlist). Ningún otro contenedor ni dominio tiene salida nueva.
2. **El STT/IA permanece totalmente aislado** (reafirma ADR-009/ADR-005): `stt_worker`, `ia`, `rag_worker`,
   `sentiment_worker` viven en `ia_internal internal:true`, **nunca** se conectan a `app` con egress, y **jamás**
   obtienen ruta al PBX ni a internet. El `stt_worker` recibe el audio del **almacén cifrado on-prem**, no de la
   descarga.
3. **Allowlist por RUTA de módulo** en `check-externos-backend.sh`: el host del PBX se permite **solo** dentro
   del módulo del conector de descarga (`app/services/telefonia/` o `app/integrations/pbx/`); si aparece en
   cualquier otro módulo → **falla el CI** (transporte fuera del conector = fuga). El STT/IA que importe el
   cliente httpx de descarga **falla** la build; el conector que importe/llame STT/IA **falla** la build.
4. **Firewall a nivel host** que garantiza que el único egress público sea la descarga desde
   `api`/`recording_fetch_worker` al host del PBX.
5. **Credenciales del PBX y `verify_token`/firma** SOLO en env/secret manager (C3), nunca en repo/logs.
6. **Si el PBX es on-prem (topología preferida, SUP-42), este ADR NO habilita ningún egress**: el
   `recording_fetch_worker` se entrega inerte y la allowlist pública permanece deshabilitada.

---

## Alternativas consideradas

| Alternativa | Por qué se descartó |
| ----------- | ------------------- |
| **Que el `stt_worker`/IA descargue directamente del PBX** | Daría al STT/IA ruta a internet/PBX: rompe el aislamiento (ADR-009/ADR-005) y el invariante de la fase. Prohibido. |
| **Dar egress a toda la red `app`** | Amplía la superficie de salida a componentes que no lo necesitan; se restringe a `api`/`recording_fetch_worker` + allowlist por ruta. |
| **BSP/intermediario que procese el audio** | Un tercero **vería el audio** (dato personal/PHI): contradice SENSIBLE más aún que el transporte directo. Descartado. |
| **Prohibir todo egress incluso con PBX externo** | Imposibilitaría ingerir grabaciones de un PBX externo. Se resuelve con transporte acotado (este ADR) manteniendo el audio/STT sin salida. |
| **Allowlist a nivel de red sin distinción por módulo de código** | No impide que el transporte se introduzca en módulos indebidos (p. ej. la IA). Se complementa con allowlist por ruta en el CI. |

---

## Consecuencias

**Pros**
- Habilita la ingesta desde un PBX externo **sin** romper el invariante: el audio y el STT/IA siguen sin salida (ADR-009).
- Egress mínimo, explícito y **auditable por ruta** (CI) + firewall host; regresiones rompen la build.
- Si el PBX es on-prem, **no se abre ningún egress** (topología preferida, cero superficie nueva).

**Cons / mitigaciones**
- Aparece un borde de egress condicional (riesgo R-45) → invariante de topología §3.2, allowlist por ruta,
  firewall host, prueba de egress vacío desde STT/IA + captura de red (SPEC-042).
- Depende del entorno (firewall host, red Docker) → se versiona y documenta (SPEC-035/043); revisión
  QUICKSILVER/BLACK WIDOW en el deploy.
- Habilitar el egress externo es cambio sensible → aprobación explícita del Lead + notificación Telegram (C6).

**Criterio de verificación (objetivo y verificable)**
- **Prueba de egress:** un intento de salida desde `stt_worker`/`ia`/`rag_worker`/`sentiment_worker` hacia
  cualquier IP/dominio público **debe fallar** (timeout/deny), con evidencia en CI (SPEC-042).
- (Si PBX externo) `api`/`recording_fetch_worker` alcanzan **solo** el host del PBX y **ningún** otro dominio
  público (captura de red).
- `check-externos-backend.sh` en verde con allowlist por ruta; test negativo (transporte fuera del conector, o
  STT/IA importando el cliente de descarga) **falla** la build.
- (Si PBX on-prem) **cero** egress público en la captura de red.

---

## Referencias

- `PLAN-004.md` — §3.2 (invariante de topología), §3.3 (aislamiento STT/IA), §3.4 (allowlist por ruta), §11
  (ADR-010), §12 (SUP-42), R-45, CE-42, DoD §3.
- `SPEC-035` — Infra: `recording_fetch_worker` + allowlist host PBX por ruta (si externo).
- `SPEC-037` — Conector de ingesta de grabaciones (transporte) + descarga acotada.
- `SPEC-042` — Prueba de egress (STT/IA sin salida; si externo, solo al host del PBX).
- Relacionado: **ADR-006** (excepción de egress transporte WhatsApp, patrón análogo), **ADR-009** (STT local +
  aislamiento, reafirmado), **ADR-005** (bloqueo de egress de IA).
- `scripts/check-externos-backend.sh` — auditoría "cero audio/inferencia a terceros + descarga acotada".
