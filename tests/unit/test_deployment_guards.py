"""Tests for deployment mode and URL guard helpers."""

import pytest

from wolfpack.config.deployment import DeploymentMode, is_loopback_or_private


@pytest.mark.parametrize(
    "url,expected",
    [
        # Loopback
        ("http://localhost:11434", True),
        ("http://localhost", True),
        ("http://127.0.0.1:11434", True),
        ("http://127.0.0.1", True),
        ("http://[::1]:11434", True),
        ("http://[::1]", True),
        # RFC-1918 private ranges
        ("http://10.0.0.1:11434", True),
        ("http://10.255.255.255:11434", True),
        ("http://172.16.0.1:11434", True),
        ("http://172.31.255.255:11434", True),
        ("http://192.168.0.1", True),
        ("http://192.168.1.100:11434", True),
        # Public internet hosts
        ("https://api.ollama.com", False),
        ("https://ollama.com", False),
        ("http://8.8.8.8:11434", False),
        ("http://1.1.1.1", False),
        # Non-IP public hostname
        ("http://my-remote-server.example.com", False),
        # Edge cases
        ("http://", False),
        ("localhost:11434", False),   # urlparse treats schemeless as path
        ("", False),
    ],
)
def test_is_loopback_or_private(url: str, expected: bool) -> None:
    assert is_loopback_or_private(url) is expected


def test_deployment_mode_string_values() -> None:
    assert DeploymentMode.DEV.value == "dev"
    assert DeploymentMode.ON_PREM_CONNECTED.value == "on_prem_connected"
    assert DeploymentMode.ON_PREM_AIRGAPPED.value == "on_prem_airgapped"


def test_deployment_mode_is_str_enum() -> None:
    assert isinstance(DeploymentMode.DEV, str)
    assert DeploymentMode("dev") is DeploymentMode.DEV
