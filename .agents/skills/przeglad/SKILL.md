---
name: przeglad
description: Przegląd PR w tym repozytorium, wspólny dla autora i recenzenta - co jest porażką (Ważne, Drobne), jakie dowody, postać werdyktu i kolejne rundy. Użyj przed pushem, żeby świeży agent przejrzał Twój diff (tryb autora), i jako niezależny recenzent PR, zanim napiszesz i opublikujesz werdykt PASS albo FAIL (tryb recenzenta). Tryb podaje wywołujący.
---

# Przegląd PR

Ten skill ma wspólne reguły przeglądu i dwa tryby, które różnią się tylko krokami końcowymi: tryb autora przed pushem i tryb recenzenta, który publikuje werdykt na PR.
Wywołujący podaje tryb w zleceniu.
`PASS` mówi też, że skille `verify-*` z linii `SKILLE VERIFY` przeszły na tym SHA (gotowość w [`AGENTS.md`](../../../AGENTS.md)).
Postać werdyktu, którą przyjmuje `tools/scal_pr.py`, podaje jego `--help`.

## Co jest porażką

Ważne znalezisko to defekt zachowania z dowodem, który da się powtórzyć: polecenie, jego wynik i plik:linia.
Tylko Ważne daje `FAIL`.
W tym repo Ważne były zwykle:

- test, który przestał sprawdzać to, co sprawdzał (pokrycie zgubione przy refaktorze, asercja na tekst zamiast na zachowanie);
- zachowanie widoczne tylko na Windows albo na Pythonie 3.11 (brak `tzdata`, krok zegara `time.monotonic()`, import, który pada tylko pod 3.11);
- stan, który jedna część przebiegu zakłada po innej (część podstawy skilla startująca od środka porządku);
- przypisanie albo zakres liczony od złej linii lub złego commitu (np. `git blame` pierwszej linii wielowierszowej instrukcji).

Drobne znalezisko to luka bez defektu: przeżyta mutacja, której nic nie łapie, nieaktualne zdanie w dokumencie, kosztowna, ale poprawna droga.
Drobnych podaj najwyżej 3, najważniejsze.
Defekt, który zmiana PR wywołuje albo ujawnia, liczy się do werdyktu także wtedy, gdy siedzi w pliku, którego PR nie zmienia (np. nowa konfiguracja uruchamia niezmieniony kod w nowym stanie).
Istniejące wcześniej to tylko defekt, który powtarzasz na merge-base bez tej zmiany, i do werdyktu się nie liczy.
Styl, nazwy i formatowanie zostawiasz ruffowi, mypy i lintom frontendu.

## Dowody

Każde znalezisko ma plik:linia i dowód: polecenie z wynikiem, repro albo mutację z `tools/mutacje.py` (`NIEWYKRYTA` albo `WYKRYTA`).
Recenzent refaktoru, czyli zmiany, która nie ma zmieniać zachowania procesów, uruchamia `.venv/bin/python tools/rownowaznosc.py --baza <merge-base>` i wkleja do werdyktu jego ostatnią linię.
Recenzent PR-u, który dodaje albo zmienia sprawdzenie (test struktury, regułę lintu, zadanie CI, narzędzie sprawdzające), uruchamia samo to sprawdzenie przez `tools/na_scalonych_pr.py --commit <SHA>` na jednym z commitów, które opis PR podaje jako złapane, i wkleja ostatnią linię wyniku.
Mutacje recenzenta biegną po kolei, z `PYTEST_XDIST_AUTO_NUM_WORKERS=1`, najwyżej kilkanaście.
Pełnych mutacji i pełnego CI recenzent nie uruchamia lokalnie, bo liczy je CI i noc (ADR 0021).

## Postać werdyktu

Pierwsza linia to `WERDYKT: PASS <pełny SHA HEAD>` albo `WERDYKT: FAIL <pełny SHA HEAD>`.
Druga podaje liczbę znalezisk w postaci `Znaleziska: N (Ważne a, Drobne b)`.
Dalej znaleziska od najważniejszego, każde z oznaczeniem, plik:linia i dowodem, a na końcu krótko, co sprawdzone i z jakim wynikiem.
Każde Ważne nazywa klasę błędu (np. parser, który przepuszcza formę, której nie zna) i wymienia wszystkie jej wystąpienia w diffie, każde z plik:linia, żeby autor poprawił całą klasę w jednej rundzie.

## Kolejne rundy

Runda po `FAIL` sprawdza diff od przejrzanego SHA do nowego HEAD i to, czy każde znalezisko poprzedniej rundy jest zamknięte.
Zamkniętych znalezisk nie powtarza.
Nowe znalezisko w kodzie, którego ta runda nie zmieniła, jest Ważne tylko wtedy, gdy to defekt zachowania z dowodem.
Po trzeciej rundzie z `FAIL` koordynator nie zleca czwartej, tylko zmienia podejście albo dzieli PR.
Każdą rundę robi nowy recenzent, który nie pisał kodu, z linkiem do poprzednich werdyktów.

## Tryb autora: przed pushem

Autor daje swój diff jednemu świeżemu recenzentowi przed pushem, poprawia Ważne i niczego nie publikuje.
Ten przegląd nie zastępuje niezależnego przeglądu PR i nie blokuje pushu.

1. Zacommituj zmianę i przejdź `.venv/bin/python tools/szybko.py`.
   Krok kończy się, gdy `szybko.py` przechodzi na HEAD, który chcesz wypchnąć.
