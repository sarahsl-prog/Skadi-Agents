"""KMS interface definition."""

from __future__ import annotations

from abc import ABC, abstractmethod


class KMSInterface(ABC):
    """Abstract interface for Key Management Systems."""

    @abstractmethod
    async def wrap_key(self, dek: bytes, kek_id: str) -> bytes:
        """Wrap a data encryption key with the specified KEK.

        Args:
            dek: Raw 256-bit data encryption key.
            kek_id: Identifier of the key-encryption key to use.

        Returns:
            Wrapped (encrypted) DEK bytes.
        """

    @abstractmethod
    async def unwrap_key(self, wrapped_dek: bytes, kek_id: str) -> bytes:
        """Unwrap a data encryption key with the specified KEK.

        Args:
            wrapped_dek: Wrapped DEK bytes from ``wrap_key``.
            kek_id: Identifier of the key-encryption key to use.

        Returns:
            Raw DEK bytes.

        Raises:
            ValueError: If the wrapped DEK is malformed or the KEK is unknown.
        """

    @abstractmethod
    async def rotate_kek(self, kek_id: str) -> str:
        """Rotate a KEK and return the new KEK identifier.

        Args:
            kek_id: Current KEK identifier.

        Returns:
            New KEK identifier.
        """
