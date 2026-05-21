"""Unit tests for the dev-only SoftwareKMS (wrap/unwrap/rotate)."""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag

from wolfpack.crypto.software_kms import SoftwareKMS

_DEK = b"k" * 32


async def test_wrap_unwrap_roundtrip(tmp_path: Path) -> None:
    kms = SoftwareKMS(keystore_dir=tmp_path)
    kek_id = kms._generate_kek()
    wrapped = await kms.wrap_key(_DEK, kek_id)
    assert wrapped != _DEK
    assert await kms.unwrap_key(wrapped, kek_id) == _DEK


async def test_unwrap_with_mismatched_kek_id_rejected(tmp_path: Path) -> None:
    kms = SoftwareKMS(keystore_dir=tmp_path)
    kek_id = kms._generate_kek()
    other_id = kms._generate_kek()
    wrapped = await kms.wrap_key(_DEK, kek_id)
    # The kek_id is embedded in the blob; unwrapping under a different id fails.
    with pytest.raises(ValueError, match="KEK ID mismatch"):
        await kms.unwrap_key(wrapped, other_id)


async def test_tampered_ciphertext_fails_auth(tmp_path: Path) -> None:
    kms = SoftwareKMS(keystore_dir=tmp_path)
    kek_id = kms._generate_kek()
    wrapped = bytearray(await kms.wrap_key(_DEK, kek_id))
    wrapped[-1] ^= 0xFF  # flip a tag byte -> GCM auth must fail
    with pytest.raises(InvalidTag):
        await kms.unwrap_key(bytes(wrapped), kek_id)


async def test_rotate_generates_distinct_kek(tmp_path: Path) -> None:
    kms = SoftwareKMS(keystore_dir=tmp_path)
    kek_id = kms._generate_kek()
    new_id = await kms.rotate_kek(kek_id)
    assert new_id != kek_id
    # Old KEK is retained so existing wrapped DEKs remain unwrappable.
    assert (tmp_path / kek_id).exists()
    assert (tmp_path / new_id).exists()


async def test_unwrap_short_input_rejected(tmp_path: Path) -> None:
    kms = SoftwareKMS(keystore_dir=tmp_path)
    with pytest.raises(ValueError):
        await kms.unwrap_key(b"\x00", "kek_x")


async def test_wrap_with_unknown_kek_raises(tmp_path: Path) -> None:
    kms = SoftwareKMS(keystore_dir=tmp_path)
    with pytest.raises(ValueError, match="KEK not found"):
        await kms.wrap_key(_DEK, "does-not-exist")
