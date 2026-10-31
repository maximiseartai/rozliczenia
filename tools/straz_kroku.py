"""Strażnik kroku sprawdzeń przeplotów: czytelny błąd zamiast wiszenia, gdy kod pod sprawdzeniem stoi poza modelem.

Sprawdzenia przeplotów skilli (``explore_runs.py``, ``explore_publication.py``) prowadzą wątki modelu jako greenlety
na jednym wątku systemu. Kod pod sprawdzeniem, który czeka na coś spoza modelu (prawdziwą blokadę, kolejkę, sen) albo
kręci się w pętli bez kroku, zatrzymuje więc całe sprawdzenie, a nic w tym wątku systemu nie może go obudzić. Bez
strażnika sprawdzenie wisiało do limitu 120 s pytest, a to wyglądało jak flaky test (#84).

Harmonogram sprawdzenia zapisuje w ``StepWatch``, który wątek modelu biegnie, i liczy każdy jego powrót. Strażnik patrzy
z własnego wątku: gdy licznik stoi ``limit_s``, wypisuje na stdout zdanie sprawdzenia o wątku, który nie wrócił, stos
wątku sprawdzenia i linię werdyktu, a potem kończy proces kodem ``STALLED`` bez czekania na zablokowany wątek.
Ostatnia linia wyjścia to werdykt, bo po niej oceniają wynik CI i ``tools/mutacje.py``.

Strażnik zabija proces, więc pilnuje tylko skryptu uruchomionego jako własny proces (``main`` sprawdzenia), nie
sprawdzenia wywołanego w procesie pytest.

    import straz_kroku   # skrypt skilla dodaje tools/ do sys.path

    WATCH: straz_kroku.StepWatch[Actor] = straz_kroku.StepWatch()
    with WATCH.guard(10.0, describe, "URUCHOMIENIA: ZAWIESZENIE"):
        reports = [explore(scope) for scope in scopes]
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
import os
import sys
import threading
import time
import traceback
from types import FrameType
from typing import Generic, TypeVar

STALLED = 3

T = TypeVar("T")


class StepWatch(Generic[T]):
    """Postęp sprawdzenia: wątek modelu, który teraz biegnie, i liczba jego powrotów do harmonogramu."""

    def __init__(self) -> None:
        self.running: T | None = None
        self.returns = 0

    @contextmanager
    def guard(
        self,
        limit_s: float,
        describe: Callable[[T | None, FrameType | None], str],
        verdict: str,
    ) -> Iterator[None]:
        """Pilnuje bloku ``with``: ``describe`` dostaje wątek modelu, który nie wrócił, i ramkę, na której stoi."""

        checking = threading.get_ident()
        stop = threading.Event()

        def watch() -> None:
            seen, since = self.returns, time.monotonic()
            while not stop.wait(limit_s / 10):
                if self.returns != seen:
                    seen, since = self.returns, time.monotonic()
                elif time.monotonic() - since >= limit_s:
                    frame = sys._current_frames().get(checking)
                    stack = traceback.format_stack(frame) if frame is not None else []
                    lines = [describe(self.running, frame), "Stos sprawdzenia:", *"".join(stack).splitlines(), verdict]
                    print("\n".join(lines), flush=True)
                    os._exit(STALLED)

        watcher = threading.Thread(target=watch, name="straż kroku", daemon=True)
        watcher.start()
        try:
            yield
        finally:
            stop.set()
            watcher.join()
