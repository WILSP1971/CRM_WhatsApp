"""
Tests unitarios de la capa de seguridad (SPEC-013) — SIN dependencias
externas (no requieren Postgres/Redis/Docker). Corren en cualquier entorno,
incluido este sandbox de implementación.

Cubren:
  - Hashing de contraseñas: nunca en claro, hash no reversible, verificación
    correcta/incorrecta (RNF-01, criterio de aceptación #1).
  - JWT: emisión con `tenant_id`/`sub`/`rol` embebidos, validación de firma,
    expiración, rechazo de tokens manipulados (criterios #2, #4, #5 parcial).
  - Rate-limit de login: bloqueo tras N intentos fallidos, reseteo tras éxito
    (criterio #7), usando el backend en memoria (Redis no disponible en este
    sandbox; ver docstring de `app/security/rate_limit.py`).
"""

from __future__ import annotations

import time
import uuid

import pytest
from jose import jwt as jose_jwt

from app.security.jwt import (
    InvalidTokenError,
    create_access_token,
    decode_access_token,
)
from app.security.passwords import hash_password, needs_rehash, verify_password
from app.security.rate_limit import LoginRateLimitExceeded, LoginRateLimiter


# ---------------------------------------------------------------------------
# Hashing de contraseñas (RNF-01, criterio de aceptación #1)
# ---------------------------------------------------------------------------


def test_password_hash_is_never_the_plain_value():
    plain = "SuperClaveSegura!2026"
    hashed = hash_password(plain)

    assert hashed != plain
    assert plain not in hashed
    # bcrypt(-sha256) produce hashes con el prefijo estándar de passlib.
    assert hashed.startswith("$bcrypt")


def test_password_hash_has_random_salt_per_call():
    plain = "MismaClave123"
    hash_1 = hash_password(plain)
    hash_2 = hash_password(plain)

    assert hash_1 != hash_2, "Cada hash debe llevar su propio salt aleatorio"
    assert verify_password(plain, hash_1)
    assert verify_password(plain, hash_2)


def test_verify_password_true_for_correct_password():
    plain = "ClaveCorrecta#1"
    hashed = hash_password(plain)
    assert verify_password(plain, hashed) is True


def test_verify_password_false_for_incorrect_password():
    hashed = hash_password("ClaveCorrecta#1")
    assert verify_password("ClaveIncorrecta", hashed) is False


def test_verify_password_false_for_empty_or_corrupt_hash():
    assert verify_password("cualquier", "") is False
    assert verify_password("cualquier", "no-es-un-hash-valido") is False
    assert verify_password("", "algo") is False


def test_hash_password_rejects_empty_password():
    with pytest.raises(ValueError):
        hash_password("")


def test_needs_rehash_false_for_current_hash():
    assert needs_rehash(hash_password("ClaveActual123")) is False


# ---------------------------------------------------------------------------
# JWT (criterios #2, #4, RF de sesión segura con tenant_id embebido)
# ---------------------------------------------------------------------------


def test_create_access_token_embeds_tenant_id_sub_and_rol():
    user_id = uuid.uuid4()
    tenant_id = uuid.uuid4()

    token = create_access_token(user_id=user_id, tenant_id=tenant_id, rol="admin")
    payload = decode_access_token(token)

    assert payload.sub == str(user_id)
    assert payload.tenant_id == str(tenant_id)
    assert payload.rol == "admin"


def test_decode_access_token_rejects_tampered_signature():
    token = create_access_token(
        user_id=uuid.uuid4(), tenant_id=uuid.uuid4(), rol="agente"
    )
    tampered = token[:-4] + ("A" if token[-4] != "A" else "B") + token[-3:]

    with pytest.raises(InvalidTokenError):
        decode_access_token(tampered)


