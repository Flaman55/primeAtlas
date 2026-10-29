## English

**PrimeAtlas 1.1.0** — a Visualization tab with three views, an About tab, readability settings and pages that scroll whenever their content does not fit.

PrimeAtlas is an application for generating, browsing and researching prime numbers: a prime and prime-constellation archive, research tabs (Goldbach, squares, polynomials, gaps, π(x) approximations) and GPU-rendered visualizations.

### What's new
- **Visualization tab** with three sub-tabs: Rings (moved here), Tree (a prime copy tree with a multiples axis, plus the Assembly animation mode) and Sphere (rings and fibers modes). When the storage is empty, they offer to generate a range.
- **About tab:** version and commit, author, license and third-party notices.
- **Settings → General → User interface:** background and text brightness per theme, text size for the whole app, and the scroll-area width.
- Every page gets a vertical scrollbar when its content does not fit the window, with a scroll strip next to it: the mouse wheel over the strip always scrolls the page.
- Striped tables, more readable hint text, tab highlight on hover; the Primes tree columns fit their content.
- Fixed: the ring visualization froze while scrubbing; installer checkboxes were cut off at 125% display scaling; installing sympy failed with WinError 448; mouse-wheel scrolling on Settings pages; constellation hits from windows scanned out of order were not stored.

The full list is in `CHANGELOG.md`. An existing installation gets this version from **Settings → Updates**; there is no need to reinstall.

### Installation
1. Download **PrimeAtlasSetup.exe** (below, under *Assets*) and run it. No administrator rights and no pre-installed Python or git are needed.
2. Windows may show *"Windows protected your PC"* because the installer is not digitally signed. Click **More info → Run anyway**.
3. Choose the install directory (default `%LOCALAPPDATA%\PrimeAtlas`; it must be empty or hold an earlier PrimeAtlas installation) and whether to create desktop and Start-menu shortcuts.

The installer carries its own Python 3.13 and git (it does not touch programs already installed on the computer), downloads PrimeAtlas from GitHub and installs the required packages (numpy, moderngl, glfw, Pillow). An internet connection is needed during installation.

### Good to know
- **Updates:** Settings → Updates checks for and downloads new versions from GitHub.
- **Generating data** requires WSL (Windows Subsystem for Linux). On first launch a wizard offers to set it up. Browsing existing data works without WSL.
- **Uninstalling** (Windows Settings → Apps) asks whether to delete the generated data; by default it keeps it.
- Requirements: Windows 10/11, 64-bit.

License: PolyForm Noncommercial 1.0.0 (noncommercial use). See `LICENSE.md` and `NOTICE.md`.

---

## Polski

**PrimeAtlas 1.1.0** — zakładka Wizualizacja z trzema widokami, zakładka O programie, ustawienia czytelności oraz strony, które przewijają się zawsze, gdy ich treść nie mieści się w oknie.

PrimeAtlas to aplikacja do generowania, przeglądania i badania liczb pierwszych: magazyn liczb pierwszych i konstelacji, zakładki badawcze (Goldbach, kwadraty, wielomiany, luki, przybliżenia π(x)) oraz wizualizacje renderowane na GPU.

### Co nowego
- **Zakładka Wizualizacja** z trzema podzakładkami: Pierścienie (przeniesione tutaj), Drzewo (drzewo kopii liczb pierwszych z osią wielokrotności oraz tryb animacji Składanie) i Sfera (tryby pierścieni i włókien). Gdy magazyn jest pusty, proponują wygenerowanie zakresu.
- **Zakładka O programie:** wersja i commit, autor, licencja i informacje o komponentach zewnętrznych.
- **Ustawienia → Ogólne → Interfejs użytkownika:** jasność tła i tekstu osobno dla każdego motywu, rozmiar tekstu w całej aplikacji oraz szerokość obszaru przewijania.
- Każda strona dostaje pionowy pasek przewijania, gdy jej treść nie mieści się w oknie, a obok niego obszar przewijania: kółko myszy nad nim zawsze przewija stronę.
- Tabele w paski, czytelniejsze podpowiedzi, podświetlanie zakładek po najechaniu; kolumny drzewa liczb pierwszych dopasowują się do zawartości.
- Poprawione: zawieszanie się wizualizacji pierścieni podczas przewijania; ucięte pola wyboru instalatora przy skalowaniu ekranu 125%; błąd WinError 448 przy instalacji sympy; przewijanie kółkiem myszy na stronach Ustawień; niezapisywane trafienia konstelacji z okien skanowanych poza kolejnością.

Pełna lista jest w pliku `CHANGELOG.md`. Istniejąca instalacja dostaje tę wersję przez **Ustawienia → Aktualizacje**; nie trzeba instalować ponownie.

### Instalacja
1. Pobierz **PrimeAtlasSetup.exe** (poniżej, w sekcji *Assets*) i uruchom go. Nie są potrzebne uprawnienia administratora ani wcześniej zainstalowany Python czy git.
2. Windows może pokazać ostrzeżenie *„System Windows ochronił ten komputer”*, bo instalator nie jest podpisany cyfrowo. Kliknij **Więcej informacji → Uruchom mimo to**.
3. Wybierz katalog instalacji (domyślnie `%LOCALAPPDATA%\PrimeAtlas`; musi być pusty albo zawierać wcześniejszą instalację PrimeAtlas) oraz czy utworzyć skróty na pulpicie i w menu Start.

Instalator zawiera własnego Pythona 3.13 i gita (nie ingeruje w programy już zainstalowane na komputerze), pobiera PrimeAtlas z GitHuba i instaluje potrzebne pakiety (numpy, moderngl, glfw, Pillow). Podczas instalacji wymagane jest połączenie z internetem.

### Warto wiedzieć
- **Aktualizacje:** Ustawienia → Aktualizacje sprawdza i pobiera nowe wersje z GitHuba.
- **Generowanie danych** wymaga WSL (Windows Subsystem for Linux). Przy pierwszym uruchomieniu kreator zaproponuje jego konfigurację. Samo przeglądanie danych działa bez WSL.
- **Deinstalacja** (Ustawienia systemu → Aplikacje) pyta, czy usunąć wygenerowane dane; domyślnie je zostawia.
- Wymagania: Windows 10/11, 64-bit.

Licencja: PolyForm Noncommercial 1.0.0 (użytek niekomercyjny). Zob. `LICENSE.md` i `NOTICE.md`.
