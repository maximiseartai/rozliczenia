"""Publikacja plików okresu w Przygotowaniu pliku zbiorczego we wszystkich harmonogramach w zakresie.

Przerwanie procesu, błąd systemu plików, drugie Uruchomienie procesu i działanie
taty między krokami publikacji są poza zasięgiem testów przez
``prepare_collective_file()``, więc sprawdza je wyczerpująco skrypt skilla
``verify-publikacja-plikow-okresu`` na prawdziwym ``preparation_files.py``.
Zakres, znane ustalenia i postępowanie przy porażce opisuje
``.agents/skills/verify-publikacja-plikow-okresu/SKILL.md``.
"""

from __future__ import annotations

import importlib.util
import os
import stat
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
    / "verify-publikacja-plikow-okresu"
    / "scripts"
    / "explore_publication.py"
)


def _load_explorer() -> ModuleType:
    spec = importlib.util.spec_from_file_location("explore_publication", EXPLORER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# Sprawdzenie jako własny proces, jak w CI, bo tylko takiemu strażnik kroku może przerwać kod stojący poza modelem (#84):
# argumenty to plik sprawdzenia, limit kroku w sekundach i argumenty sprawdzenia, a {change} zmienia kod przed startem.
DRIVER = """
import importlib.util, sys

spec = importlib.util.spec_from_file_location("explore_publication", sys.argv[1])
explorer = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = explorer
spec.loader.exec_module(explorer)
explorer.STEP_LIMIT_SECONDS = float(sys.argv[2])
{change}
raise SystemExit(explorer.main(sys.argv[3:]))
"""

INTERLEAVED = "drugie Uruchomienie procesu weszło między kroki pierwszego"

# Drukuje INTERLEAVED raz, gdy pierwszy raz write_period_files zaczyna się, zanim skończyło się inne.
COUNTING_INTERLEAVING = f"""
write_period_files = explorer.preparation_files.write_period_files
writing = 0
interleaved = False

def counted(*args):
    global writing, interleaved
    if writing and not interleaved:
        interleaved = True
        print("{INTERLEAVED}")
    writing += 1
    try:
        return write_period_files(*args)
    finally:
        writing -= 1

explorer.preparation_files.write_period_files = counted
"""

# Sprawdzenie, czy plików okresu nie ma, kręci się tu w pętli bez wywołania systemu plików, więc żaden krok nie wraca.
SPINNING = """
def spinning(files):
    while True:
        pass

explorer.preparation_files.ensure_period_files_absent = spinning
"""


def _check(limit_s: float, *arguments: str, change: str) -> subprocess.CompletedProcess[str]:
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


@pytest.mark.dlugi
def test_publikacja_plikow_okresu_zachowuje_nienadpisywanie_i_razem_albo_zaden_w_kazdym_harmonogramie() -> None:
    # Limit kroku 1 s przy sprawdzeniu dłuższym niż on: strażnik przerywa tylko krok, który nie wraca, nie całe
    # sprawdzenie (pełne sprawdzenie trwa na Macu około 8 s).
    done = _check(1.0, change=COUNTING_INTERLEAVING)

    assert done.returncode == 0, done.stdout + done.stderr
    # Drugie Uruchomienie procesu musi wejść między kroki pierwszego, inaczej zakres dwóch Uruchomień sprawdza tylko
    # jedno po drugim i OK niczego nie mówi o wyścigu.
    assert INTERLEAVED in done.stdout, "w żadnym harmonogramie drugie Uruchomienie procesu nie ruszyło przed końcem pierwszego"


def test_kod_publikacji_bez_kolejnego_kroku_konczy_sprawdzenie_nazwa_uruchomienia_i_kroku_zamiast_limitu_pytest() -> None:
    """Sprawdzenie nie wisi do limitu 120 s pytest, które wyglądało jak flaky test, tylko mówi, co stoi i gdzie (#84)."""

    done = _check(2.0, "--scope", "jedno-uruchomienie", change=SPINNING)

    lines = done.stdout.splitlines()
    assert done.returncode == 3, done.stdout + done.stderr
    assert lines[-1] == "PUBLIKACJA: ZAWIESZENIE: krok nie wrócił w 2 s, więc nie ma werdyktu o regułach."
    assert lines[0].startswith(
        "ZAWIESZENIE: Uruchomienie procesu u1 po kroku „zapis skoroszytu=None” nie doszło do kolejnego kroku w 2 s "
        "i stoi w [preparation_files.py:"
    ), lines[0]
    assert " _publish]: kod kręci się bez wywołania systemu plików" in lines[0]


def test_sprawdzenie_publikacji_prowadzi_uruchomienia_bez_watkow_systemu(monkeypatch: pytest.MonkeyPatch) -> None:
    """Czas sprawdzenia nie zależy od tego, jak zajęte są procesory runnera.

    Wątek systemu na każde Uruchomienie procesu w każdym harmonogramie oddawał sterowanie przez jądro przy każdym
    kroku, a na runnerze Windows z Pythonem 3.11 zajętym innymi workerami xdist sprawdzenie dochodziło do limitu
    120 s pytest i worker ginął (`main` od 6f94edb8).
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

    report = explorer.explore(explorer.SCOPES["jedno-uruchomienie"])

    assert report.undisturbed_successes
    assert started == []


class _LimitCzasu(BaseException):
    """Jak `Failed: Timeout` pytest-timeout: wyjątek spoza `Exception`, który sygnał rzuca w kodzie publikacji."""


@pytest.mark.parametrize("zatrzymanie", range(1, 21))
def test_limit_czasu_w_kodzie_publikacji_konczy_sprawdzenie_tym_limitem(
    monkeypatch: pytest.MonkeyPatch, zatrzymanie: int
) -> None:
    """Limit pytest, który przychodzi w Uruchomieniu procesu, kończy sprawdzenie, a nie jedno Uruchomienie.

    Na Linuksie i macOS pytest-timeout rzuca `Failed: Timeout` w bieżącej ramce, a ta należy często do kodu
    publikacji w greenlecie Uruchomienia. Połknięty jako Zatrzymanie albo przerwany jak harmonogram w znanym stanie,
    zmieniał drzewo harmonogramów: sprawdzenie kończyło się `IndexError`, fałszywym naruszeniem albo przechodziło,
    a pętla bez końca w kodzie publikacji nie kończyła się wcale. Limit przychodzi tu w chwili N-tego Zatrzymania
    w `ensure_period_files_absent`, bo sprzątanie po nim trafia też w stany sprawdzone wcześniej.
    """

    explorer = _load_explorer()
    ensure_absent = explorer.preparation_files.ensure_period_files_absent
    stops = 0

    def ensure_absent_until_limit(files: object) -> None:
        nonlocal stops
        try:
            ensure_absent(files)
        except Exception:
            stops += 1
            if stops == zatrzymanie:
                raise _LimitCzasu from None
            raise

    monkeypatch.setattr(explorer.preparation_files, "ensure_period_files_absent", ensure_absent_until_limit)

    with pytest.raises(_LimitCzasu):
        explorer.explore(explorer.SCOPES["dwa-uruchomienia"])


def _istnieje_przez_os_stat(path: Path) -> bool:
    try:
        path.stat()
    except OSError:
        return False
    return True


def _dowiazanie_przez_os_lstat(path: Path) -> bool:
    try:
        return stat.S_ISLNK(path.lstat().st_mode)
    except OSError:
        return False


def test_drzewo_harmonogramow_nie_zalezy_od_tego_czym_pathlib_pyta_o_plik(monkeypatch: pytest.MonkeyPatch) -> None:
    """Na każdej wersji Pythona sprawdzenie przechodzi te same harmonogramy.

    Na Pythonie 3.11 i 3.12 `Path.exists` i `Path.is_symlink` pytają `Path.stat` i `Path.lstat`, a na 3.14
    `os.path.exists` i `os.path.islink`, których odpowiedzi mówią mniej. Stan zapamiętywał odpowiedź, więc na 3.14
    łączył stany, które 3.12 rozróżnia, i przechodził 6640 harmonogramów `dwa-uruchomienia` zamiast 9798.
    """

    explorer = _load_explorer()
    trees = {}
    for version, exists, is_symlink in (
        ("3.11 i 3.12", _istnieje_przez_os_stat, _dowiazanie_przez_os_lstat),
        # Przechwytywanie podmienia os.path.exists i os.path.islink, więc szukamy ich w chwili wywołania.
        ("3.14", lambda path: os.path.exists(path), lambda path: os.path.islink(path)),
    ):
        monkeypatch.setattr(Path, "exists", lambda path, exists=exists, **_: exists(path))
        monkeypatch.setattr(Path, "is_symlink", lambda path, is_symlink=is_symlink: is_symlink(path))
        report = explorer.explore(explorer.SCOPES["jedno-uruchomienie"])
        trees[version] = (report.schedules, report.states)

    assert trees["3.11 i 3.12"] == trees["3.14"], trees
