"""KMS abstraction for WolfPack crypto operations."""

from __future__ import annotations

from wolfpack.config.settings import Settings
from wolfpack.crypto.kms import KMSInterface


def get_kms(settings: Settings) -> KMSInterface:
    """Return a KMS implementation appropriate for the deployment mode.

    In ``dev`` mode this returns ``SoftwareKMS`` (insecure, file-based).

    Args:
        settings: Loaded application settings.

    Returns:
        A ``KMSInterface`` implementation.
    """
    from wolfpack.crypto.software_kms import SoftwareKMS

    if str(settings.deployment_mode) == "dev":
        return SoftwareKMS()
    raise NotImplementedError(
        f"No KMS implementation available for mode {settings.deployment_mode!r}"
    )
