---
name: przeglad
description: Przegląd PR w tym repozytorium, wspólny dla autora i recenzenta - co jest porażką (Ważne, Drobne), jakie dowody, postać werdyktu i kolejne rundy. Użyj przed pushem, żeby świeży agent przejrzał Twój diff (tryb autora), jako niezależny recenzent PR, zanim napiszesz i opublikujesz werdykt PASS albo FAIL (tryb recenzenta), i po werdykcie FAIL, zanim wypchniesz poprawki i odpowiesz na znaleziska (odpowiedź autora). Tryb podaje wywołujący.
---

# Przegląd PR

Ten skill ma wspólne reguły przeglądu i dwa tryby, które różnią się tylko krokami końcowymi: tryb autora przed pushem i tryb recenzenta, który publikuje werdykt na PR.
Po werdykcie `FAIL` autor odpowiada na każde znalezisko według sekcji „Odpowiedź autora na FAIL”.
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
Dalej znaleziska od najważniejszego, każde w linii, która zaczyna się od jego numeru: `W1: ` dla Ważnego i `D1: ` dla Drobnego, kolejno od 1 w swoim rodzaju, a po numerze plik:linia i dowód.
Na końcu krótko, co sprawdzone i z jakim wynikiem.

```markdown
WERDYKT: FAIL <pełny SHA HEAD>
Znaleziska: 2 (Ważne 1, Drobne 1)

- W1: tools/x.py:12 — <defekt>; dowód: <polecenie i wynik>
- D1: tools/x.py:30 — <luka>; dowód: <mutacja NIEWYKRYTA>
```

## Kolejne rundy

Runda po `FAIL` sprawdza diff od przejrzanego SHA do nowego HEAD i odpowiedź autora na każde znalezisko poprzedniej rundy (linie `ODPOWIEDŹ` z `--przeglad`).
Znalezisko `naprawione` jest zamknięte, gdy diff je naprawia, a `błędne`, `zamierzone` albo `bez znaczenia`, gdy powód wytrzymuje sprawdzenie; powód, który nie wytrzymuje, wraca jako znalezisko z dowodem przeciw niemu.
Zamkniętych znalezisk nie powtarza.
Nowe znalezisko w kodzie, którego ta runda nie zmieniła, jest Ważne tylko wtedy, gdy to defekt zachowania z dowodem.
Po trzeciej rundzie z `FAIL` koordynator nie zleca czwartej, tylko zmienia podejście albo dzieli PR.
Każdą rundę robi nowy recenzent, który nie pisał kodu, z linkiem do poprzednich werdyktów.

## Odpowiedź autora na FAIL

Autor rundy poprawek odpowiada na każde znalezisko ostatniego werdyktu `FAIL`, także Drobne, a `tools/scal_pr.py` nie scala PR, dopóki któreś nie ma odpowiedzi.

1. Dla każdego znaleziska ustal odpowiedź: `naprawione` (poprawka w commicie), `błędne` (dowód, że defektu nie ma), `zamierzone` (zachowanie, którego chce zadanie, z jego źródłem) albo `bez znaczenia` (dlaczego nie warto).
   Krok kończy się, gdy każde znalezisko ma odpowiedź z powodem, który sprawdzi następny recenzent.
2. Zacommituj poprawki, przejdź `.venv/bin/python tools/szybko.py` i wypchnij gałąź.
3. Opublikuj odpowiedź komentarzem na PR (`gh pr comment <PR> --body-file <plik>`) w postaci z `--help` narzędzia `tools/scal_pr.py`: pierwsza linia `ODPOWIEDŹ <pełny SHA z linii werdyktu FAIL>`, dalej linia na znalezisko.

   ```markdown
   ODPOWIEDŹ <pełny SHA z werdyktu FAIL>

   - W1: naprawione — test w <SHA poprawki> pada na starym kodzie
   - D1: bez znaczenia — <powód>
   ```

   Krok kończy się, gdy `.venv/bin/python tools/scal_pr.py <PR> --przeglad` nie pokazuje linii `ODPOWIEDŹ` zakończonej `brak`.
4. Zleć kolejną rundę przeglądu w trybie recenzenta.

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
   Drukuje pełny SHA HEAD, merge-base z bazą, `git diff --stat`, zmienione pliki, wynik `tools/skille_dla_zmiany.py` dla HEAD PR, poprzednie werdykty z ich SHA i dwiema pierwszymi liniami oraz w liniach `ODPOWIEDŹ` każde znalezisko ostatniego `FAIL` z odpowiedzią autora albo `brak`.
   Krok kończy się, gdy masz SHA HEAD i merge-base; poprzedni werdykt znaczy, że to kolejna runda (sekcja „Kolejne rundy”).
2. Przejrzyj diff według sekcji „Co jest porażką” i „Dowody”, a skille z linii `SKILLE VERIFY` wykonaj według sekcji `What CI runs and what stays local` każdego z nich.
   Każde potwierdzone znalezisko z numerem (`W1`, `D1`), plik:linia i dowodem od razu dopisz do pliku `runda-<k>.md` w katalogu werdyktu, żeby przerwany przegląd zostawił znaleziska.
   Krok kończy się, gdy przejrzałeś cały diff, a każde znalezisko jest w pliku.
3. Dopisz na górę pliku dwie linie z sekcji „Postać werdyktu”, a na koniec krótko, co sprawdzone i z jakim wynikiem.
   Krok kończy się, gdy liczby w drugiej linii zgadzają się ze znaleziskami w pliku.
4. Opublikuj werdykt: `.venv/bin/python tools/scal_pr.py <PR> --werdykt <plik>`.
   Narzędzie sprawdza obie linie i SHA HEAD, a gdy odmawia, popraw plik według jego komunikatu i uruchom je ponownie.
   Gdy HEAD PR zmienił się w trakcie, przejrzyj diff od przejrzanego SHA do nowego HEAD, zanim zmienisz SHA w pliku.
   Krok kończy się linią `WERDYKT OK` z adresem komentarza: oddaj wywołującemu ścieżkę pliku i tę linię.
