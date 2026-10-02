"""SPEC-060 — Certificado de trazabilidad CE-61..CE-65 (Entregable #5: notas
de voz de WhatsApp, SPEC-053..059) — HAWKEYE.

Este archivo NO reimplementa las pruebas: es el punto único y legible que
mapea cada criterio de aceptación de SPEC-060 al/a los test(s) reales que lo
verifican (algunos preexistentes de SPEC-053..059, otros añadidos por
SPEC-060 para cerrar huecos genuinos de observabilidad/cobertura). Contiene
solo tests "espejo" triviales que ejecutan/re-verifican el mapeo declarado
en cada docstring — la evidencia dura vive en los archivos citados.

Resumen ejecutivo de la auditoría SPEC-060 (ver informe completo de HAWKEYE
para el detalle de comandos/salidas):

  - CE-61 (e2e descarga -> STT local -> Message.contenido, cero STT de
    terceros): YA CUBIERTO por SPEC-054/055/056, sin huecos.
  - CE-62 (enriquecimiento reutilizado, sin TTS): YA CUBIERTO por SPEC-057,
    sin huecos.
  - CE-63 (idempotencia wamid + cross-tenant Message/audio_ref con RLS
    real): YA CUBIERTO. El test cross-tenant específico sobre
    `Message.audio_ref` con el rol de aplicación real (`app_engine`, NO
    `postgres_engine`) YA EXISTÍA en
    `tests/test_messages_voice_note_data.py::
    test_messages_audio_cross_tenant_isolation` (+ variantes directas por id
    y sin tenant fijado) — verificado, no duplicado.
  - CE-64 (límite de duración -> auto-respuesta, sin job STT, descarte
    auditado): YA CUBIERTO por SPEC-055, sin huecos.
  - CE-65 (no-regresión #1-#4): VERIFICADO explícitamente contra
    `git log`/`git diff` commit a commit desde SPEC-038 (7d4713c) hasta
    SPEC-057 (1c8eea3) — ningún assert de un test PREEXISTENTE del sink
    `call` fue modificado; solo se añadieron tests nuevos y, en un caso
    (2252ef7), se corrigió el FIXTURE inyectado (`postgres_engine` ->
    `app_engine`) de dos tests para eliminar un falso positivo de RLS
    detectado contra Postgres real — el/los ASSERT(s) de esos dos tests no
    cambiaron de contenido.
  - Observabilidad (RF explícito de SPEC-060): GENUINAMENTE NUEVO — no
    existía NINGUNA métrica para descargas de media/descartes por duración.
    Añadidas en `app/core/metrics.py`
    (`increment_whatsapp_media_downloads`/
    `increment_whatsapp_audio_discarded_by_duration`), instrumentadas en
    `app/integrations/whatsapp/media_client.py` y
    `app/workers/whatsapp_inbound_worker.py`. Sin label `tenant_id` (decisión
    de diseño reafirmada, ver docstring de `app/core/metrics.py`) — la
    desagregación por tenant vive en los logs estructurados existentes.
  - Cobertura del código nuevo: medida real con `pytest --cov` (no
    estimada), ver detalle por módulo en cada sección de este archivo.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# CE-61 — e2e: descarga (solo graph.facebook.com) + STT local (sink
# `message`) + Message.contenido; cero STT de terceros.
# ---------------------------------------------------------------------------
#
#   - tests/test_whatsapp_inbound_worker.py::
#       test_process_job_audio_message_creates_message_and_downloads
#       (e2e: descarga real simulada vía httpx.MockTransport + persistencia
#       de audio_ref/mime_type cifrado)
#   - tests/test_whatsapp_inbound_worker.py::
#       test_process_job_audio_within_limit_enqueues_stt_job_with_message_destino
#       (encolado en stt:jobs con destino="message:{id}")
#   - tests/test_stt_worker.py::
#       test_process_job_message_sink_updates_existing_message_without_call_artifacts
#       (el sink `message` transcribe local con faster-whisper — mismo motor
#       que el sink `call`, SIN cliente STT de terceros — y escribe
#       Message.contenido/transcripcion_estado="ok", sin crear
#       CallTranscript/Call/Message nuevo, ADR-013)
#   - tests/test_egress_topology_guardrail.py (todo el archivo): `stt_worker`
#     permanece EXCLUSIVAMENTE en la red `ia_internal` (internal:true, sin
#     egress) — cero salida posible a un STT de terceros a nivel de
#     topología de red, no solo de código.
#   - check-externos-backend.sh (sección "graph.facebook.com" + sección
#     media_client/GraphMediaClient no importable desde STT/IA): confirma
#     por código que la descarga SOLO ocurre en
#     app/integrations/whatsapp/media_client.py y NUNCA se importa desde
#     app.workers.stt_worker ni ningún módulo de IA.


def test_ce61_media_client_only_reachable_from_whatsapp_module():
    """Espejo ejecutable del guardarraíl de check-externos-backend.sh
    (sección 8): `media_client`/`download_and_store_voice_note`/
    `GraphMediaClient` no deben aparecer en ningún módulo de
    `app.workers.stt_worker` ni `app.services.ai_service` (cero acoplamiento
    de descarga hacia el STT/IA, CE-61)."""
    forbidden_modules = [
        _BACKEND_ROOT / "app" / "workers" / "stt_worker.py",
        _BACKEND_ROOT / "app" / "services" / "ai_service.py",
    ]
    needles = ("media_client", "download_and_store_voice_note", "GraphMediaClient")
    for module_path in forbidden_modules:
        assert module_path.is_file(), f"No se encontró {module_path}"
        content = module_path.read_text(encoding="utf-8")
        for needle in needles:
            assert needle not in content, (
                f"REGRESIÓN CE-61: '{needle}' aparece en {module_path} — el "
                "STT/IA nunca debe poder descargar media (ADR-009)"
            )


# ---------------------------------------------------------------------------
# CE-62 — enriquecimiento reutilizado (sentimiento + borrador RAG >=3 citas),
# respuesta en texto con human-in-the-loop, sin TTS de salida (ADR-013).
# ---------------------------------------------------------------------------
#
#   - tests/test_stt_worker.py::
#       test_process_job_message_sink_dispatches_sentiment_job_on_transcript
#   - tests/test_stt_worker.py::
#       test_process_job_message_sink_creates_proposed_rag_draft_with_citations
#       (>=3 citas trazables, estado "propuesto")
#   - tests/test_stt_worker.py::
#       test_process_job_message_sink_rag_draft_never_auto_sent
#       (NUNCA se auto-envía — aprobación humana explícita, ADR-013)
#   - tests/test_stt_worker.py::
#       test_process_job_message_sink_reprocessing_ok_does_not_redispatch_ai_pipeline
#       (no se re-dispara el pipeline IA en un reproceso ya "ok")
#   - Ausencia de TTS: ningún módulo de `app/workers/stt_worker.py` ni
#     `app/workers/whatsapp_inbound_worker.py` importa un cliente de síntesis
#     de voz (verificable por inspección — no existe tal dependencia en
#     requirements.txt para el canal de mensajería; `voice_tts`, SPEC-044,
#     es exclusivo del canal de voz EN VIVO, un slice completamente distinto).


def test_ce62_messaging_workers_do_not_import_tts_client():
    """Espejo ejecutable: ni el worker de ingesta de WhatsApp ni el sink de
    transcripción importan ningún cliente de texto-a-voz (ADR-013, "sin TTS
    de salida" para el canal de mensajería asíncrona)."""
    modules = [
        _BACKEND_ROOT / "app" / "workers" / "whatsapp_inbound_worker.py",
        _BACKEND_ROOT / "app" / "workers" / "stt_worker.py",
    ]
    tts_needles = ("tts", "text_to_speech", "texto_a_voz", "synthesize_speech")
    for module_path in modules:
        content = module_path.read_text(encoding="utf-8").lower()
        for needle in tts_needles:
            assert needle not in content, (
                f"REGRESIÓN CE-62/ADR-013: posible referencia a TTS "
                f"('{needle}') en {module_path} — el canal de mensajería "
                "responde SOLO en texto (human-in-the-loop)"
            )


# ---------------------------------------------------------------------------
# CE-63 — idempotencia por wamid (sin re-descarga/re-transcripción/
# duplicado, sin call_id) + cross-tenant sobre Message/audio_ref con RLS
# real (rol app no-superusuario).
# ---------------------------------------------------------------------------
#
#   - tests/test_whatsapp_inbound_worker.py::
#       test_process_job_audio_duplicate_wamid_does_not_duplicate_message_or_job
#   - tests/test_stt_worker.py::
#       test_process_job_message_sink_reprocessing_already_ok_is_noop
#   - tests/test_whatsapp_inbound_worker.py::
#       test_process_job_audio_creates_zero_call_or_call_transcript_rows
#       (sin call_id / sin entidad `call`, ADR-013)
#   - tests/test_messages_voice_note_data.py::
#       test_messages_audio_cross_tenant_isolation (CE-63, VERIFICADO
#       PREEXISTENTE — usa `app_engine`, rol `omnicore_app` NO-superusuario,
#       ADR-008 — sobre `Message`/`audio_ref` con `tipo='audio'`; sin este
#       rol el test pasaría por accidente ante un superusuario que ignora
#       RLS, ver docstring del propio test)
#   - tests/test_messages_voice_note_data.py::
#       test_messages_audio_cross_tenant_direct_select_by_id_returns_zero_rows
#       (lectura directa por id de otro tenant -> 0 filas)
#   - tests/test_messages_voice_note_data.py::
#       test_messages_session_without_tenant_sees_zero_audio_rows
#       (fail-closed sin tenant fijado)
#
# NOTA DE AUDITORÍA (punto 2 del encargo SPEC-060): este test cross-tenant
# específico sobre `Message.audio_ref` YA EXISTÍA antes de SPEC-060 (no se
# duplicó). Se confirmó que usa `app_engine`/RLS real, no `postgres_engine`
# (que evade RLS por ser superusuario/owner) — cumple el criterio exacto que
# pedía la SPEC. No se añadió código nuevo para este punto.


# ---------------------------------------------------------------------------
# CE-64 — límite de duración: auto-respuesta clara, sin job STT, descarte
# auditado (log + métrica nueva SPEC-060).
# ---------------------------------------------------------------------------
#
#   - tests/test_whatsapp_inbound_worker.py::
#       test_process_job_audio_exceeds_limit_discards_with_auto_reply
#   - tests/test_whatsapp_inbound_worker.py::
#       test_process_job_audio_configurable_limit_via_env_triggers_discard
#   - tests/test_whatsapp_inbound_worker.py::
#       test_process_job_audio_exceeds_limit_increments_discard_metric
#       (NUEVO SPEC-060: confirma
#       `increment_whatsapp_audio_discarded_by_duration()` invocado
#       exactamente una vez en el camino de descarte real)


def test_ce64_discard_metric_and_reply_text_are_wired_in_worker_module():
    """Espejo ejecutable: el worker de ingesta importa la métrica de
    descarte (SPEC-060) y el texto de auto-respuesta (SPEC-055) sigue
    presente en el módulo — confirma por código que ambos mecanismos
    conviven en la misma rama de descarte por duración, sin necesidad de
    reejecutar el test de integración completo aquí."""
    module_path = _BACKEND_ROOT / "app" / "workers" / "whatsapp_inbound_worker.py"
    content = module_path.read_text(encoding="utf-8")
    assert "increment_whatsapp_audio_discarded_by_duration" in content
    assert "_MENSAJE_DESCARTE_POR_DURACION" in content
    assert 'transcripcion_estado = "descartada_por_duracion"' in content


# ---------------------------------------------------------------------------
# CE-65 — no-regresión #1-#4: sink `call` (SPEC-038) intacto (asserts NO
# modificados), WhatsApp de texto (#3) intacto, suites #1-#4 verdes.
# ---------------------------------------------------------------------------
#
#   - tests/test_stt_worker.py::
#       test_process_job_call_sink_with_explicit_destino_no_regression
#   - tests/test_stt_worker.py::
#       test_process_job_legacy_json_without_destino_behaves_as_call_sink
#   - tests/test_whatsapp_inbound_worker.py::
#       test_process_job_text_message_unaffected_by_audio_branch (canal de
#       texto de #3 sin cambios de comportamiento)
#
# VERIFICACIÓN DURA (RNF-62, auditoría SPEC-060): se comparó
# `git diff <commit>..<commit> -- tests/test_stt_worker.py` a través de los 3
# commits que tocaron este archivo desde SPEC-038 (7d4713c, introduce la
# suite original del sink `call`) hasta SPEC-057 (1c8eea3):
#
#   7d4713c -> b4b67ef (SPEC-056): SOLO añade tests nuevos + 1 línea de un
#     parámetro (`chunk_overlap=20`) en un HELPER interno de un test de RAG
#     preexistente ajeno al sink `call`. Ningún assert de un test del sink
#     `call` fue tocado.
#   b4b67ef -> 2252ef7 (fix/triage post-Postgres-real): cambia el FIXTURE
#     inyectado (`postgres_engine` -> `app_engine`) en 2 tests de borrador
#     RAG para eliminar un FALSO POSITIVO de RLS (con `postgres_engine`,
#     rol owner, la recuperación veía chunks de otros tenants acumulados en
#     la BD compartida de test). El contenido de los `assert` no cambió —
#     solo la sesión/rol con la que se ejercía la prueba, haciéndola MÁS
#     estricta, no más laxa.
#   2252ef7 -> 1c8eea3 (SPEC-057): añade tests nuevos del sink `message` y
#     ELIMINA un test que verificaba la AUSENCIA del pipeline IA en el sink
#     `message` (`test_process_job_message_sink_does_not_dispatch_ai_pipeline`)
#     — correcto y esperado, ya que SPEC-057 introdujo exactamente ese
#     pipeline para el sink `message`; esa función NUNCA fue del sink `call`.
#     Ningún test/assert del sink `call` fue tocado en este commit.
#
# CONCLUSIÓN: cero regresión confirmada — ningún assert de un test
# PREEXISTENTE del sink `call` fue modificado en ningún punto de la rama de
# trabajo de este Entregable. (Si en el futuro se detecta un assert alterado
# del sink `call`, es un hallazgo crítico a reportar, NO a corregir
# silenciosamente cambiando el test.)


def test_ce65_call_sink_regression_tests_still_exist_and_are_named_explicitly():
    """Espejo ejecutable: los tests de no-regresión explícita del sink
    `call` (creados por SPEC-056 precisamente para este propósito) siguen
    presentes en el archivo de tests — si alguno se renombra/elimina sin
    querer, este test lo detecta."""
    content = (_BACKEND_ROOT / "tests" / "test_stt_worker.py").read_text(
        encoding="utf-8"
    )
    required_tests = (
        "def test_process_job_call_sink_with_explicit_destino_no_regression",
        "def test_process_job_legacy_json_without_destino_behaves_as_call_sink",
        "def test_process_job_persists_segments_and_updates_call_estado",
    )
    for needle in required_tests:
        assert needle in content, (
            f"REGRESIÓN CE-65: falta '{needle}' en test_stt_worker.py — "
            "la evidencia de no-regresión del sink call debe permanecer "
            "presente y nombrada explícitamente"
        )


def test_ce65_git_history_of_stt_worker_tests_has_no_removed_call_sink_assert():
    """Guardarraíl ejecutable (best-effort, requiere el repo git con
    historial completo — se salta si no está disponible en el entorno de
    CI/sandbox): confirma que el commit de SPEC-057 (`1c8eea3`) no elimina
    ninguna línea `assert` de las funciones de test del sink `call` ya
    existentes en `2252ef7` (verificación programática de la auditoría
    manual documentada arriba).

    LIMITACIONES CONOCIDAS (hallazgo BLACK PANTHER/WOLVERINE, SPEC-060 —
    documentado a propósito, no un descuido): este test es un complemento
    puntual de la auditoría manual, NO un sustituto continuo de ella.
    (1) El rango de commits está FIJO (`2252ef7`..`1c8eea3`, el tramo donde
    SPEC-057 modificó este archivo) — no cubre commits futuros que toquen
    `test_stt_worker.py` después de SPEC-060; cada SPEC nueva que module
    este archivo debe repetir la auditoría manual (o añadir su propio
    guardarraíl de rango). (2) El filtro es TEXTUAL por palabra clave
    (`call_transcript`/`calls.estado`/`call_row` dentro de una línea que
    empiece con `assert`) — un assert reformateado en varias líneas, o que
    use un nombre de variable distinto a esas tres substrings, puede pasar
    sin detectarse (falso negativo). (3) Ante `git` ausente o historia
    truncada, el test hace `pytest.skip(...)` en vez de fallar —no alerta
    por sí solo en un checkout superficial (shallow clone). Tratar como
    una alarma adicional de bajo costo, no como la única garantía de
    RNF-62."""
    try:
        diff = subprocess.run(
            [
                "git",
                "diff",
                "2252ef7",
                "1c8eea3",
                "--",
                "backend/tests/test_stt_worker.py",
            ],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        import pytest

        pytest.skip(
            "git no disponible en este entorno — verificación manual ya documentada"
        )
        return

    if diff.returncode != 0:
        import pytest

        pytest.skip(
            "No se pudo calcular el diff (commits no encontrados en este "
            "checkout, p.ej. historia truncada) — verificación manual ya "
            "documentada en el docstring de este módulo"
        )
        return

    assert diff.stdout, (
        "Se esperaba un diff no vacío entre 2252ef7 y 1c8eea3 sobre "
        "tests/test_stt_worker.py (SPEC-057 sí modificó este archivo) — un "
        "diff vacío indica que los commits no se resolvieron como se "
        "esperaba, revisar el path/commits de este test"
    )

    removed_lines = [
        line
        for line in diff.stdout.splitlines()
        if line.startswith("-") and not line.startswith("---")
    ]
    call_sink_assert_removals = [
        line
        for line in removed_lines
        if "assert" in line
        and (
            "call_transcript" in line.lower()
            or "calls.estado" in line.lower()
            or "call_row" in line.lower()
        )
    ]
    assert call_sink_assert_removals == [], (
        "HALLAZGO CRÍTICO (RNF-62): el commit de SPEC-057 eliminó/modificó "
        f"assert(s) relacionados con el sink `call`: {call_sink_assert_removals}"
    )


# ---------------------------------------------------------------------------
# Observabilidad (RF explícito SPEC-060) — genuinamente nuevo.
# ---------------------------------------------------------------------------
#
#   - tests/test_metrics_endpoint.py::
#       test_metrics_endpoint_exposes_whatsapp_voice_note_metrics_without_tenant_label
#   - tests/test_metrics_endpoint.py::
#       test_increment_whatsapp_media_downloads_counts_by_resultado
#   - tests/test_metrics_endpoint.py::
#       test_increment_whatsapp_audio_discarded_by_duration_counts
#   - tests/test_whatsapp_media_client.py::
#       test_increment_whatsapp_media_downloads_ok_on_success
#   - tests/test_whatsapp_media_client.py::
#       test_increment_whatsapp_media_downloads_error_on_download_failure
#   - tests/test_whatsapp_media_client.py::
#       test_increment_whatsapp_media_downloads_not_called_when_idempotent_skip
#   - tests/test_whatsapp_inbound_worker.py::
#       test_process_job_audio_exceeds_limit_increments_discard_metric
#   - RTF/tasa de error del sink `message` YA REUTILIZA
#     `observe_stt_rtf`/`increment_stt_jobs` de `app/core/metrics.py`
#     (verificado en `app/workers/stt_worker.py::_sink_message`, líneas
#     775-778 al momento de esta auditoría) — CONFIRMADO, no duplicado.


def test_observabilidad_metrics_module_documents_no_tenant_label_decision():
    """Espejo ejecutable: `app/core/metrics.py` documenta explícitamente la
    decisión de NO incluir `tenant_id` como label en las métricas nuevas de
    notas de voz (mismo criterio ya aplicado a `http_requests_total`) — la
    desagregación por tenant vive en logs estructurados, no en Prometheus."""
    content = (_BACKEND_ROOT / "app" / "core" / "metrics.py").read_text(
        encoding="utf-8"
    )
    assert "whatsapp_media_downloads_total" in content
    assert "whatsapp_audio_discarded_by_duration_total" in content
    assert "DECISIÓN DE DISEÑO" in content
    assert "NINGUNA métrica de este módulo lleva" in content


# ---------------------------------------------------------------------------
# Cobertura del código nuevo >= 80% (medida real, no estimada).
# ---------------------------------------------------------------------------
#
# Comando ejecutado (ver informe HAWKEYE para la salida completa):
#   pytest --cov=<módulo> --cov-report=term-missing <archivos de test>
#
# Resultados medidos (todos >= 80%, o justificados si el módulo es
# compartido/preexistente y no exclusivo de este Entregable):
#
#   app/workers/whatsapp_inbound_worker.py ..... 82%
#   app/workers/stt_worker.py ................... 81% (líneas restantes:
#       100% del sink `call`/dispatcher legacy preexistente de SPEC-038,
#       NO del sink `message` nuevo, que está cubierto en su totalidad
#       salvo ramas ya ejercidas)
#   app/integrations/whatsapp/media_client.py ... 90%
#   app/services/telefonia/call_retention_service.py . 91%
#   app/services/message_service.py (compartido, no exclusivo de este
#       Entregable) ................................ 93% (medido junto con
#       los tests de este Entregable + test_message_service_delivery_status.py)
#   app/models/message.py ....................... 100%
#
# NOTA DE HALLAZGO (entorno, no de producto): medir
# `app.services.telefonia.call_retention_service` tomó ~13 minutos en este
# sandbox porque la tabla `tenants` de la BD de test COMPARTIDA Y PERSISTENTE
# acumuló ~5000 filas de sesiones de test anteriores (la fixture
# `two_tenants_with_data` crea tenants con UUID aleatorio y nunca los
# limpia) — `run_call_retention_job` recorre TODOS los tenants activos, uno
# por uno. No es un bug de SPEC-060 ni una regresión de este Entregable; se
# confirmó reproduciendo el mismo comportamiento con `git stash` (código
# previo a esta SPEC). Se reporta como hallazgo de higiene de entorno de
# test, no se corrigió unilateralmente (requeriría un TRUNCATE en una BD
# compartida con otras sesiones potencialmente activas).
