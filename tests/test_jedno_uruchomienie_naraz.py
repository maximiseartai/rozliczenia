"""Jedno Uruchomienie procesu naraz i brak zamknięcia Centrum rozliczeń w trakcie pracy, w każdym przeplocie w zakresie.

Kolejność kroków dwóch kart, Decyzji taty, wątku Uruchomienia i zamknięcia serwera
jest poza zasięgiem testów przez API, więc sprawdza ją wyczerpująco skrypt skilla
``verify-jedno-uruchomienie-naraz`` na prawdziwych ``RunHost`` i ``Shutdown``.
Zakres, znane ustalenia i postępowanie przy porażce opisuje
``.agents/skills/verify-jedno-uruchomienie-naraz/SKILL.md``.
"""

from __future__ import annotations

import importlib.util
import sys
import threading
from pathlib import Path
from types import ModuleType

import pytest

from tests.fixtures.potomne import wait_for

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


def test_centrum_prowadzi_jedno_uruchomienie_naraz_i_nie_zamyka_sie_w_trakcie_w_kazdym_przeplocie() -> None:
    explorer = _load_explorer()

    outcome = explorer.summarize([explorer.explore(scope) for scope in explorer.SCOPES.values()])

    assert outcome.exit_code == 0, "\n".join(outcome.lines)


def test_sprawdzenie_przeplotow_prowadzi_watki_modelu_bez_watkow_systemu(monkeypatch: pytest.MonkeyPatch) -> None:
    """Czas sprawdzenia nie zależy od tego, jak zajęte są procesory runnera (#565).

    Wątek systemu na każdy wątek modelu oddawał sterowanie przez jądro przy każdym kroku, a na runnerze CI zajętym
    innymi workerami xdist sprawdzenie dochodziło do limitu 120 s pytest.
    """

    explorer = _load_explorer()
    started: list[str] = []
    start = threading.Thread.start
    checking = {threading.current_thread()}

    def counted(thread: threading.Thread) -> None:
        # Wątki tła zostawione przez wcześniejsze testy w tym workerze startują swoje wątki same; liczy się tylko to,
        # co uruchomiło sprawdzenie, także z wątku, który samo uruchomiło.
        if threading.current_thread() in checking:
            started.append(thread.name)
            checking.add(thread)
        start(thread)

    monkeypatch.setattr(threading.Thread, "start", counted)

    report = explorer.explore(explorer.SCOPES["zamknij-w-trakcie"])

    assert report.runs_ended and report.clean_closes
    # Jeden wątek systemu na cały zakres, z limitem kroku (#52), a nie po jednym na wątek modelu.
    assert len(started) == 1


def test_blokada_spoza_modelu_w_kodzie_pod_sprawdzeniem_konczy_sprawdzenie_krokiem_ktory_stoi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prawdziwa blokada w ``RunHost.start`` daje po limicie kroku błąd z wątkiem modelu i krokiem (#52).

    Wątki modelu są greenletami jednego wątku systemu, więc blokada spoza modelu zatrzymuje całe sprawdzenie. Bez
    limitu kroku wisiało ono do limitu 120 s pytest i wyglądało w CI jak flaky test.
    """

    explorer = _load_explorer()
    released = threading.Event()
    start = explorer.runs.RunHost.start

    def start_after_real_event(host: object, prepared: object) -> object:
        released.wait(60)
        return start(host, prepared)

    monkeypatch.setattr(explorer.runs.RunHost, "start", start_after_real_event)
    scope = explorer.SCOPES["zamknij-w-trakcie"]
    try:
        report = explorer.explore(scope, step_limit=1.0)
    finally:
        released.set()
    # Odblokowane sprawdzenie zwija się przy następnym kroku i oddaje podmienione moduły.
    assert wait_for(lambda: all(thread.name != f"sprawdzenie {scope.name}" for thread in threading.enumerate()))

    outcome = explorer.summarize([report])

    assert outcome.exit_code == 2, "\n".join(outcome.lines)
    assert outcome.lines[-1].startswith("URUCHOMIENIA: KROK STOI (1)")
    assert any(
        "wątek modelu „karta Uruchom 1” nie doszedł od kroku „żądanie POST /api/runs dociera do serwera" in line
        for line in outcome.lines
    ), "\n".join(outcome.lines)
    assert any("start_after_real_event" in line for line in outcome.lines), "\n".join(outcome.lines)