def test_decode_access_token_rejects_token_signed_with_wrong_secret():
    # Token válido en forma, pero firmado con un secreto distinto al configurado.
    bogus_token = jose_jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "tenant_id": str(uuid.uuid4()),
            "rol": "admin",
            "type": "access",
            "iat": time.time(),
            "exp": time.time() + 3600,
        },
        "otro-secreto-completamente-distinto",
        algorithm="HS256",
    )

    with pytest.raises(InvalidTokenError):
        decode_access_token(bogus_token)


def test_decode_access_token_rejects_expired_token():
    token = create_access_token(
        user_id=uuid.uuid4(), tenant_id=uuid.uuid4(), rol="agente", expires_minutes=-1
    )
    with pytest.raises(InvalidTokenError):
        decode_access_token(token)


def test_decode_access_token_rejects_empty_token():
    with pytest.raises(InvalidTokenError):
        decode_access_token("")


def test_decode_access_token_rejects_alg_none_token():
    """
    Evidencia explícita (BLACK WIDOW, opcional): un token firmado con
    `alg=none` (sin firma) o con un algoritmo distinto al configurado
    (`JWT_ALGORITHM`) es rechazado. `python-jose` exige declarar
    `algorithms=[...]` en `decode()` (ver `app/security/jwt.py`), lo que ya
    bloquea por diseño el ataque clásico "alg=none"; este test deja la
    evidencia de que efectivamente se rechaza.
    """
    payload = {
        "sub": str(uuid.uuid4()),
        "tenant_id": str(uuid.uuid4()),
        "rol": "admin",
        "type": "access",
        "iat": time.time(),
        "exp": time.time() + 3600,
    }

    # Token con alg=none (construido a mano: `python-jose` ni siquiera
    # permite *codificar* con "none", por lo que se arma el JWT manualmente
    # tal como lo haría un atacante explotando el ataque clásico "alg=none").
    import base64
    import json

    def _b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    header = _b64url(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    body = _b64url(json.dumps(payload).encode())
    alg_none_token = f"{header}.{body}."  # firma vacía, como exige alg=none

    with pytest.raises(InvalidTokenError):
        decode_access_token(alg_none_token)

    # Token firmado con un algoritmo distinto (HS512) al configurado (HS256):
    # también debe rechazarse aunque la firma en sí sea "válida" para HS512.
    from app.core.config import get_settings

    settings = get_settings()
    other_alg_token = jose_jwt.encode(
        payload, settings.jwt_secret_key, algorithm="HS512"
    )
    with pytest.raises(InvalidTokenError):
        decode_access_token(other_alg_token)


def test_decode_access_token_rejects_wrong_token_type():
    from app.core.config import get_settings

    settings = get_settings()
    non_access_token = jose_jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "tenant_id": str(uuid.uuid4()),
            "rol": "admin",
            "type": "refresh",  # tipo distinto al esperado ("access")
            "iat": time.time(),
            "exp": time.time() + 3600,
        },
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(InvalidTokenError):
        decode_access_token(non_access_token)


# ---------------------------------------------------------------------------
# Rate-limit de login (criterio de aceptación #7)
# ---------------------------------------------------------------------------


def test_rate_limiter_blocks_after_max_attempts():
    limiter = LoginRateLimiter(max_attempts=3, window_seconds=60)
    key = (f"tenant-test-{uuid.uuid4()}", "user@example.com")

    for _ in range(3):
        limiter.check_and_increment(*key)  # 1ro, 2do y 3er intento: permitidos

    with pytest.raises(LoginRateLimitExceeded):
        limiter.check_and_increment(*key)  # 4to intento: bloqueado


def test_rate_limiter_reset_clears_counter():
    limiter = LoginRateLimiter(max_attempts=2, window_seconds=60)
    key = (f"tenant-test-{uuid.uuid4()}", "user2@example.com")

    limiter.check_and_increment(*key)
    limiter.check_and_increment(*key)
    limiter.reset(*key)

    # Tras el reset (login exitoso), el contador vuelve a cero.
    limiter.check_and_increment(*key)  # no debe lanzar
