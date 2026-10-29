# Changelog

Versions follow [Semantic Versioning](https://semver.org/): a new feature raises the minor
number, a fix-only release the patch number. The number lives in
`primeatlas/core/version.py` (`APP_VERSION`); the app shows it with the checked-out commit,
e.g. `1.1.0 (f59ce41)`, because Settings → Updates moves every copy along `main` between
releases.

## 1.1.0 — unreleased

### English

**New**
- Visualization tab with three sub-tabs: Rings (moved here), Tree (a prime copy tree with a
  multiples axis, plus the Assembly animation mode) and Sphere (rings and fibers modes).
- About tab: version and commit, author, license and third-party notices.
- Settings → General → User interface: background and text brightness per theme, text size
  for the whole app, and the scroll-area width.
- A scroll strip next to every scrollable page's scrollbar: the mouse wheel over it always
  scrolls the page.
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
