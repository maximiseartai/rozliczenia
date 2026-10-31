"""``tools/limit_kroku.py``: krok sprawdzenia przeplotów, który nie wraca do planisty, kończy sprawdzenie czytelnym błędem.

Macierz biegnie raz, na interfejsie modułu. Oba sprawdzenia przeplotów, które go używają
(``verify-jedno-uruchomienie-naraz`` i ``verify-publikacja-plikow-okresu``), mają po jednym teście, że blokada spoza
modelu w ich kodzie daje ``KROK STOI`` (#52).
"""

from __future__ import annotations

import threading
import time

import pytest

from tests.fixtures.potomne import wait_for

import limit_kroku

STUCK_THREAD = "sprawdzenie przeplotów w teście"


class _Przerwanie(BaseException):
    """Jak Ctrl+C albo limit pytest w sprawdzeniu: wyjątek spoza ``Exception``."""


def _bez_watku_sprawdzenia() -> bool:
    return all(thread.name != STUCK_THREAD for thread in threading.enumerate())


def test_sprawdzenie_bez_zawieszenia_oddaje_swoj_wynik() -> None:
    def work(heartbeat: limit_kroku.Heartbeat) -> str:
        heartbeat.entering("karta 1", "krok 1")
        heartbeat.left()
        return "wynik"

    assert limit_kroku.watched(work, limit=10.0, name=STUCK_THREAD) == "wynik"


def test_wyjatek_sprawdzenia_spoza_exception_dochodzi_do_wolajacego() -> None:
    def work(heartbeat: limit_kroku.Heartbeat) -> str:
        raise _Przerwanie

    with pytest.raises(_Przerwanie):
        limit_kroku.watched(work, limit=10.0, name=STUCK_THREAD)


def test_limit_pytest_w_watku_czekajacym_porzuca_sprawdzenie_ktore_idzie_dalej(monkeypatch: pytest.MonkeyPatch) -> None:
    """``Failed: Timeout`` i Ctrl+C przychodzą tylko do głównego wątku, czyli do czekania w ``watched``.

    Bez porzucenia sprawdzenie szło dalej i podmieniało moduły pod następnymi testami tego workera.
    """

    join = threading.Thread.join
    waiting = threading.current_thread()
    steps: list[int] = []

    def join_until_limit(thread: threading.Thread, timeout: float | None = None) -> None:
        if threading.current_thread() is waiting and steps:
            raise _Przerwanie
        join(thread, timeout)

    def work(heartbeat: limit_kroku.Heartbeat) -> None:
        while True:
            heartbeat.entering("karta 1", f"krok {len(steps)}")
            heartbeat.left()
            steps.append(len(steps))

    monkeypatch.setattr(threading.Thread, "join", join_until_limit)

    with pytest.raises(_Przerwanie):
        limit_kroku.watched(work, limit=10.0, name=STUCK_THREAD)

    assert wait_for(_bez_watku_sprawdzenia)


def test_sprawdzenie_ktore_idzie_wolno_ale_idzie_trwa_dluzej_niz_limit_kroku() -> None:
    """Limit liczy się od ostatniego kroku, nie od startu: zajęty runner nie robi z wolnego sprawdzenia zawieszenia."""

    limit = 0.6

    def work(heartbeat: limit_kroku.Heartbeat) -> int:
        steps = 0
        until = time.monotonic() + 3 * limit
        while (now := time.monotonic()) < until:
            heartbeat.entering("karta 1", f"krok {steps}")
            heartbeat.left()
            steps += 1
            while time.monotonic() < now + limit / 4:
                pass  # praca kroku bez tętna, krótsza od limitu
        return steps

    assert isinstance(limit_kroku.watched(work, limit=limit, name=STUCK_THREAD), int)


@pytest.mark.parametrize(
    ("actor", "where"),
    [
        ("karta Uruchom 1", "wątek modelu „karta Uruchom 1” nie doszedł od kroku „żądanie POST /api/runs” do następnego kroku"),
        (None, "planista nie doszedł do następnego kroku poza wątkami modelu"),
    ],
)
def test_krok_zatrzymany_na_blokadzie_spoza_modelu_konczy_sprawdzenie_bledem_z_watkiem_krokiem_i_stosem(
    actor: str | None, where: str
) -> None:
    released = threading.Event()
    went_on: list[str] = []

    def stuck_on_real_event() -> None:
        released.wait(60)

    def work(heartbeat: limit_kroku.Heartbeat) -> None:
        heartbeat.entering("karta Uruchom 1", "żądanie POST /api/runs")
        if actor is None:
            heartbeat.left()
        stuck_on_real_event()
        heartbeat.entering("karta Uruchom 1", "wejście w blokadę")
        went_on.append("następny krok")

    try:
        outcome = limit_kroku.watched(work, limit=0.5, name=STUCK_THREAD)
    finally:
        released.set()

    assert isinstance(outcome, limit_kroku.Stuck)
    lines = outcome.lines()
    assert lines[0].startswith(f"KROK STOI: {where} w 0.5 s.")
    assert any("stuck_on_real_event" in line for line in lines[1:])
    # Sprawdzenie, na które nikt już nie czeka, zwija się przy następnym kroku, zamiast iść dalej obok następnego.
    assert wait_for(_bez_watku_sprawdzenia)
    assert went_on == []
