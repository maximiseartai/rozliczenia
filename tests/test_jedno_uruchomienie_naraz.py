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

    outcome = explorer.summarize(explorer.explore_scopes(explorer.SCOPES.values()))

    assert outcome.exit_code == 0, "\n".join(outcome.lines)


def test_sprawdzenie_przeplotow_prowadzi_watki_modelu_bez_watkow_systemu(monkeypatch: pytest.MonkeyPatch) -> None:
    """Czas sprawdzenia nie zależy od tego, jak zajęte są procesory runnera (#565).

    Wątek systemu na każdy wątek modelu oddawał sterowanie przez jądro przy każdym kroku, a na runnerze CI zajętym
    innymi workerami xdist sprawdzenie dochodziło do limitu 120 s pytest. Jeden wątek systemu na cały zakres, którego
    pilnuje wątek wywołujący, takiego oddawania nie ma.
    """

    explorer = _load_explorer()
    started: list[str] = []
    start = threading.Thread.start
    checking = {threading.current_thread()}

    def counted(thread: threading.Thread) -> None:
        # Wątki tła zostawione przez wcześniejsze testy w tym workerze startują swoje wątki same; liczy się tylko to,
        # co uruchomiło sprawdzenie, i to, co uruchomiły jego wątki.
        if threading.current_thread() in checking:
            started.append(thread.name)
            checking.add(thread)
        start(thread)

    monkeypatch.setattr(threading.Thread, "start", counted)

    report = explorer.explore(explorer.SCOPES["zamknij-w-trakcie"])

    assert report.runs_ended and report.clean_closes
    assert started == [explorer.CHECKER_THREAD]


def test_kod_stojacy_na_prawdziwej_blokadzie_konczy_sprawdzenie_werdyktem_z_watkiem_modelu_i_krokiem(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prawdziwa blokada spoza kroków modelu daje BLOKADA SPOZA MODELU, a nie limit 120 s pytest.

    Wątki modelu dzielą jeden wątek systemu, więc taka blokada zatrzymuje całe sprawdzenie, a limit pytest wygląda w CI
    jak kolejny flaky test (#565).
    """

    explorer = _load_explorer()
    released = threading.Event()
    start = explorer.runs.RunHost.start

    def blocked(host: object, prepared: object) -> object:
        released.wait()  # prawdziwe Event: model zastępuje threading tylko w runs.py i shutdown.py
        return start(host, prepared)

    monkeypatch.setattr(explorer.runs.RunHost, "start", blocked)
    monkeypatch.setattr(explorer, "STEP_TIMEOUT_SECONDS", 1.0)
    started_after_stall: list[str] = []
    start_thread = threading.Thread.start

    def counted(thread: threading.Thread) -> None:
        if threading.current_thread().name == explorer.CHECKER_THREAD:
            started_after_stall.append(thread.name)
        start_thread(thread)

    try:
        outcome = explorer.summarize(explorer.explore_scopes(explorer.SCOPES.values()))
        # Zablokowany wątek sprawdzenia sam nie przywróci kodu, a kolejne testy tego workera prowadzą prawdziwy RunHost.
        real_code_back = explorer.runs.threading is threading and explorer.shutdown.threading is threading
    finally:
        # Porzucone sprawdzenie, które blokada puści, kończy się na swoim kolejnym kroku: dalej biegłoby na prawdziwym
        # threading i startowało prawdziwe wątki Uruchomienia w tym workerze.
        monkeypatch.setattr(threading.Thread, "start", counted)
        released.set()
        assert wait_for(lambda: all(thread.name != explorer.CHECKER_THREAD for thread in threading.enumerate()))

    report = "\n".join(outcome.lines)
    assert outcome.exit_code == 2, report
    assert (
        "  BLOKADA SPOZA MODELU: „karta Uruchom 1” stoi po kroku „żądanie POST /api/runs dociera do serwera” "
        "dłużej niż 1 s w kodzie poza krokami modelu"
    ) in outcome.lines, report
    assert "released.wait()" in report
    assert real_code_back
    assert started_after_stall == []
    assert outcome.lines[-1].startswith("URUCHOMIENIA: BLOKADA SPOZA MODELU (1)"), report
