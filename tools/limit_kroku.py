"""Limit kroku sprawdzenia przeplotów, którego wątki modelu są greenletami jednego wątku systemu.

Sprawdzenia przeplotów skilli ``verify-jedno-uruchomienie-naraz`` i ``verify-publikacja-plikow-okresu`` prowadzą
wątki modelu jako greenlety na jednym wątku systemu (#565). Planista nie może wywłaszczyć greenletu, więc kod pod
sprawdzeniem, który czeka na coś spoza modelu (prawdziwą blokadę, sen, wejście-wyjście) albo kręci się bez końca,
zatrzymuje całe sprawdzenie, a to wisiało do limitu 120 s pytest jak flaky test (#52).

``watched`` prowadzi sprawdzenie w jednym własnym wątku systemu i patrzy na jego tętno (``Heartbeat``): planista
zgłasza każde oddanie sterowania wątkowi modelu i każdy powrót. Gdy przez ``limit`` sekund żadne nie przyszło,
``watched`` zwraca ``Stuck`` z nazwą wątku modelu, krokiem, od którego ruszył, i jego stosem. Limit liczy się od
ostatniego tętna, nie od startu, więc sprawdzenie, które na zajętym runnerze idzie wolno, ale idzie, nie staje.

Granica: wątek, który stanął, zostaje w procesie z podmianami swojego sprawdzenia, bo nic nie przerwie blokady
w kodzie C. Gdy kiedyś ruszy, przy następnym kroku dostaje ``Abandoned`` i zwija się, więc nie miesza już w
sprawdzeniu, na które nikt nie czeka.

    import limit_kroku   # skrypt skilla dopisuje tools/ do sys.path

    outcome = limit_kroku.watched(lambda heartbeat: explore(scope, heartbeat), limit=10.0, name="sprawdzenie")
    if isinstance(outcome, limit_kroku.Stuck):
        print("\\n".join(outcome.lines()))
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import sys
import threading
import time
import traceback
from typing import TypeVar

T = TypeVar("T")

STEP_LIMIT_SECONDS = 10.0
"""Jeden krok modelu trwa mikrosekundy; 10 s bez kroku to zawieszenie także na runnerze zajętym innymi workerami."""


class Abandoned(BaseException):
    """Nikt już nie czeka na to sprawdzenie: jego wątek zwija się przy następnym kroku."""


class Heartbeat:
    """Co sprawdzenie robi teraz: który wątek modelu ma sterowanie i od którego kroku."""

    def __init__(self) -> None:
        self.beats = 0
        self.actor: str | None = None
        self.step = ""
        self.abandoned = False

    def entering(self, actor: str, step: str) -> None:
        """Planista oddaje sterowanie wątkowi modelu ``actor``, który rusza od kroku ``step``."""

        if self.abandoned:
            raise Abandoned
        self.beats += 1
        self.actor = actor
        self.step = step

    def left(self) -> None:
        """Wątek modelu oddał sterowanie planiście."""

        self.beats += 1
        self.actor = None


@dataclass(frozen=True)
class Stuck:
    """Krok, który nie wrócił do planisty w limicie."""

    actor: str | None
    step: str
    seconds: float
    stack: tuple[str, ...]

    def lines(self) -> list[str]:
        where = (
            f"wątek modelu „{self.actor}” nie doszedł od kroku „{self.step}” do następnego kroku"
            if self.actor is not None
            else "planista nie doszedł do następnego kroku poza wątkami modelu"
        )
        return [
            f"KROK STOI: {where} w {self.seconds:g} s. Kod pod sprawdzeniem czeka na coś spoza modelu "
            "(prawdziwą blokadę, sen, wejście-wyjście) albo kręci się bez końca. Jego stos:",
            *(line for entry in self.stack for line in entry.rstrip("\n").splitlines()),
        ]


def watched(work: Callable[[Heartbeat], T], *, limit: float, name: str) -> T | Stuck:
    """Wynik ``work`` z jego wątku albo ``Stuck``; wyjątek ``work``, także spoza ``Exception``, rzuca dalej."""

    heartbeat = Heartbeat()
    result: list[T] = []
    failure: list[BaseException] = []

    def body() -> None:
        try:
            result.append(work(heartbeat))
        except Abandoned:
            pass
        except BaseException as error:  # noqa: BLE001 - the caller raises it, whatever it is
            failure.append(error)

    thread = threading.Thread(target=body, name=name, daemon=True)
    thread.start()
    beats, since = heartbeat.beats, time.monotonic()
    try:
        while thread.is_alive():
            thread.join(limit / 10)
            now = time.monotonic()
            if heartbeat.beats != beats:
                beats, since = heartbeat.beats, now
            elif thread.is_alive() and now - since >= limit:
                heartbeat.abandoned = True
                frame = sys._current_frames().get(thread.ident or 0)
                stack = tuple(traceback.format_stack(frame)) if frame is not None else ()
                return Stuck(heartbeat.actor, heartbeat.step, limit, stack)
    except BaseException:
        # pytest's limit and Ctrl+C reach only the main thread, so here; without this the check would go on patching
        # modules under the next tests of the worker.
        heartbeat.abandoned = True
        raise
    if failure:
        raise failure[0]
    return result[0]
