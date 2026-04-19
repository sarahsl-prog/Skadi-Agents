"""Deployment mode enum and URL guard helpers."""

import ipaddress
from enum import StrEnum
from urllib.parse import urlparse


class DeploymentMode(StrEnum):
    DEV = "dev"
    ON_PREM_CONNECTED = "on_prem_connected"
    ON_PREM_AIRGAPPED = "on_prem_airgapped"


def is_loopback_or_private(url: str) -> bool:
    """Return True if the URL's host is a loopback or RFC-1918 private address.

    Non-IP hostnames (other than 'localhost') are conservatively treated as public.
    This is called at config load time to enforce airgapped deployment restrictions.
    """
    host = urlparse(url).hostname or ""
    if not host:
        return False
    if host == "localhost":
        return True
    try:
        addr = ipaddress.ip_address(host)
        return addr.is_loopback or addr.is_private
    except ValueError:
        # Non-IP hostname that isn't 'localhost' — treat as public
        return False
