## English

**PrimeAtlas 1.3.0** — new sieve engines for deep floors (v6 wheel-30 default, v7 jump gear, pt1 partial sieve with BPSW or a pseudosquares proof), a time model that proposes the engine for a run, and a Benchmark tab rebuilt around filtering, exporting and comparing runs.

PrimeAtlas is an application for generating, browsing and researching prime numbers: a prime and prime-constellation archive, research tabs (Goldbach, squares, polynomials, gaps, π(x) approximations) and GPU-rendered visualizations.

### What's new
- **Engine v6 (default, code v6.1):** 30 numbers per byte instead of 16, so one run in the same RAM covers 1.875 times as many numbers; about 2× v5 on floors 25–27, with native multi-threaded window writing. Windows are byte-identical to v5's.
- **Engine v7 (code v7.4):** a jump gear finds only the large sieving primes whose multiples land in the run, so on deep floors that stage costs in proportion to the run's width. 10^10 numbers, 24 threads: floor 28 about 717 → 140 s, floor 29 about 2260 → 312 s. Same output as v6.1; the gear is used only where it is proven exact.
- **Engines pt1 / pt1.1 / pt1-pss:** each window is sieved only up to N^1/4; the survivors are decided by BPSW (P windows, probable) or by the pseudosquares proof (pt1-pss, proven, straight to the D store). P windows can be proven to D later, by the pt1.1 proof or by a v7.3 sieve (Generation → Verify P → D).
- **Engine proposal and Time simulation:** Quick generation and the Time simulation window estimate a run's time from your own benchmark log and propose an engine for the floor and width; a probable (BPSW) engine is proposed only with a clear margin and always with a warning. Nothing switches by itself.
- **Native comparisons:** primesieve and Kim Walisch's Pseudosquares Prime Sieve (up to 10^33) run as native programs and are timed side by side with the engines.
- **Benchmark tab:** runs without storage writes, a Filter window for the table and every chart, zoom, charts in their own windows, chosen line colors, independent hiding of axes, runs and lines, and export as PDF, CSV, SVG and an interactive HTML page.
- **Everyday use:** the app shows its version as the release plus the merges since it (e.g. 1.3.0+2) and lists the changes in About; forms keep their values across restarts; closing during a run stops it at the next save point.

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

**PrimeAtlas 1.3.0** — nowe silniki sita dla głębokich pięter (domyślny v6 z kołem 30, v7 z przekładnią skokową, pt1 z częściowym sitem i testem BPSW albo dowodem pseudokwadratów), model czasu, który proponuje silnik dla przebiegu, oraz zakładka Benchmark przebudowana wokół filtrowania, eksportu i porównywania przebiegów.

PrimeAtlas to aplikacja do generowania, przeglądania i badania liczb pierwszych: magazyn liczb pierwszych i konstelacji, zakładki badawcze (Goldbach, kwadraty, wielomiany, luki, przybliżenia π(x)) oraz wizualizacje renderowane na GPU.

### Co nowego
- **Silnik v6 (domyślny, kod v6.1):** 30 liczb na bajt zamiast 16, więc jeden przebieg w tej samej pamięci RAM obejmuje 1,875 razy więcej liczb; około 2× szybciej niż v5 na piętrach 25–27, z natywnym wielowątkowym zapisem okien. Okna są identyczne co do bajta z oknami v5.
- **Silnik v7 (kod v7.4):** przekładnia skokowa znajduje tylko te duże liczby pierwsze sita, których wielokrotności trafiają w przebieg, więc na głębokich piętrach ten etap kosztuje proporcjonalnie do szerokości przebiegu. 10^10 liczb, 24 wątki: piętro 28 około 717 → 140 s, piętro 29 około 2260 → 312 s. Wynik taki sam jak v6.1; przekładnia działa tylko tam, gdzie jej dokładność jest udowodniona.
- **Silniki pt1 / pt1.1 / pt1-pss:** każde okno jest przesiewane tylko do N^1/4; pozostałe liczby rozstrzyga test BPSW (okna P, prawdopodobne) albo dowód pseudokwadratów (pt1-pss, dowiedzione, prosto do magazynu D). Okna P można później dowieść do D dowodem pt1.1 albo sitem v7.3 (Generowanie → Weryfikacja P → D).
- **Propozycja silnika i Symulacja czasu:** Szybkie generowanie i okno Symulacji czasu szacują czas przebiegu z Twojego logu benchmarków i proponują silnik dla piętra i szerokości; silnik prawdopodobny (BPSW) jest proponowany tylko przy wyraźnej przewadze i zawsze z ostrzeżeniem. Nic nie przełącza się samo.
- **Porównania natywne:** primesieve i Pseudosquares Prime Sieve Kima Walischa (do 10^33) działają jako natywne programy i są mierzone obok silników.
- **Zakładka Benchmark:** przebiegi bez zapisu do magazynu, okno Filtr dla tabeli i wszystkich wykresów, powiększanie, wykresy w osobnych oknach, wybrane kolory linii, niezależne ukrywanie osi, przebiegów i linii oraz eksport do PDF, CSV, SVG i interaktywnej strony HTML.
- **Na co dzień:** aplikacja pokazuje wersję jako release plus liczbę mergów od niego (np. 1.3.0+2) i wypisuje zmiany w zakładce O programie; formularze zachowują wartości po ponownym uruchomieniu; zamknięcie w trakcie przebiegu zatrzymuje go w najbliższym punkcie zapisu.

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