2. Zleć przegląd jednemu nowemu agentowi, który nie zna Twojej rozmowy.
   Podaj mu ten skill w trybie autora, katalog worktree, pełny SHA HEAD, merge-base z `origin/main` (`git merge-base HEAD origin/main`) i cel zmiany jednym zdaniem, bez własnej oceny diffu.
   Recenzent przegląda diff od merge-base do HEAD według reguł wyżej i oddaje werdykt w postaci z sekcji „Postać werdyktu” w odpowiedzi, bez komentarza na GitHubie.
   Krok kończy się, gdy masz jego werdykt.
3. Popraw każde Ważne, a Drobne popraw albo zapisz z powodem w opisie PR.
   Po poprawkach znów przejdź `tools/szybko.py`, a drugiej rundy przeglądu autora nie zlecasz.
   Krok kończy się, gdy każde Ważne ma poprawkę w commicie.
4. Wypchnij gałąź.
   Werdykt autora zostaje u Ciebie: `PASS` na PR pisze tylko niezależny recenzent w trybie recenzenta.

## Tryb recenzenta: werdykt na PR

Niezależny recenzent, który nie pisał kodu, przegląda HEAD PR i publikuje werdykt przez `tools/scal_pr.py`.
Kto zleca przegląd, podaje numer PR i katalog biegu, w którym leży plik werdyktu (`~/.t3/notes/<bieg>/recenzje/<PR>/`), a bez biegu plik leży w `~/.t3/notes/recenzje/<PR>/`.

1. Uruchom `.venv/bin/python tools/scal_pr.py <PR> --przeglad`.
   Drukuje pełny SHA HEAD, merge-base z bazą, `git diff --stat`, zmienione pliki, wynik `tools/skille_dla_zmiany.py` dla HEAD PR i poprzednie werdykty z ich SHA i dwiema pierwszymi liniami.
   Krok kończy się, gdy masz SHA HEAD i merge-base; poprzedni werdykt znaczy, że to kolejna runda (sekcja „Kolejne rundy”).
2. Znajdź kandydatów na znaleziska.
   W pierwszej rundzie (PR bez werdyktu, linia `RUNDA | 1`) uruchom w jednej wiadomości trzech szukających: agentów (narzędzie Agent) z modelem Opus i `run_in_background: false`.
   Każdy dostaje ten skill, katalog repo, pełny SHA HEAD, merge-base, tytuł i opis PR oraz jedną soczewkę:
   - zachowanie i błędy: defekty z sekcji „Co jest porażką” w diffie i w niezmienionym kodzie, który diff uruchamia w nowym stanie;
   - obietnice i dowody: każde zdanie opisu PR oraz docstringu, `--help`, `SKILL.md` i ADR zmienionego w diffie ma test, przebieg albo mutację, która je pokazuje;
   - Windows, Python 3.11 i kolejność: zachowanie zależne od systemu albo wersji Pythona (sekcja „Tools and Platforms” w `CODING_STANDARDS.md`) i test zależny od kolejności, sąsiadów w xdist, wątku albo zegara.
   Szukający oddaje w odpowiedzi listę kandydatów, każdy z oznaczeniem Ważne albo Drobne, tytułem, plik:linia, mechanizmem i poleceniem, które go odtworzy.
   W kolejnej rundzie szukasz sam według sekcji „Kolejne rundy”.
   Krok kończy się, gdy masz listę od każdego szukającego i połączyłeś kandydatów o tym samym mechanizmie w jednego.
3. Potwierdź każdego kandydata na Ważne osobnym agentem potwierdzającym (Opus, `run_in_background: false`, najwyżej 4 naraz w jednej wiadomości).
   Potwierdzający dostaje tytuł i opis PR, merge-base, SHA HEAD i jednego kandydata, odtwarza defekt powtarzalnym dowodem z sekcji „Dowody” (polecenie i jego wynik), powtarza to samo na merge-base i szuka w diffie innych wystąpień tej samej klasy błędu.
   Oddaje `POTWIERDZONE` z poleceniem, wynikiem i wystąpieniami klasy albo `ODRZUCONE` z powodem, także wtedy, gdy defekt jest już na merge-base, łapie go ruff, mypy, lint frontendu albo strażnik z tabeli `CODING_STANDARDS.md`, albo na jego linii stoi wyjątek z powodem, terminem i zgodą Maksa.
   Odrzucony kandydat odpada, a luka bez złego zachowania zostaje najwyżej Drobnym.
   Drobne wybierasz sam z kandydatów, najwyżej 3, najważniejsze.
   Każde potwierdzone znalezisko z oznaczeniem, plik:linia i dowodem od razu dopisz do pliku `runda-<k>.md` w katalogu werdyktu, żeby przerwany przegląd zostawił znaleziska.
   Krok kończy się, gdy każdy kandydat jest w pliku z dowodem albo odrzucony z powodem.
4. Skille z linii `SKILLE VERIFY` wykonaj według sekcji `What CI runs and what stays local` każdego z nich.
   Krok kończy się, gdy każdy skill skończył się bez FAIL albo jego FAIL jest w pliku jako Ważne.
5. Dopisz na górę pliku dwie linie z sekcji „Postać werdyktu”, a na koniec krótko, co sprawdzone i z jakim wynikiem.
   Krok kończy się, gdy liczby w drugiej linii zgadzają się ze znaleziskami w pliku.
6. Opublikuj werdykt: `.venv/bin/python tools/scal_pr.py <PR> --werdykt <plik>`.
   Narzędzie sprawdza obie linie i SHA HEAD, a gdy odmawia, popraw plik według jego komunikatu i uruchom je ponownie.
   Gdy HEAD PR zmienił się w trakcie, przejrzyj diff od przejrzanego SHA do nowego HEAD, zanim zmienisz SHA w pliku.
   Krok kończy się linią `WERDYKT OK` z adresem komentarza: oddaj wywołującemu ścieżkę pliku i tę linię.
