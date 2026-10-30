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
from typing import Any

import pytest

from rozliczenia.centrum import runs
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
        # co uruchomiło sprawdzenie, także z wątków, które samo uruchomiło.
        if threading.current_thread() in checking:
            started.append(thread.name)
            checking.add(thread)
        start(thread)

    monkeypatch.setattr(threading.Thread, "start", counted)

    report = explorer.explore(explorer.SCOPES["zamknij-w-trakcie"])

    assert report.runs_ended and report.clean_closes
    # Jeden wątek systemu prowadzi cały zakres, a wywołujący pilnuje, czy kroki idą.
    assert len(started) <= 1, started


def test_kod_zawieszony_poza_modelem_daje_czytelne_zawieszenie_zamiast_limitu_pytest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prawdziwa blokada w kodzie pod sprawdzeniem zatrzymuje jedyny wątek systemu, na którym biegną wątki modelu.

    Sprawdzenie ma wtedy skończyć się raportem z nazwą wątku modelu i jego krokiem, a nie wisieć do limitu pytest,
    który w CI wygląda jak flaky test (#6).
    """

    explorer = _load_explorer()
    released = threading.Event()  # prawdziwe, nie z modelu
    start = runs.RunHost.start

    def blocked(host: runs.RunHost, prepared: runs.PreparedRun[Any, Any]) -> object:
        released.wait()
        return start(host, prepared)

    monkeypatch.setattr(runs.RunHost, "start", blocked)

    try:
        outcome = explorer.summarize([explorer.explore(explorer.SCOPES["zamknij-w-trakcie"])])
        # Kolejne testy tego workera dostają prawdziwe threading z powrotem, choć wątek sprawdzenia nadal czeka.
        assert vars(runs)["threading"] is threading
    finally:
        released.set()

    assert outcome.exit_code == 3
    assert outcome.lines[-1].startswith("URUCHOMIENIA: ZAWIESZENIE POZA MODELEM (1)")
    assert any(
        "ZAWIESZENIE POZA MODELEM: karta Uruchom 1: brak kolejnego kroku" in line
        and "„żądanie POST /api/runs dociera do serwera”" in line
        and "blocked" in line
        for line in outcome.lines
    ), "\n".join(outcome.lines)
    assert wait_for(lambda: not any(thread.name.startswith("sprawdzenie ") for thread in threading.enumerate()))
