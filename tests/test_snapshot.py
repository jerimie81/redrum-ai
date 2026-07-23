import pytest
import subprocess
import sys

def test_cli_help_snapshot():
    res = subprocess.run(
        [sys.executable, "/home/redrum/.gemini/projects/redrum-ai/ai_partner.py", "--help"],
        capture_output=True,
        text=True
    )
    assert res.returncode == 0
    assert "usage:" in res.stdout
