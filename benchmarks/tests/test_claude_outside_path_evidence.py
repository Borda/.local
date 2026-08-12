"""Focused regression tests for Claude external-path telemetry."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest


def test_external_path_evidence_ignores_a_launcher_shebang_in_written_content(script_run_agentic: Any) -> None:
    """A source-file payload must not masquerade as an external path access.

    Regression: successful writes containing a Python shebang quarantined Patch
    cells as if the agent had accessed the shebang launcher.
    """
    events = [
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "write",
                        "name": "Write",
                        "input": {
                            "file_path": "/disposable/repository/test_fix.py",
                            "content": "#!/usr/bin/env python\nprint('ok')\n",
                        },
                    }
                ]
            },
        },
        {
            "type": "user",
            "message": {"content": [{"type": "tool_result", "tool_use_id": "write", "is_error": False, "content": ""}]},
        },
    ]

    attempted, successful = script_run_agentic._outside_workspace_path_evidence(events, Path("/disposable/repository"))

    assert attempted == []
    assert successful == []


@pytest.mark.parametrize(
    ("tool_name", "tool_input"),
    [
        pytest.param("Read", {"file_path": "/host/source.py"}, id="external_read"),
        pytest.param("Write", {"file_path": "/host/source.py", "content": "pass\n"}, id="external_write"),
        pytest.param("Bash", {"command": "cat /host/source.py"}, id="external_command"),
    ],
)
def test_external_path_evidence_keeps_successful_host_access_quarantined(
    script_run_agentic: Any, tool_name: str, tool_input: dict[str, str]
) -> None:
    """Executable tool path fields and commands still record successful host access."""
    events = [
        {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "id": "external", "name": tool_name, "input": tool_input}]},
        },
        {
            "type": "user",
            "message": {
                "content": [{"type": "tool_result", "tool_use_id": "external", "is_error": False, "content": "ok"}]
            },
        },
    ]

    attempted, successful = script_run_agentic._outside_workspace_path_evidence(events, Path("/disposable/repository"))

    assert attempted == ["/host/source.py"]
    assert successful == ["/host/source.py"]
