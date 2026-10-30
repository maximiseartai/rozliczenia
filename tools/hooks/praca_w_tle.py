#!/usr/bin/env python3
"""Hook ``Stop`` Claude Code: agent nie kończy tury, dopóki w tle jego sesji biegnie polecenie Basha albo Monitor.

Tura oddana z pracą w tle wygląda na skończoną, choć wyniku jeszcze nie ma: rodzic dostaje hand-back dziecka bez
wyniku, a ``claude -p`` oddaje pierwszy ``result`` („Uruchomione w tle.”) i dopiero po powiadomieniu drugi, z wynikiem
(Claude Code 2.1.312, próba H6 30.10.2026). Koordynator czekał tak na dziecko 5 h (29.10).

Claude Code podaje hookowi ``Stop`` listę ``background_tasks`` z zadaniami sesji, które jeszcze biegną (skończone
z niej znikają), każde z ``type`` i ``status``. Hook odmawia (JSON ``{"decision": "block", "reason": …}`` na stdout,
a ``reason`` trafia do agenta jako polecenie dalszej pracy), gdy na liście jest zadanie typu ``TYPES`` (``shell``
z Basha ``run_in_background`` i z narzędzia Monitor, które lista też podaje jako ``shell``, oraz ``monitor``) o statusie spoza ``FINISHED``: status, którego hook nie zna, liczy się
jako żywy. Odmawia także przy ``stop_hook_active``, bo zadanie w końcu się kończy albo agent je zatrzymuje, a pętlę
bez końca ucina Claude Code po ośmiu odmowach z rzędu (``CLAUDE_CODE_STOP_HOOK_BLOCK_CAP``).

Wszystko inne przechodzi bez słowa (kod 0): pusta lista, inne typy zadań (podagent, workflow, sesja w chmurze, które
same raportują wywołującemu), zaplanowane wybudzenia (``session_crons``) i wejście bez ``background_tasks`` albo
nieczytelne, bo hook nie może zatrzymać pracy. Granica: inne harnessy niż Claude Code (Codex, opencode) i Claude Code
bez pola ``background_tasks`` łapie tylko przegląd. Hook nie jest wpięty w ``SubagentStop``, bo tam lista należy do
sesji rodzica, nie podagenta.
Uruchamia go systemowy Python (na Macu 3.9), więc ruff sprawdza ten plik pod 3.9
(``per-file-target-version`` w ``pyproject.toml``), a plik importuje tylko bibliotekę standardową.
"""

from __future__ import annotations

import json
import sys

TYPES = frozenset({"shell", "monitor"})
# Statusy z powiadomień o końcu zadania (``<status>`` w ``task-notification``, ``stopped`` po TaskStop w próbie H6);
# skończone zwykle już znikają z listy.
FINISHED = frozenset({"completed", "failed", "killed", "stopped"})


def alive(event: object) -> list[str]:
    """Opisy żywych zadań ``TYPES`` z wejścia hooka ``Stop``; pusta lista, gdy nie ma żadnego albo wejścia nie da się odczytać."""

    tasks = event.get("background_tasks") if isinstance(event, dict) else None
    if not isinstance(tasks, list):
        return []
    found = []
    for task in tasks:
        if isinstance(task, dict) and task.get("type") in TYPES and task.get("status") not in FINISHED:
            found.append(f"{task['type']} {task.get('id')} „{task.get('command') or task.get('description')}”")
    return found


def refusal(tasks: list[str]) -> str:
    return (
        f"Odmowa końca tury: w tle sesji biegnie jeszcze {'; '.join(tasks)}. Tura oddana z pracą w tle wygląda na "
        "skończoną, choć wyniku jeszcze nie ma: wywołujący (rodzic, claude -p) dostaje odpowiedź bez niego. "
        "Przed końcem tury poczekaj na koniec zadania (w T3 t3_background_wait z jego ID) i zapisz jego wynik, albo "
        "zatrzymaj je (TaskStop z jego ID), uruchom tę pracę na pierwszym planie (Bash bez run_in_background, do "
        "600000 ms, dłuższą dziel na części) i zapisz wynik. Monitor też biegnie w tle, więc nie zastępuje czekania, "
        "a pętla z sleep nie jest czekaniem na wynik."
    )


def main() -> int:
    try:
        event = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    except (ValueError, RecursionError):
        return 0
    tasks = alive(event)
    if tasks:
        print(json.dumps({"decision": "block", "reason": refusal(tasks)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
