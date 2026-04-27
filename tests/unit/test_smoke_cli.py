"""Unit tests for the smoke CLI entry point."""

import subprocess
import sys


def test_smoke_cli_imports() -> None:
    """The smoke CLI module must be importable without side effects."""
    from wolfpack.smoke.hello_pack import app

    assert app is not None


def test_smoke_cli_help() -> None:
    """The smoke CLI must expose a --help flag."""
    result = subprocess.run(
        [sys.executable, "-m", "wolfpack.smoke.hello_pack", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "smoke" in result.stdout.lower()
