"""Insecure, dev-only software KMS.

**WARNING:** This module stores KEKs as plain files on disk and is intended
for local development only.  Production deployments must use a hardware-backed
KMS (e.g. HashiCorp Vault, AWS KMS, Azure Key Vault).
"""

from __future__ import annotations

import os
import struct
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from wolfpack.crypto.kms import KMSInterface

_KEK_SIZE = 32  # 256 bits
_NONCE_SIZE = 12  # 96 bits, recommended for AES-GCM


def _default_keystore_dir() -> Path:
    return Path(".wolfpack/keks")


class SoftwareKMS(KMSInterface):
    """File-based KEK store using AES-256-GCM.

    KEKs are generated with :func:`os.urandom` and written unencrypted to the
    keystore directory.  This is **insecure** and only suitable for dev mode.
    """

    def __init__(self, keystore_dir: Path | None = None) -> None:
        self._keystore_dir = keystore_dir or _default_keystore_dir()
        self._keystore_dir.mkdir(parents=True, exist_ok=True)

    async def wrap_key(self, dek: bytes, kek_id: str) -> bytes:
        """Wrap *dek* with the KEK identified by *kek_id*."""
        kek = self._load_kek(kek_id)
        nonce = os.urandom(_NONCE_SIZE)
        aesgcm = AESGCM(kek)
        aad = kek_id.encode("utf-8")
        ciphertext = aesgcm.encrypt(nonce, dek, aad)
        kek_id_bytes = kek_id.encode("utf-8")
        # Format: kek_id_len (2 bytes) | kek_id | nonce | ciphertext
        return struct.pack("!H", len(kek_id_bytes)) + kek_id_bytes + nonce + ciphertext

    async def unwrap_key(self, wrapped_dek: bytes, kek_id: str) -> bytes:
        """Unwrap *wrapped_dek* with the KEK identified by *kek_id*."""
        if len(wrapped_dek) < 2:
            raise ValueError("wrapped_dek too short")
        kek_id_len = struct.unpack("!H", wrapped_dek[:2])[0]
        offset = 2 + kek_id_len + _NONCE_SIZE
        if len(wrapped_dek) < offset:
            raise ValueError("wrapped_dek too short for nonce")
        stored_kek_id = wrapped_dek[2 : 2 + kek_id_len].decode("utf-8")
        if stored_kek_id != kek_id:
            raise ValueError(f"KEK ID mismatch: expected {kek_id!r}, got {stored_kek_id!r}")
        nonce = wrapped_dek[2 + kek_id_len : offset]
        ciphertext = wrapped_dek[offset:]
        kek = self._load_kek(kek_id)
        aesgcm = AESGCM(kek)
        aad = kek_id.encode("utf-8")
        return aesgcm.decrypt(nonce, ciphertext, aad)

    async def rotate_kek(self, kek_id: str) -> str:
        """Generate a new KEK and return its identifier.

        The old KEK file is left in place so existing wrapped DEKs can still
        be unwrapped.
        """
        return self._generate_kek()

    def _load_kek(self, kek_id: str) -> bytes:
        kek_path = self._keystore_dir / kek_id
        if not kek_path.exists():
            raise ValueError(f"KEK not found: {kek_id}")
        return kek_path.read_bytes()

    def _generate_kek(self) -> str:
        kek = os.urandom(_KEK_SIZE)
        # Use a random UUID-like suffix instead of key hex to avoid leaking key material
        import uuid

        kek_id = f"kek_{uuid.uuid4().hex}"
        kek_path = self._keystore_dir / kek_id
        kek_path.write_bytes(kek)
        return kek_id
