"""Hook ``tools/hooks/praca_w_tle.py``: agent nie kończy tury, dopóki w tle jego sesji biegnie Bash albo Monitor.

Wejścia mają kształt wejścia hooka ``Stop`` z Claude Code 2.1.312: pierwsze to zapis z próby ``claude -p``
z poleceniem w tle (H6, 30.10.2026). Każdy test uruchamia hook tak jak Claude Code: JSON na stdin, a odmowa to
``{"decision": "block", "reason": …}`` na stdout z kodem 0.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "tools" / "hooks" / "praca_w_tle.py"
SETTINGS = ROOT / ".claude" / "settings.json"

SHELL = {"id": "bqowx4t8g", "type": "shell", "status": "running", "description": "Wait 45s then write KONIEC to file", "command": "sleep 45; echo KONIEC > wynik.txt"}
MONITOR = {"id": "m1", "type": "monitor", "status": "running", "description": "CI logs", "server": "x", "tool": "y"}
SUBAGENT = {"id": "a1", "type": "subagent", "status": "running", "description": "przegląd", "agent_type": "general-purpose"}


def _stop(tasks: list[dict[str, str]], **fields: object) -> str:
    event = {"session_id": "s", "transcript_path": "/t.jsonl", "cwd": "/", "hook_event_name": "Stop", "stop_hook_active": False}
    return json.dumps({**event, "last_assistant_message": "Uruchomione w tle.", "background_tasks": tasks, "session_crons": [], **fields})


def _hook(stdin: str | bytes) -> subprocess.CompletedProcess[bytes]:
    data = stdin.encode("utf-8") if isinstance(stdin, str) else stdin
    return subprocess.run([sys.executable, str(HOOK)], input=data, capture_output=True, check=False)


def _reason(hooked: subprocess.CompletedProcess[bytes]) -> str:
    assert (hooked.returncode, hooked.stderr) == (0, b"")
    decision = json.loads(hooked.stdout)
    assert decision["decision"] == "block"
    return str(decision["reason"])


@pytest.mark.parametrize(
    ("tasks", "named"),
    [
        ([SHELL], ["shell bqowx4t8g „sleep 45; echo KONIEC > wynik.txt”"]),
        ([MONITOR], ["monitor m1 „CI logs”"]),
        ([{**SHELL, "status": "pending"}], ["shell bqowx4t8g"]),
        ([{**SHELL, "status": None}], ["shell bqowx4t8g"]),
        ([SUBAGENT, {**SHELL, "status": "completed"}, MONITOR], ["monitor m1"]),
    ],
    ids=["bash-w-tle", "monitor", "status-nieznany-to-zywy", "bez-statusu-to-zywy", "tylko-zywe-bash-i-monitor"],
)
def test_zywe_zadanie_basha_albo_monitor_w_tle_zatrzymuje_koniec_tury_z_droga_do_wyniku(tasks: list[dict[str, str]], named: list[str]) -> None:
    reason = _reason(_hook(_stop(tasks)))

    assert [name in reason for name in named] == [True] * len(named)
    assert "subagent" not in reason
    assert ["t3_background_wait" in reason, "TaskStop" in reason, "run_in_background" in reason] == [True, True, True]


def test_odmowa_trwa_takze_przy_stop_hook_active_dopoki_zadanie_zyje() -> None:
    reason = _reason(_hook(_stop([SHELL], stop_hook_active=True)))

    assert "shell bqowx4t8g" in reason


@pytest.mark.parametrize(
    "tasks",
    [
        [],
        [{**SHELL, "status": "completed"}, {**MONITOR, "status": "killed"}, {**SHELL, "id": "b2", "status": "failed"}, {**SHELL, "id": "b3", "status": "stopped"}],
        [SUBAGENT, {"id": "w1", "type": "workflow", "status": "running", "name": "x"}, {"id": "c1", "type": "cloud session", "status": "running"}],
        [{"id": "t1", "type": "MCP task", "status": "running", "server": "x", "tool": "y"}, "shell", None],
    ],
    ids=["pusta-lista", "zadania-skonczone", "podagent-workflow-sesja-w-chmurze", "zadanie-mcp-i-wpisy-nie-obiekty"],
)
def test_bez_zywego_basha_ani_monitora_tura_konczy_sie_bez_slowa(tasks: list[object]) -> None:
    hooked = _hook(_stop(tasks))  # type: ignore[arg-type]

    assert (hooked.returncode, hooked.stdout, hooked.stderr) == (0, b"", b"")


@pytest.mark.parametrize(
    "stdin",
    [
        "",
        "nie json",
        "[]",
        "null",
        "5",
        json.dumps({"hook_event_name": "Stop", "stop_hook_active": False}),
        json.dumps({"hook_event_name": "Stop", "background_tasks": {"0": SHELL}}),
        "[" * 100000,
        b"\xff\xfe{",
    ],
    ids=["pusto", "nie-json", "lista", "null", "liczba", "bez-background-tasks", "background-tasks-nie-lista", "gleboki-json", "nie-utf8"],
)
def test_nieczytelne_wejscie_hooka_przechodzi(stdin: str | bytes) -> None:
    hooked = _hook(stdin)

    assert (hooked.returncode, hooked.stdout) == (0, b"")


def _configured_hooks() -> list[dict[str, object]]:
    entries = json.loads(SETTINGS.read_text(encoding="utf-8"))["hooks"]["Stop"]
    return [hook for entry in entries for hook in entry["hooks"]]


def test_hook_ocenia_dluga_liste_zadan_przed_limitem_z_ustawien() -> None:
    # Claude Code po limicie kończy hook bez decyzji, więc tura kończy się mimo pracy w tle.
    (timeout,) = [float(str(hook["timeout"])) for hook in _configured_hooks()]
    tasks = [{**SHELL, "id": f"b{n}", "status": "completed"} for n in range(100000)] + [SHELL]

    hooked = subprocess.run([sys.executable, str(HOOK)], input=_stop(tasks).encode("utf-8"), capture_output=True, timeout=timeout, check=False)

    assert 0 < timeout <= 10
    assert "shell bqowx4t8g" in _reason(hooked)


def _configured(project: Path) -> list[subprocess.CompletedProcess[bytes]]:
    return [
        subprocess.run(
            str(hook["command"]),
            shell=True,
            input=_stop([SHELL]).encode("utf-8"),
            env={**os.environ, "CLAUDE_PROJECT_DIR": str(project)},
            capture_output=True,
            check=False,
        )
        for hook in _configured_hooks()
    ]


@pytest.mark.skipif(sys.platform == "win32", reason="python3 na Windows bywa aliasem Microsoft Store")
def test_ustawienia_projektu_wpinaja_hook_w_stop_a_nie_w_subagent_stop() -> None:
    hooked = _configured(ROOT)

    assert [json.loads(run.stdout)["decision"] for run in hooked] == ["block"]
    assert "SubagentStop" not in json.loads(SETTINGS.read_text(encoding="utf-8"))["hooks"]


@pytest.mark.skipif(sys.platform == "win32", reason="python3 na Windows bywa aliasem Microsoft Store")
def test_checkout_bez_skryptu_hooka_nie_blokuje_konca_tury(tmp_path: Path) -> None:
    # Sesja trzyma ustawienia ze startu, a checkout sprzed hooka nie ma skryptu; python3 bez pliku kończy się kodem 2.
    hooked = _configured(tmp_path)

    assert [(run.returncode, run.stdout, run.stderr) for run in hooked] == [(0, b"", b"")]
