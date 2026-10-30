"""Jedno Uruchomienie procesu naraz i brak zamknięcia Centrum rozliczeń w trakcie pracy, w każdym przeplocie w zakresie.

Kolejność kroków dwóch kart, Decyzji taty, wątku Uruchomienia i zamknięcia serwera
jest poza zasięgiem testów przez API, więc sprawdza ją wyczerpująco skrypt skilla
``verify-jedno-uruchomienie-naraz`` na prawdziwych ``RunHost`` i ``Shutdown``.
Zakres, znane ustalenia i postępowanie przy porażce opisuje
``.agents/skills/verify-jedno-uruchomienie-naraz/SKILL.md``.
"""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
import threading
from pathlib import Path
from types import ModuleType

import pytest

EXPLORER = (
    Path(__file__).resolve().parents[1]
    / ".agents"
    / "skills"
    / "verify-jedno-uruchomienie-naraz"
    / "scripts"
    / "explore_runs.py"
)
SRC = Path(__file__).resolve().parents[1] / "src"

# Prawdziwe Event, nie to z modelu: kod pod sprawdzeniem czeka na nie w RunHost.start i nigdy nie oddaje sterowania.
BLOCKED_START = """
import runpy, sys, threading
sys.path.insert(0, sys.argv[1])
from rozliczenia.centrum import runs
def blocked(self, *_):
    threading.Event().wait()
runs._Run.__init__ = blocked
sys.argv = sys.argv[2:]
runpy.run_path(sys.argv[0], run_name="__main__")
"""


def _load_explorer() -> ModuleType:
    spec = importlib.util.spec_from_file_location("explore_runs", EXPLORER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _check(*arguments: str) -> subprocess.CompletedProcess[str]:
    """Sprawdzenie we własnym procesie: limit kroku kończy proces, więc w procesie pytest zabrałby mu raport."""

    return subprocess.run(
        [sys.executable, *arguments],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        timeout=90,
        check=False,
    )


def test_centrum_prowadzi_jedno_uruchomienie_naraz_i_nie_zamyka_sie_w_trakcie_w_kazdym_przeplocie() -> None:
    # Najdłuższa przerwa między krokami to 0,05 s (Mac, 2026-10-30), a całe sprawdzenie trwa ponad 2 s, więc limit kroku
    # 2 s nie zatrzymuje zdrowego sprawdzenia, a zatrzymałby je, gdyby nie widział kroków.
    checked = _check(str(EXPLORER), "--step-limit-s", "2")

    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert checked.stdout.rstrip().splitlines()[-1] == "URUCHOMIENIA OK"


def test_blokada_spoza_modelu_konczy_sprawdzenie_czytelnym_bledem_przed_limitem_pytest() -> None:
    """Kod pod sprawdzeniem stojący na blokadzie, której model nie prowadzi, nie wygląda w CI jak flaky test (#27)."""

    checked = _check("-c", BLOCKED_START, str(SRC), str(EXPLORER), "--scope", "zamknij-w-trakcie", "--step-limit-s", "2")

    lines = checked.stdout.rstrip().splitlines()
    assert checked.returncode == 2, checked.stdout + checked.stderr
    assert lines[-1] == "URUCHOMIENIA: BLOKADA SPOZA MODELU: karta Uruchom 1, krok nie wrócił w 2 s."
    assert re.fullmatch(
        r"  karta Uruchom 1: krok nie wrócił w 2 s po „wejście w blokadę RunHost\._lock”; kod stoi w \[runs\.py:\d+ start\] "
        r"i czeka na coś, czego model nie prowadzi \(prawdziwa blokada, kolejka, sen\)",
        lines[1],
    ), lines[1]
    assert "    1. karta Uruchom 1: żądanie POST /api/runs dociera do serwera [model]" in lines


def test_sprawdzenie_przeplotow_prowadzi_watki_modelu_bez_watkow_systemu(monkeypatch: pytest.MonkeyPatch) -> None:
    """Czas sprawdzenia nie zależy od tego, jak zajęte są procesory runnera (#565).

    Wątek systemu na każdy wątek modelu oddawał sterowanie przez jądro przy każdym kroku, a na runnerze CI zajętym
    innymi workerami xdist sprawdzenie dochodziło do limitu 120 s pytest.
    """

    explorer = _load_explorer()
    started: list[str] = []
    start = threading.Thread.start
    checking = threading.current_thread()

    def counted(thread: threading.Thread) -> None:
        # Wątki tła zostawione przez wcześniejsze testy w tym workerze startują swoje wątki same; liczy się tylko to,
        # co uruchomiło sprawdzenie.
        if threading.current_thread() is checking:
            started.append(thread.name)
        start(thread)

    monkeypatch.setattr(threading.Thread, "start", counted)

    report = explorer.explore(explorer.SCOPES["zamknij-w-trakcie"])

    assert report.runs_ended and report.clean_closes
    assert started == []
