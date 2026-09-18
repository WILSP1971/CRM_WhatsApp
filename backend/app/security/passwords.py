"""
Hashing de contraseñas — SPEC-013 (RNF-01, checkpoint C3).

CHECKPOINT C3 / RNF-01: las contraseñas NUNCA se almacenan ni se registran en
claro. Se usa `passlib` con **bcrypt** (algoritmo fuerte, con salt aleatorio
por contraseña, no reversible) para hashear y verificar.

Nota de alcance: SPEC-013 acepta Argon2 o bcrypt. Este proyecto usa bcrypt
porque ya está declarado en `requirements.txt` (`passlib[bcrypt]`, `bcrypt`)
desde SPEC-011/012 y no añade una dependencia nueva de compilación nativa
(Argon2 requiere `argon2-cffi`); bcrypt con costo >=12 cumple RNF-01.
"""

from passlib.context import CryptContext

# `bcrypt_sha256` evita la limitación de bcrypt de truncar contraseñas a 72
# bytes (pre-hashea con SHA-256 antes de aplicar bcrypt), manteniendo el
# mismo algoritmo de salting/costo de bcrypt puro.
_pwd_context = CryptContext(schemes=["bcrypt_sha256", "bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    """Genera un hash bcrypt (con salt aleatorio) de la contraseña en claro.

    El resultado es un hash de una sola vía (no reversible); nunca se guarda
    ni se transmite la contraseña original.
    """
    if not plain_password:
        raise ValueError("La contraseña no puede ser vacía")
    return _pwd_context.hash(plain_password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Verifica una contraseña en claro contra su hash almacenado.

    Devuelve False ante cualquier hash inválido/corrupto en vez de lanzar
    excepción, para no filtrar información en el flujo de login.
    """
    if not plain_password or not password_hash:
        return False
    try:
        return _pwd_context.verify(plain_password, password_hash)
    except (ValueError, TypeError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """Indica si el hash fue generado con parámetros desactualizados."""
    return _pwd_context.needs_update(password_hash)
