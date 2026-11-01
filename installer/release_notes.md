## English

**PrimeAtlas 1.2.0** — sieve engine v5 becomes the default: byte-identical output, half the RAM for the sieve buffer, and 1.7–13× faster than v4.1 on 10^10 numbers with 24 workers.

PrimeAtlas is an application for generating, browsing and researching prime numbers: a prime and prime-constellation archive, research tabs (Goldbach, squares, polynomials, gaps, π(x) approximations) and GPU-rendered visualizations.

### What's new
- **Sieve engine v5 (default):** the shared buffer holds odd numbers only, small primes sieve cache-sized segments, larger primes go through one multi-threaded bucketed pass. Floor 25, 10^10 numbers, 24 workers: 121 s → 70 s. Measurements, the cost model and comparisons with primesieve and PARI/GP are in `BENCHMARK.md`.
- **Generation tab:** a *Sieve engine* selector (v4.1 / v5) and four v5 fields (segment size, bucket region, bucket memory, windows per run at floor 25). **Auto** sizes a run from the floor and the RAM free in WSL; v5 allows up to 100,000 windows per run.
- **Benchmark charts:** one line per engine, the whole run and the sieve phase on separate charts, reference points (PARI/GP, primesieve), a log scale, and a legend that shows or hides each line; the PDF export follows all of them.
- An installation that already saved its Generation settings keeps the engine it stores: choose **v5** once in the *Sieve engine* field. v4.1 stays available.

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

**PrimeAtlas 1.2.0** — silnik sita v5 staje się domyślny: wynik identyczny co do bajta, połowa RAM-u na bufor sita i 1,7–13× szybciej niż v4.1 na 10^10 liczbach przy 24 procesach.

PrimeAtlas to aplikacja do generowania, przeglądania i badania liczb pierwszych: magazyn liczb pierwszych i konstelacji, zakładki badawcze (Goldbach, kwadraty, wielomiany, luki, przybliżenia π(x)) oraz wizualizacje renderowane na GPU.

### Co nowego
- **Silnik sita v5 (domyślny):** wspólny bufor przechowuje tylko liczby nieparzyste, małe liczby pierwsze przesiewają segmenty o rozmiarze pamięci cache, większe przechodzą przez jeden wielowątkowy przebieg kubełkowy. Piętro 25, 10^10 liczb, 24 procesy: 121 s → 70 s. Pomiary, model kosztów i porównania z primesieve i PARI/GP są w `BENCHMARK.md`.
- **Zakładka Generowanie:** wybór *Silnik sita* (v4.1 / v5) i cztery pola v5 (rozmiar segmentu, region kubełków, pamięć kubełków, liczba okien na uruchomienie na piętrze 25). **Auto** dobiera wielkość przebiegu do piętra i wolnej pamięci RAM w WSL; v5 pozwala na 100 000 okien na uruchomienie.
- **Wykresy benchmarku:** osobna linia dla każdego silnika, cały przebieg i samo sito na osobnych wykresach, punkty odniesienia (PARI/GP, primesieve), skala logarytmiczna oraz legenda, która pokazuje i ukrywa każdą linię; eksport PDF uwzględnia je wszystkie.
- Instalacja, która ma już zapisane ustawienia Generowania, zachowuje zapisany silnik: wybierz raz **v5** w polu *Silnik sita*. v4.1 pozostaje dostępny.

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
