"""Stary proces Centrum, który zamknął port, a jego kolejka Skrzynki Zgłoszeń jeszcze wysyła (#21).

Uruchamiany przez test jako osobny proces: ``python kolejka_starego_procesu.py <folder kolejki> <dziennik>``.
Kolejka startuje (``resume``) ze skrzynką, która na pytanie o issue odpowiada dopiero po linii na standardowym
wejściu. Gdy pytanie trwa, proces wypisuje ``szuka``, a po końcu przejścia treści issue, które założył, jako JSON
w ASCII, bo potok na Windows koduje w cp1252.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from rozliczenia.centrum.keyed_box import KeyedBox  # noqa: E402
from rozliczenia.centrum.log import CentrumLog  # noqa: E402
from rozliczenia.centrum.outbox import Outbox  # noqa: E402

from tests.fixtures.centrum import FakeReportBox  # noqa: E402
from tests.fixtures.clock import ManualClock  # noqa: E402

KEY = "github_pat_SYNTETYCZNY_KLUCZ"
WAIT_S = 60


def main(directory: Path, log: Path) -> int:
    hold = threading.Event()
    box = FakeReportBox(search_hold=hold)
    clock = ManualClock()
    outbox = Outbox(directory, KeyedBox(box, lambda: KEY, clock=clock), CentrumLog(log), clock=clock)
    outbox.resume()
    if not box.searching.wait(WAIT_S):
        return 1
    print("szuka", flush=True)
    sys.stdin.readline()
    hold.set()
    if outbox.wait_delivered("", "kontrola-ilosci", timeout_s=WAIT_S):
        return 1
    print(json.dumps([issue.body for issue in box.issues]), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1]), Path(sys.argv[2])))
