"""Unit tests for PII pseudonymization (no DB required)."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wolfpack.schemas.persistence import PersistencePool
from wolfpack.schemas.pii import BreakGlassError, depseudonymize, pseudonymize


@pytest.fixture()
def mock_pool() -> Any:
    pool = MagicMock(spec=PersistencePool)
    pool.acquire = AsyncMock()
    pool.release = AsyncMock()
    return pool


class TestPseudonymize:
    async def test_same_input_same_token(self, mock_pool: Any) -> None:
        salt = b"x" * 32
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value = mock_conn

        with patch.object(secrets, "token_bytes", return_value=salt):
            # First call: no salt exists, create it
            mock_conn.fetchrow.return_value = None
            mock_conn.execute.return_value = None
            token1 = await pseudonymize(mock_pool, "case-1", "alice@example.com", "user")

            # Second call: salt exists
            mock_conn.fetchrow.return_value = {"salt": salt}
            token2 = await pseudonymize(mock_pool, "case-1", "alice@example.com", "user")

        assert token1 == token2

    async def test_different_salt_different_token(self, mock_pool: Any) -> None:
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value = mock_conn
        mock_conn.execute.return_value = None

        with patch.object(
            secrets,
            # token_bytes is called for the 32-byte salt AND the 12-byte
            # AES-GCM nonce on each fresh case, so supply both per case.
            "token_bytes",
            side_effect=[b"a" * 32, b"\x00" * 12, b"b" * 32, b"\x00" * 12],
        ):
            # First case salt
            mock_conn.fetchrow.side_effect = [
                None,  # no salt for case-1
                {"salt": b"a" * 32},
                None,  # no salt for case-2
                {"salt": b"b" * 32},
            ]

            token1 = await pseudonymize(mock_pool, "case-1", "alice@example.com", "user")
            token2 = await pseudonymize(mock_pool, "case-2", "bob@example.com", "user")

        assert token1 != token2

    async def test_token_format(self, mock_pool: Any) -> None:
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value = mock_conn
        mock_conn.fetchrow.return_value = None
        mock_conn.execute.return_value = None

        token = await pseudonymize(mock_pool, "case-1", "bob@example.com", "email")

        prefix, suffix = token.split("_", 1)
        assert prefix == "email"
        assert len(suffix) == 12
        assert all(c in "0123456789abcdef" for c in suffix)

    async def test_determinism(self, mock_pool: Any) -> None:
        salt = b"s" * 32
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value = mock_conn
        mock_conn.execute.return_value = None

        with patch.object(secrets, "token_bytes", return_value=salt):
            # No salt first call, then salt exists
            mock_conn.fetchrow.side_effect = [None, {"salt": salt}, {"salt": salt}]

            token1 = await pseudonymize(mock_pool, "case-1", "val", "user")
            token2 = await pseudonymize(mock_pool, "case-1", "val", "user")

        expected = hmac.new(salt, b"user:val", hashlib.sha256).hexdigest()[:12]
        assert token1 == f"user_{expected}"
        assert token1 == token2


class TestDepseudonymize:
    async def test_success(self, mock_pool: Any) -> None:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        salt = b"s" * 32
        case_id = "case-1"
        original = "alice@example.com"
        # Reproduce the on-disk encrypted form: nonce | AES-GCM(ciphertext|tag),
        # keyed by HMAC(salt, "pii-encryption-v1"), with case_id as AAD.
        enc_key = hmac.new(salt, b"pii-encryption-v1", hashlib.sha256).digest()
        nonce = b"\x01" * 12
        ciphertext = AESGCM(enc_key).encrypt(nonce, original.encode(), case_id.encode())
        stored_value = nonce + ciphertext

        mock_conn = AsyncMock()
        mock_pool.acquire.return_value = mock_conn
        mock_conn.execute.return_value = None
        # 1st fetchrow: the mapping row; 2nd fetchrow: the per-case salt.
        mock_conn.fetchrow.side_effect = [
            {"original_value": stored_value},
            {"salt": salt},
        ]

        result = await depseudonymize(mock_pool, case_id, "user_a42f1e0c1234", "analyst-1")

        assert result == original
        # Audit was written
        assert mock_conn.execute.await_count >= 1

    async def test_not_found(self, mock_pool: Any) -> None:
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value = mock_conn
        mock_conn.execute.return_value = None
        mock_conn.fetchrow.return_value = None

        result = await depseudonymize(mock_pool, "case-1", "user_deadbeef", "analyst-1")

        assert result is None

    async def test_breakglass_audit_failure(self, mock_pool: Any) -> None:
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value = mock_conn
        mock_conn.execute.side_effect = RuntimeError("DB down")

        with pytest.raises(BreakGlassError):
            await depseudonymize(mock_pool, "case-1", "user_a42f1e", "analyst-1")
