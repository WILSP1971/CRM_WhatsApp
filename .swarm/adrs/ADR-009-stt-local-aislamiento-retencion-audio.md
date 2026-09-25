# ADR-009 — STT 100% local + aislamiento del `stt_worker` + retención/anonimización del audio (dato personal / posible PHI)

> Autor: 🔮 DOCTOR STRANGE — Lead de Arquitectura y Specs (Nivel 1)
> Proyecto: `/home/swarm/proyectos/CRM_WhatsApp` · Clasificación: **SENSIBLE** (`.no-externo`)
> Origen: `PLAN-004.md` (§1/§3.2/§3.3, F0/F3/F6, riesgos R-41/R-42/R-43/R-44, CE-41/CE-42/CE-44), `SPEC-035`, `SPEC-036`, `SPEC-038`, `SPEC-039`, `SPEC-041`

- **Estado:** Aceptada
- **Fecha:** 2026-09-19

---

## Contexto

El Entregable #4 introduce el **audio de llamadas telefónicas como dato personal (posible PHI)**. La
clasificación **SENSIBLE** (`.no-externo`) prohíbe cualquier inferencia externa y que los componentes que
procesan datos personales salgan a internet (ADR-005: `ia_internal internal:true` + firewall host + auditoría).
El STT (speech-to-text) y cualquier TTS futuro procesan directamente ese audio; enviarlo a un servicio de STT
en la nube (Google STT, AWS Transcribe, OpenAI Whisper API, Deepgram, AssemblyAI, Azure Speech, etc.) supondría
entregar datos personales/PHI a un tercero, rompiendo la política con más fuerza aún que la inferencia de texto.

Además, el audio en reposo es un dato sensible que exige **cifrado**, una **política de retención** y **acceso
auditado** (HABEAS DATA/GDPR-like; PHI si el Lead lo confirma). Se necesita decidir (a) el motor de STT y su
provisión, (b) dónde vive el `stt_worker` respecto al borde de egress, y (c) el tratamiento del audio como dato
personal en su ciclo de vida.

Por SUP-44, el dimensionamiento por defecto es **GPU ≥16 GB** con `large-v3`; por SUP-45, el dominio por
defecto es **comercial/HABEAS DATA (Ley 1581) + GDPR-like**; por SUP-49, la retención de audio por defecto es
**30 días**.

---

## Decisión

1. **STT 100% local con `faster-whisper` self-hosted:** `large-v3` es-CO como base (RTF ≤ 1.0 objetivo en GPU
   batch), **fallback CPU/`medium`** (o `whisper.cpp`) con RTF degradado documentado; modelo/idioma
   parametrizables por env. **Los pesos se montan por volumen** (sin `pull`/descarga en runtime). **STT/TTS de
   terceros PROHIBIDOS** en todo el código (auditado por `check-externos-backend.sh`, SPEC-035).
2. **Aislamiento del `stt_worker`:** el `stt_worker` vive en `ia_internal internal:true` (comparte el
   aislamiento de la IA, ADR-005). **Nunca** se le añade la red `app` ni ruta a internet, y **jamás** alcanza
   el PBX. Recibe el audio desde el **almacén cifrado on-prem** (volumen/MinIO en red interna), **no** por red
   externa. Firewall host DROP para el STT/IA; prueba de egress vacío (SPEC-042).
3. **Audio como dato personal en su ciclo de vida:** el audio se **cifra en reposo** (volumen cifrado / cifrado
   de objeto MinIO), con **política de retención configurable** (por defecto **30 días** → purga/anonimización
   del audio y/o transcripción, SPEC-041) y **registro de acceso auditado** (quién/cuándo/qué). Si el Lead
   confirma **salud/PHI**, este ADR se **endurece**: cifrado de campo de la transcripción, retención estricta y
   acceso reforzado.

---

## Alternativas consideradas

| Alternativa | Por qué se descartó |
| ----------- | ------------------- |
| **STT en la nube (Google STT / AWS Transcribe / OpenAI Whisper API / Deepgram / AssemblyAI / Azure Speech)** | Enviaría el **audio (dato personal/PHI) a un tercero**: rompe SENSIBLE/`.no-externo` de forma directa. Prohibido. |
| **`stt_worker` en la red `app` (con egress) por comodidad** | Superficie de salida innecesaria: el STT no necesita internet ni el PBX (recibe el audio del almacén on-prem). Aumenta el riesgo R-41. Descartado a favor de `ia_internal internal:true`. |
| **Que el `stt_worker` descargue la grabación del PBX** | Rompe el aislamiento: daría al STT ruta al PBX/internet. La descarga (si aplica) es transporte del conector (ADR-010), nunca del STT. |
| **Audio en claro en disco** | Fuga de dato personal/PHI ante acceso indebido o backup. Se exige cifrado en reposo (R-43). |
| **Retención indefinida del audio** | Incumple HABEAS DATA/GDPR-like/PHI (R-44). Se fija retención configurable (por defecto 30 días) + purga/anonimización + acceso auditado. |

---

## Consecuencias

**Pros**
- El audio (dato personal/posible PHI) y la inferencia **nunca salen** del host: cumple SENSIBLE sin excepción.
- El `stt_worker` reutiliza el aislamiento ya probado de la IA (ADR-005); superficie de egress cero para STT/IA.
- Ciclo de vida del audio controlado: cifrado en reposo, retención configurable, acceso auditado; endurecible a PHI.

**Cons / mitigaciones**
- STT local exige GPU para RTF ≤ 1.0 con `large-v3` (R-42) → fallback CPU/`medium` documentado; N `stt_worker`
  escalables; batch tolerante a cola; medición THOR (SPEC-042).
- Gestión de pesos por volumen y de claves de cifrado → runbook + secretos en env (C3, SPEC-043).
- WER es-CO puede degradar el enriquecimiento (R-48) → el human-in-the-loop (SPEC-019/039) absorbe errores.

**Criterio de verificación (objetivo y verificable)**
- **Prueba de egress:** un intento de salida desde `stt_worker`/`ia`/`rag_worker`/`sentiment_worker` hacia
  cualquier IP/dominio público **debe fallar** (timeout/deny), con evidencia en CI/captura de red (SPEC-042).
- `check-externos-backend.sh` en verde con STT/TTS de terceros prohibidos; insertarlos **falla** la build.
- Grabación ficticia es-CO transcrita 100% local con segmentos + timestamps; **cero** STT de terceros; WER documentado (CE-41).
- Audio **cifrado en reposo** (inspección); retención por defecto (30 días) purga/anonimiza; acceso auditado (CE-44).

---

## Referencias

- `PLAN-004.md` — §1 (STT local), §3.2 (invariante de topología), §3.3 (aislamiento STT/IA), §11 (ADR-009),
  R-41/R-42/R-43/R-44, CE-41/CE-42/CE-44, DoD §2/§3/§4.
- `SPEC-035` — Infra STT local + almacén cifrado + auditoría de egress.
- `SPEC-036` — Datos `call`/`call_transcript` + RLS efectiva.
- `SPEC-038` — Worker STT `faster-whisper` es-CO (batch, sin egress).
- `SPEC-039` — Enriquecimiento IA local sobre la transcripción.
- `SPEC-041` — Retención/anonimización de audio + seguridad (extiende SPEC-021).
- Relacionado: **ADR-005** (bloqueo de egress de IA, reafirmado), **ADR-004/ADR-008** (RLS efectiva),
  **ADR-010** (egress acotado del PBX externo, si aplica).
- `scripts/check-externos-backend.sh` — auditoría "cero audio/inferencia a terceros".
