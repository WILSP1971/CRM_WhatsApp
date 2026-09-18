# ADR-005 — Bloqueo de egress del contenedor de IA (garantía técnica de "cero externos")

> Autor: 🔮 DOCTOR STRANGE — Lead de Arquitectura y Specs (Nivel 1)
> Proyecto: `/home/swarm/proyectos/CRM_WhatsApp` · Clasificación: **SENSIBLE** (`.no-externo`)
> Origen: `PLAN-002.md` (§3.2/§3.3, F0/F4/F7, riesgo R-22, CE-21), `SPEC-011` (infra), `SPEC-016` (IA local)

- **Estado:** Aceptada
- **Fecha:** 2026-09-18

---

## Contexto

La clasificación **SENSIBLE** (`.no-externo`) exige **cero llamadas salientes de inferencia a
terceros** y, más ampliamente, que el componente que procesa datos personales para IA **no pueda salir
a internet**. **ADR-003** decide que LLM y embeddings son locales; pero una decisión de configuración
de la aplicación **no basta** como garantía: un error, una librería o un cambio de config podrían
introducir una llamada externa (riesgo **R-22**, criterio **CE-21**).

Se necesita una **garantía técnica**, defensiva en profundidad y **auditable de forma reproducible**,
de que el contenedor de IA **no tiene ruta a internet**, independientemente de lo que haga la app.

---

## Decisión

Se adopta un **aislamiento de red en varias capas** para el contenedor de IA, con auditoría automatizada:

1. **Red Docker `internal: true`:** el contenedor de IA se conecta **solo** a una red Docker interna
   **sin puente a la red por defecto ni a internet**; no expone ni consume puertos hacia el exterior.
   La API le habla por **HTTP interno** (127.0.0.1 / red interna).
2. **Firewall a nivel host (defensa en profundidad):** reglas iptables/nftables que hacen **DROP** de
   todo tráfico saliente originado por el contenedor de IA hacia rangos **no privados**, por si la red
   Docker cambiara.
3. **Sin proxy/DNS externos:** ninguna variable de proxy ni resolutor DNS externo para ese contenedor
   (DNS interno o vacío).
4. **Pesos montados localmente:** los modelos se descargan y montan como **volumen** en build/aprovisionamiento;
   **nunca** hay `pull`/descarga en runtime hacia internet (coherente con ADR-003).
5. **Auditoría reproducible (equivalente backend del `check:externos`):**
   - **`check-externos-backend.sh`** escanea código/config del backend en CI buscando URLs/dominios
     externos, SDKs de IA de terceros y endpoints de inferencia remota; **falla el CI** si aparece alguno.
   - **Prueba de egress vacío** (HAWKEYE): desde el contenedor de IA se intenta alcanzar dominios
     externos (p. ej. `api.openai.com`, `8.8.8.8`) y **debe fallar** (timeout/deny); evidencia en CI.
   - **Captura de red** durante una corrida RAG e2e: se verifica (netstat/pcap/log de conexiones) que
     **no** hay conexiones salientes del contenedor de IA a IPs públicas.

---

## Alternativas consideradas

| Alternativa                                                | Por qué se descartó                                                                                                                                                       |
| ---------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Confiar solo en la configuración de la app**             | **Insuficiente** como garantía: un bug, una dependencia o un cambio de env podrían abrir una llamada externa sin que la política se rompa "en papel". No es defensa en profundidad. |
| **Proxy con allowlist de dominios**                        | **Innecesario**: si no hay egress permitido, no hace falta un proxy que decida qué se permite. Añade superficie y complejidad sin beneficio (no se necesita ninguna salida). |
| **Bloqueo solo por red Docker interna (sin firewall host)** | Buena base, pero un cambio de topología de red podría reintroducir ruta a internet; el **firewall host** añade la segunda capa de defensa.                                |
| **Auditoría manual puntual**                               | No reproducible ni continua; se automatiza en CI (`check-externos-backend.sh` + prueba de egress) para que **falle** ante cualquier regresión.                            |

---

## Consecuencias

**Pros**

- **Garantía técnica** (no solo declarativa) de la política SENSIBLE: el contenedor de IA **no puede**
  salir a internet, con defensa en profundidad (red interna + firewall host).
- **Auditable y reproducible** en CI: cualquier regresión que introduzca egress **rompe la build**.
- Coherente con ADR-003: pesos locales, inferencia solo por HTTP interno.

**Cons / mitigaciones**

- **Descarga de pesos** no puede hacerse en runtime → se resuelve haciéndola en **build/volumen**
  durante el aprovisionamiento (documentado en README/runbook, SPEC-023).
- El firewall host es específico del entorno → se documenta y versiona la configuración; revisión de
  QUICKSILVER/BLACK WIDOW en el deploy on-prem.
- Diagnosticar problemas de IA es más "cerrado" (sin internet) → logs internos y `/healthz` del
  contenedor de IA para operación (observabilidad, F8).

**Criterio de verificación (objetivo y verificable)**

- **CE-21**: el contenedor de IA con egress bloqueado + `check-externos-backend.sh` en verde + prueba
  de egress vacío + captura de red **sin dominios externos** durante RAG e2e.
- Un **intento de egress** desde el contenedor de IA hacia una IP/dominio público **debe fallar**
  (timeout/deny), con evidencia registrada en CI.
- La red de IA declara `internal: true` y no expone puertos externos; los pesos están en volumen local
  (no hay `pull` en runtime).
- Revisión de **BLACK WIDOW**: egress bloqueado, ausencia de SDKs externos, secretos en env (C3).

---

## Referencias

- `PLAN-002.md` — §3.2 (bloqueo de egress), §3.3 (auditoría backend), F0/F4/F7, riesgo **R-22**, **CE-21**, DoD §2.
- `SPEC-011` — Infra base + Docker Compose (red interna sin egress) + CI backend.
- `SPEC-016` — IA local self-hosted con verificación de egress bloqueado/auditoría.
- Relacionado: **ADR-003** (IA local: pesos locales, inferencia interna), **ADR-004** (aislamiento multi-tenant).
- `scripts/puede-modelo-externo.sh` — política de modelo externo del enjambre (criterio reutilizado).
