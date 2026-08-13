"""Focused regression tests for Claude external-path telemetry."""

from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath
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


def _read_events(file_path: str) -> list[dict[str, Any]]:
    """Return one successful external Read transcript naming *file_path*."""
    return [
        {
            "type": "assistant",
            "message": {
                "content": [{"type": "tool_use", "id": "read", "name": "Read", "input": {"file_path": file_path}}]
            },
        },
        {
            "type": "user",
            "message": {
                "content": [{"type": "tool_result", "tool_use_id": "read", "is_error": False, "content": "ok"}]
            },
        },
    ]


def test_external_path_evidence_records_the_observed_path_under_a_windows_workspace(
    script_run_agentic: Any,
) -> None:
    """Recorded evidence is the path the agent named, never one re-rooted on the scoring host.

    Regression: the observed path was pushed through ``Path.resolve()``. On Windows that
    gives a leading-slash path the current drive letter, so ``/host/source.py`` was
    reported as ``D:\\host\\source.py`` — evidence about a file that was never touched.
    """
    attempted, successful = script_run_agentic._outside_workspace_path_evidence(
        _read_events("/host/source.py"), PureWindowsPath(r"D:\agent\disposable")
    )

    assert attempted == ["/host/source.py"]
    assert successful == ["/host/source.py"]


def test_workspace_members_are_not_external_evidence(script_run_agentic: Any) -> None:
    """A checkout is never its own leak."""
    attempted, successful = script_run_agentic._outside_workspace_path_evidence(
        _read_events("/disposable/repository/src/app.py"), PurePosixPath("/disposable/repository")
    )

    assert attempted == []
    assert successful == []


@pytest.mark.parametrize(
    ("workspace_root", "expected"),
    [
        pytest.param(PureWindowsPath(r"D:\agent\repo"), ("D:/agent/repo",), id="windows_backslash_root"),
        pytest.param(PurePosixPath("/agent/repo"), ("/agent/repo",), id="posix_root"),
    ],
)
def test_containment_roots_are_separator_free(script_run_agentic: Any, workspace_root: Any, expected: tuple) -> None:
    """Root forms carry no host separator, so containment never depends on the scoring OS."""
    roots = script_run_agentic._workspace_containment_roots(workspace_root)

    assert tuple(str(root) for root in roots) == expected


@pytest.mark.parametrize(
    ("observed", "inside"),
    [
        pytest.param("D:/agent/repo/src/app.py", True, id="member"),
        pytest.param("D:/agent/repo", True, id="root_itself"),
        pytest.param("D:/agent/repo-backup/src/app.py", False, id="prefix_sibling"),
        pytest.param("/host/source.py", False, id="foreign_root"),
    ],
)
def test_windows_rooted_containment_is_decided_lexically(script_run_agentic: Any, observed: str, inside: bool) -> None:
    """A drive-qualified checkout classifies observed paths without touching this filesystem."""
    roots = script_run_agentic._workspace_containment_roots(PureWindowsPath(r"D:\agent\repo"))

    assert script_run_agentic._is_inside_workspace(PurePosixPath(observed), roots) is inside


def test_sibling_directory_sharing_a_workspace_prefix_stays_external(script_run_agentic: Any) -> None:
    """A neighbour whose name merely starts with the checkout's is outside it."""
    attempted, _ = script_run_agentic._outside_workspace_path_evidence(
        _read_events("/disposable/repository-backup/src/app.py"), PurePosixPath("/disposable/repository")
    )

    assert attempted == ["/disposable/repository-backup/src/app.py"]
