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

from rozliczenia.centrum import contract, runs
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
    innymi workerami xdist sprawdzenie dochodziło do limitu 120 s pytest. Całe sprawdzenie biegnie w jednym wątku
    systemu, na który test czeka z limitem kroku.
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
    assert started == ["sprawdzenie przeplotów zamknij-w-trakcie"]


def test_blokada_spoza_modelu_konczy_sprawdzenie_bledem_z_watkiem_i_krokiem_zamiast_limitu_pytest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Kod pod sprawdzeniem zatrzymany na prawdziwej blokadzie nie wygląda w CI jak flaky test (#91).

    Bez limitu kroku sprawdzenie wisiało do limitu 120 s pytest, tak jak przy flaky teście z #565. Gdy blokada
    kiedyś puści, porzucone sprawdzenie staje na następnym kroku i nie zaczyna nowego harmonogramu w tle, a moduły
    Centrum od razu wracają do prawdziwego ``threading``, żeby następne testy w tym workerze go nie dzieliły.
    """

    explorer = _load_explorer()
    released = threading.Event()
    publish = runs.RunHost._publish_locked
    calls: list[contract.RunView] = []
    host_init = runs.RunHost.__init__
    hosts_after_release: list[runs.RunHost] = []

    def counted_host(host: runs.RunHost, *args: object, **kwargs: object) -> None:
        # Każdy harmonogram tworzy swój RunHost, więc RunHost po zwolnieniu blokady to nowy harmonogram w tle.
        if released.is_set():
            hosts_after_release.append(host)
        host_init(host, *args, **kwargs)  # type: ignore[arg-type]

    def blocked(host: runs.RunHost, view: contract.RunView) -> None:
        calls.append(view)
        released.wait()
        publish(host, view)

    monkeypatch.setattr(runs.RunHost, "_publish_locked", blocked)
    monkeypatch.setattr(runs.RunHost, "__init__", counted_host)
    try:
        with pytest.raises(explorer.Hang) as hang:
            explorer.explore(explorer.SCOPES["zamknij-w-trakcie"], step_limit=2)
        assert vars(runs)["threading"] is threading
    finally:
        released.set()

    assert wait_for(lambda: not any(thread.name.startswith("sprawdzenie przeplotów") for thread in threading.enumerate()))
    assert len(calls) == 1
    assert hosts_after_release == []
    message = str(hang.value)
    assert "Wątek modelu „karta Uruchom 1” nie doszedł do kolejnego kroku po kroku „wejście w blokadę RunHost._lock”" in message
    assert "[runs.py:" in message and " start]" in message
