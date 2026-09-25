"""Guardarraíl anti-regresión de `check-externos-backend.sh` §11 (allowlist
por ruta del host del PBX externo, SPEC-035/037, ADR-010).

Contexto (BLACK WIDOW, revisión SPEC-037): la sección 11 del script tuvo dos
bugs acumulados que la volvían un guardarraíl INOPERANTE:

1. Construcción de un único comando `grep` con múltiples `-v -E '<patrón>'`
   encadenados y ejecutados vía `eval`: con esa forma, `grep` interpreta los
   patrones intermedios como RUTAS DE FICHERO (inexistentes), sale con
   código de error, y como el resultado se capturaba con `|| true`, la
   variable de "violaciones fuera de la allowlist" quedaba vacía SIEMPRE —
   nunca se detectaba una fuga real, aunque la hubiera.
2. La lista de patrones de host buscados no incluía la variable real que usa
   el código de SPEC-037 (`PBX_EXTERNAL_HOST` / `settings.pbx_external_host`
   en `app/services/telefonia/pbx_client.py` y `app/core/config.py`), solo
   nombres genéricos/de otros PBX (`ASTERISK_HOST`, `FRESWITCH_HOST`, etc.).

Este test invoca el script bash REAL (subprocess, mismo binario que corre en
CI) contra un árbol de prueba aislado (`tmp_path`, nunca el repo real) para
que una regresión futura en cualquiera de los dos bugs anteriores haga
FALLAR la suite de pytest, no solo un script bash que alguien podría dejar
de ejecutar manualmente.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _REPO_ROOT / "backend" / "check-externos-backend.sh"
_REAL_BACKEND_DIR = _REPO_ROOT / "backend"


def _run_check_externos(backend_dir: Path) -> subprocess.CompletedProcess:
    assert _SCRIPT_PATH.is_file(), f"No se encontró {_SCRIPT_PATH}"
    return subprocess.run(
        ["bash", str(_SCRIPT_PATH), str(backend_dir)],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def sandbox_backend(tmp_path: Path) -> Path:
    """Copia MÍNIMA y aislada del árbol `backend/` real (código de
    aplicación + requirements + docker-compose/.env.example referenciados
    por el script) para poder "ensuciarla" con una violación de prueba sin
    tocar el repo real."""
    sandbox = tmp_path / "backend"
    shutil.copytree(
        _REAL_BACKEND_DIR / "app",
        sandbox / "app",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    requirements = _REAL_BACKEND_DIR / "requirements.txt"
    if requirements.is_file():
        shutil.copy(requirements, sandbox / "requirements.txt")

    # El script también lee `./docker-compose.yml`/`./.env.example` relativos
    # al cwd (no a BACKEND_DIR) en algunas secciones (p.ej. §6) — se copian
    # junto al `tmp_path` para que esas secciones no fallen por archivos
    # ausentes y el test se concentre en la sección 11.
    for fname in ("docker-compose.yml", ".env.example"):
        src = _REPO_ROOT / fname
        if src.is_file():
            shutil.copy(src, tmp_path / fname)

    return sandbox


def test_check_externos_pasa_en_verde_con_arbol_real():
    """Caso base (positivo): el árbol REAL del repo, sin modificar, debe
    pasar la auditoría completa (incluida la sección 11) — si esto falla,
    hay una fuga real, no un problema del test."""
    result = _run_check_externos(_REAL_BACKEND_DIR)

    assert result.returncode == 0, (
        "check-externos-backend.sh debería estar en verde con el árbol "
        f"real del repo.\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )


@pytest.mark.parametrize(
    "leaked_pattern",
    ["PBX_EXTERNAL_HOST", "pbx_external_host"],
)
def test_check_externos_detecta_fuga_de_pbx_external_host_fuera_de_allowlist(
    sandbox_backend: Path, leaked_pattern: str
):
    """Prueba negativa permanente (regresión BLACK WIDOW, SPEC-037): si se
    planta una referencia a `PBX_EXTERNAL_HOST`/`pbx_external_host` en un
    módulo FUERA de la allowlist de transporte del PBX (aquí,
    `app/workers/recording_ingest_worker.py`, que es STT/pipeline de
    ingesta, nunca el cliente de descarga), el script DEBE fallar
    (`returncode != 0`) y reportar el archivo violador en su salida.

    Si este test alguna vez vuelve a pasar en verde con la fuga plantada,
    es la MISMA regresión que motivó esta revisión (guardarraíl inoperante:
    `eval` con múltiples `-v -E` interpretados como rutas de fichero, o
    lista de patrones de host desactualizada) y debe tratarse como un bug de
    seguridad, no un test flaky."""
    target = sandbox_backend / "app" / "workers" / "recording_ingest_worker.py"
    assert target.is_file(), f"Fixture inconsistente: falta {target}"

    with target.open("a", encoding="utf-8") as fh:
        fh.write(
            "\n# TEST-NEGATIVO (pytest, guardarraíl SPEC-037/ADR-010): "
            "referencia fuera de la allowlist del PBX, NO debe pasar CI.\n"
        )
        fh.write(f"leak_test = {leaked_pattern!r}\n")

    result = _run_check_externos(sandbox_backend)

    assert result.returncode != 0, (
        "REGRESIÓN DE SEGURIDAD: check-externos-backend.sh no detectó una "
        f"fuga de '{leaked_pattern}' fuera de la allowlist del PBX "
        "(app/services/telefonia, app/core/config.py, "
        "app/workers/recording_fetch_worker.py). El guardarraíl de la "
        f"sección 11 (ADR-010) es inoperante.\nSTDOUT:\n{result.stdout}\n"
        f"STDERR:\n{result.stderr}"
    )
    assert "recording_ingest_worker.py" in result.stdout, (
        "El script detectó ALGUNA violación pero no reportó el archivo "
        f"esperado en su salida.\nSTDOUT:\n{result.stdout}"
    )


def test_check_externos_acepta_pbx_external_host_dentro_de_la_allowlist(
    sandbox_backend: Path,
):
    """Contraparte del test negativo: el árbol de sandbox SIN modificar (que
    ya contiene `PBX_EXTERNAL_HOST` legítimamente en
    `app/services/telefonia/pbx_client.py` y `app/core/config.py`) debe
    seguir en verde — evita que la corrección del guardarraíl se pase de
    estricta y rompa el uso legítimo documentado en SPEC-037/ADR-010."""
    result = _run_check_externos(sandbox_backend)

    assert result.returncode == 0, (
        "El árbol de sandbox (copia fiel del código real, sin fugas "
        "plantadas) debería pasar la auditoría.\n"
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
