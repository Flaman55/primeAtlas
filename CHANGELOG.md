# Changelog

Versions follow [Semantic Versioning](https://semver.org/): a new feature raises the minor
number, a fix-only release the patch number. The number lives in
`primeatlas/core/version.py` (`APP_VERSION`); the app shows it with the checked-out commit,
e.g. `1.1.0 (f59ce41)`, because Settings → Updates moves every copy along `main` between
releases.

## 1.2.0 — 2026-11-01

### English

**New**
- Sieve engine v5, now the default: the shared buffer holds odd numbers only (half the
  RAM), small primes sieve cache-sized segments, larger primes go through one
  multi-threaded bucketed pass. Its output is byte-identical to v4.1. On 10^10 numbers with
  24 workers it is 1.7–13× faster than v4.1 (floor 25: 121 s → 70 s); measurements and the
  cost model are in `BENCHMARK.md`.
- Generation tab: a "Sieve engine" selector (v4.1 / v5) and four v5 fields (segment size,
  bucket region, bucket memory, windows per run at floor 25). The Auto button sizes a run
  from the floor and the RAM free in WSL; v5 allows up to 100,000 windows per run.
- Benchmark charts: one line per engine, the whole run and the sieve phase on separate
  charts, reference points (PARI/GP, primesieve), a log scale, and a legend that shows or
  hides each line; the PDF export follows all of them.

**Other**
- `BENCHMARK.md` with the raw results and scripts under `benchmarks/`.
- An installation that already saved its Generation settings keeps the engine it stores;
  choose v5 once in the "Sieve engine" field. v4.1 stays available.

### Polski

**Nowe**
- Silnik sita v5, teraz domyślny: wspólny bufor przechowuje tylko liczby nieparzyste
  (połowa RAM-u), małe liczby pierwsze przesiewają segmenty o rozmiarze pamięci cache,
  większe przechodzą przez jeden wielowątkowy przebieg kubełkowy. Wynik jest identyczny co
  do bajta z v4.1. Na 10^10 liczbach przy 24 procesach jest 1,7–13× szybszy od v4.1
  (piętro 25: 121 s → 70 s); pomiary i model kosztów są w `BENCHMARK.md`.
- Zakładka Generowanie: wybór silnika sita (v4.1 / v5) i cztery pola v5 (rozmiar
  segmentu, region kubełków, pamięć kubełków, liczba okien na przebieg na piętrze 25).
  Przycisk Auto dobiera wielkość przebiegu do piętra i wolnej pamięci RAM w WSL; v5
  pozwala na 100 000 okien na przebieg.
- Wykresy benchmarku: osobna linia dla każdego silnika, cały przebieg i samo sito na
  osobnych wykresach, punkty odniesienia (PARI/GP, primesieve), skala logarytmiczna oraz
  legenda, która pokazuje i ukrywa każdą linię; eksport PDF uwzględnia je wszystkie.

**Inne**
- `BENCHMARK.md` z surowymi wynikami i skryptami w `benchmarks/`.
- Instalacja, która ma już zapisane ustawienia Generowania, zachowuje zapisany silnik;
  wybierz raz v5 w polu wyboru silnika. v4.1 pozostaje dostępny.

## 1.1.0 — 2026-10-29

### English

**New**
- Visualization tab with three sub-tabs: Rings (moved here), Tree (a prime copy tree with a
  multiples axis, plus the Assembly animation mode) and Sphere (rings and fibers modes).
- About tab: version and commit, author, license and third-party notices.
- Settings → General → User interface: background and text brightness per theme, text size
  for the whole app, and the scroll-area width.
- A scroll strip next to every scrollable page's scrollbar: the mouse wheel over it always
  scrolls the page.
- Every page gets a vertical scrollbar when its content does not fit the window (e.g. at a
  larger text size), and loses it again once it fits.
- Striped tables, more readable hint text, tab highlight on hover; the Storage preview stays
  hidden until a file is selected.
- The Primes tree columns fit their content and the tree pane keeps that width.
- The visualization tabs offer to generate a storage range when the storage is empty.

**Fixed**
- Ring visualization froze while scrubbing.
- Installer checkboxes were cut off at 125% display scaling.
- Installing sympy failed with WinError 448.
- Mouse-wheel scrolling on Settings pages.
- Constellation hits from windows scanned out of order were not stored.

**Other**
- One terminal and height-control pattern across the app.
- Pillow is required for visualization text.
- WSL installation guide (`INSTALL_WSL_PRIMEATLAS.md`).

### Polski

**Nowe**
- Zakładka Wizualizacja z trzema podzakładkami: Pierścienie (przeniesione tutaj), Drzewo
  (drzewo kopii liczb pierwszych z osią wielokrotności oraz tryb animacji Składanie) i Sfera
  (tryby pierścieni i włókien).
- Zakładka O programie: wersja i commit, autor, licencja i informacje o komponentach
  zewnętrznych.
- Ustawienia → Ogólne → Interfejs użytkownika: jasność tła i tekstu osobno dla każdego
  motywu, rozmiar tekstu w całej aplikacji oraz szerokość obszaru przewijania.
- Obszar przewijania obok paska przewijania każdej przewijanej strony: kółko myszy nad nim
  zawsze przewija stronę.
- Każda strona dostaje pionowy pasek przewijania, gdy jej treść nie mieści się w oknie
  (np. przy większym tekście), i traci go, gdy znów się mieści.
- Tabele w paski, czytelniejsze podpowiedzi, podświetlanie zakładek po najechaniu; podgląd
  w Magazynie pojawia się dopiero po wybraniu pliku.
- Kolumny drzewa liczb pierwszych dopasowują się do zawartości, a panel drzewa zachowuje
  tę szerokość.
- Zakładki wizualizacji proponują wygenerowanie zakresu, gdy magazyn jest pusty.

**Poprawione**
- Zawieszanie się wizualizacji pierścieni podczas przewijania.
- Ucięte pola wyboru instalatora przy skalowaniu ekranu 125%.
- Instalacja sympy kończyła się błędem WinError 448.
- Przewijanie kółkiem myszy na stronach Ustawień.
- Trafienia konstelacji z okien skanowanych poza kolejnością nie były zapisywane.

**Inne**
- Jeden wzorzec terminala i regulacji wysokości w całej aplikacji.
- Pillow jest wymagany do napisów w wizualizacjach.
- Przewodnik instalacji WSL (`INSTALL_WSL_PRIMEATLAS.md`).

## 1.0.0 — 2026-09-30

### English

The first release with a Windows installer (`PrimeAtlasSetup.exe`): its own Python 3.13 and
Git, a WSL setup wizard, updates from Settings → Updates. See the GitHub release notes for
installation steps.

### Polski

Pierwsze wydanie z instalatorem dla Windows (`PrimeAtlasSetup.exe`): własny Python 3.13
i Git, kreator konfiguracji WSL, aktualizacje z Ustawienia → Aktualizacje. Kroki instalacji
opisują informacje o wydaniu na GitHubie.
