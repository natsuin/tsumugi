"""Scenario container: optional UTF-8 BOM + one Base64 line + trailing
newline(s), wrapping AES-256-CBC/PKCS7 ciphertext of the UTF-8 script.

Key and IV come from PBKDF2-HMAC-SHA1 (.NET Rfc2898DeriveBytes) over a
password and salt. The defaults are the widely-copied .NET sample-code
values; a title using other values is refused by decode(), never guessed.

decode() re-encodes before returning and refuses input that does not
reproduce byte-for-byte, so Gate A exercises the real writer. CBC with a
fixed derived IV is deterministic, which is what makes that possible.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
from dataclasses import dataclass

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

_BOM = b"\xef\xbb\xbf"
_SALT = "saltは必ず8バイト以上".encode("utf-8")
_PASSWORDS: tuple[bytes, ...] = (b"pass",)
_ITERATIONS = 1000


@dataclass(frozen=True)
class Framing:
    """Everything outside the plaintext that encode() must reproduce."""

    password: bytes
    prefix: bytes  # UTF-8 BOM or b""
    suffix: bytes  # newline bytes after the Base64 line


def _key_iv(password: bytes) -> tuple[bytes, bytes]:
    kiv = hashlib.pbkdf2_hmac("sha1", password, _SALT, _ITERATIONS, 48)
    return kiv[:32], kiv[32:]


def _decrypt(ciphertext: bytes, password: bytes) -> bytes | None:
    if not ciphertext or len(ciphertext) % 16:
        return None
    key, iv = _key_iv(password)
    dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    padded = dec.update(ciphertext) + dec.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    try:
        return unpadder.update(padded) + unpadder.finalize()
    except ValueError:
        return None  # bad padding: wrong password or not this format


def _encrypt(plaintext: bytes, password: bytes) -> bytes:
    key, iv = _key_iv(password)
    padder = padding.PKCS7(128).padder()
    padded = padder.update(plaintext) + padder.finalize()
    enc = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    return enc.update(padded) + enc.finalize()


def decode(raw: bytes) -> tuple[str, Framing] | None:
    """(script text, framing), or None if raw is not a container this
    module can reproduce byte-identically."""
    prefix = _BOM if raw.startswith(_BOM) else b""
    body = raw[len(prefix) :]
    line = body.rstrip(b"\r\n")
    suffix = body[len(line) :]
    try:
        ciphertext = base64.b64decode(line, validate=True)
    except (binascii.Error, ValueError):
        return None
    for password in _PASSWORDS:
        plaintext = _decrypt(ciphertext, password)
        if plaintext is None:
            continue
        try:
            text = plaintext.decode("utf-8")
        except UnicodeDecodeError:
            continue
        framing = Framing(password=password, prefix=prefix, suffix=suffix)
        if encode(text, framing) != raw:
            return None
        return text, framing
    return None


def encode(text: str, framing: Framing) -> bytes:
    ciphertext = _encrypt(text.encode("utf-8"), framing.password)
    return framing.prefix + base64.b64encode(ciphertext) + framing.suffix
