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


def _load_explorer() -> ModuleType:
    spec = importlib.util.spec_from_file_location("explore_runs", EXPLORER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# Sprawdzenie jako własny proces, jak w CI, bo tylko takiemu strażnik kroku może przerwać kod stojący poza modelem (#84):
# argumenty to plik sprawdzenia, limit kroku w sekundach i argumenty sprawdzenia, a {change} zmienia kod przed startem.
DRIVER = """
import importlib.util, queue, sys
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location("explore_runs", sys.argv[1])
explorer = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = explorer
spec.loader.exec_module(explorer)
explorer.STEP_LIMIT_SECONDS = float(sys.argv[2])
{change}
raise SystemExit(explorer.main(sys.argv[3:]))
"""


def _check(limit_s: float, *arguments: str, change: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", DRIVER.format(change=change), str(EXPLORER), str(limit_s), *arguments],
        env={**os.environ, "PYTHONUTF8": "1"},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=100,
        check=False,
    )


def test_centrum_prowadzi_jedno_uruchomienie_naraz_i_nie_zamyka_sie_w_trakcie_w_kazdym_przeplocie() -> None:
    # Limit kroku 1 s przy sprawdzeniu dłuższym niż on: strażnik przerywa tylko krok, który nie wraca, nie całe
    # sprawdzenie. Najdłuższa przerwa między krokami to 20 ms w 4 s sprawdzenia na Macu.
    done = _check(1.0)

    assert done.returncode == 0, done.stdout + done.stderr


def test_kod_zatrzymany_na_blokadzie_spoza_modelu_konczy_sprawdzenie_nazwa_watku_i_kroku_zamiast_limitu_pytest() -> None:
    """Sprawdzenie nie wisi do limitu 120 s pytest, które wyglądało jak flaky test, tylko mówi, co stoi i gdzie (#84)."""

    # _Run.__init__ bierze z uuid identyfikator Uruchomienia pod RunHost._lock; tu czeka na prawdziwej kolejce, do której
    # nikt nie wkłada.
    done = _check(2.0, "--scope", "zamknij-w-trakcie", change="explorer.runs.uuid = SimpleNamespace(uuid4=lambda: queue.Queue().get())")

    lines = done.stdout.splitlines()
    assert done.returncode == 3, done.stdout + done.stderr
    assert lines[-1] == "URUCHOMIENIA: ZAWIESZENIE: krok nie wrócił w 2 s, więc nie ma werdyktu o regułach."
    assert lines[0].startswith(
        "ZAWIESZENIE: wątek modelu „karta Uruchom 1” po kroku „wejście w blokadę RunHost._lock” "
        "nie doszedł do kolejnego kroku w 2 s i stoi w [runs.py:"
    ), lines[0]
    assert " __init__]: kod czeka na coś spoza modelu" in lines[0]


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
