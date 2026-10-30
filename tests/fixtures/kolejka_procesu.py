"""Stare Centrum w osobnym procesie: jego kolejka Skrzynki w trakcie przejścia, gdy nowe Centrum już startuje.

``python -m tests.fixtures.kolejka_procesu <folder kolejki> <plik blokady> <dziennik>`` (z katalogu repozytorium):
kolejka startuje (``Outbox.resume``), a gdy jej przejście pyta skrzynkę o issue okresu, proces pisze ``szuka`` i
czeka na wiersz na wejściu, jak stare Centrum, które zamknęło już port, a jego wątek kolejki dalej wysyła. Potem
skrzynka odpowiada, a proces pisze, ile issue założyła jego kolejka (``issue: n``), i kończy się.
"""

from __future__ import annotations

from pathlib import Path
import sys
import threading

from rozliczenia.centrum.keyed_box import KeyedBox
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.outbox import Outbox

from tests.fixtures.centrum import FakeReportBox
from tests.fixtures.clock import ManualClock

SEARCH_WAIT_S = 30


def main(directory: Path, lock: Path, log: Path) -> int:
    hold = threading.Event()
    box = FakeReportBox(search_hold=hold)
    clock = ManualClock()
    outbox = Outbox(directory, KeyedBox(box, lambda: "klucz", clock=clock), CentrumLog(log), clock=clock, lock=lock)
    outbox.resume()
    if not box.searching.wait(SEARCH_WAIT_S):
        print("nie szuka", flush=True)
        return 1
    print("szuka", flush=True)
    sys.stdin.readline()
    hold.set()
    outbox.wait_delivered("", "kontrola-ilosci", timeout_s=SEARCH_WAIT_S)
    print(f"issue: {len(box.issues)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])))
