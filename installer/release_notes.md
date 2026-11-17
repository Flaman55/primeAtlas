## English

**PrimeAtlas 1.5.0** — Generation sizes runs for the computer it runs on: a RAM check before every run, a running time and ETA, width and engine proposals, a target planner and a WSL RAM limit you can set from Atlas. New: Constellations → Density against the Hardy-Littlewood prediction, and two more Irreducibility sub-tabs, Primality and Multiplicative counting. Every number field reads any common notation.

PrimeAtlas is an application for generating, browsing and researching prime numbers: a prime and prime-constellation archive, research tabs (Goldbach, squares, polynomials, gaps, π(x) approximations, irreducibility) and GPU-rendered visualizations.

### What's new
- **Generation**
  - **RAM check on Generate:** a run predicted to need more RAM than the budget asks first, naming the predicted GB, the budget and the free RAM. The budget now also respects the RAM free in Windows, not only in WSL.
  - **Running time and ETA** in the status line, from the time model at launch, then from the run's measured pace.
  - **Proposals:** an engine proposal and a width proposal, each with a Use button; Auto proposes at most 10^11 numbers per v7 run (wider gains little speed), and in Explore re-splits iterations × width into fewer, wider runs.
  - **Target planner:** a list of numbers (each with an optional radius) split into the fastest set of Atlas and Pseudosquares runs; Use fills Quick-gen with a planned run.
  - **Pipeline form** grouped into four frames that fit a 13" Full HD screen at 150 %; a fresh install defaults to one instance, one batch, engine v7 and workers Max (every CPU WSL reports).
- **Constellations → Density:** hits of each k-tuple variant against the Hardy-Littlewood prediction over exactly the scanned spans, with the ratio, its deviation and a chart per floor.
- **Research → Irreducibility:** **Primality** decides whether a number is prime from its residues alone (theorem T6); **Multiplicative counting** shows the discrete logarithm and whether a number is a square modulo q (theorem T9). Each has a self-test of 1000 random cases.
- **Number fields:** all 195 read any common notation, typed or pasted ("1 000 000", "1,000,000", "10^25+3", "3×10^24", "1,5E+25"); an unusable or out-of-range value turns the field red, an ambiguous one ("3,000") offers both readings.
- **About → This computer:** Windows and WSL hardware, and the WSL RAM limit, with a row to change it (a proposal from the Windows RAM, a warning above it, a backup of `.wslconfig`, and a WSL restart only when no run is active).
- **Benchmark:** every run records its computer and the CPU load before and during it; the time model calibrates only from this computer's runs. BENCHMARK.md opens with a new engine series (v7.2, v7.4, pt1 against the Pseudosquares Prime Sieve).
- **Fix:** the bottom progress bar holds the progress a job reports.

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

**PrimeAtlas 1.5.0** — Generowanie dopasowuje przebiegi do komputera, na którym działa: sprawdzenie RAM-u przed każdym przebiegiem, czas trwania i ETA, propozycje szerokości i silnika, planer celów oraz limit RAM-u WSL ustawiany z Atlasu. Nowe: Konstelacje → Gęstość na tle przewidywania Hardy'ego-Littlewooda i dwie kolejne podzakładki Nieredukowalności, Pierwszość i Liczenie multiplikatywne. Każde pole liczbowe czyta dowolny popularny zapis.

PrimeAtlas to aplikacja do generowania, przeglądania i badania liczb pierwszych: magazyn liczb pierwszych i konstelacji, zakładki badawcze (Goldbach, kwadraty, wielomiany, luki, przybliżenia π(x), nieredukowalność) oraz wizualizacje renderowane na GPU.

### Co nowego
- **Generowanie**
  - **Sprawdzenie RAM-u przy Generuj:** przebieg, który według przewidywań potrzebuje więcej RAM-u niż budżet, najpierw pyta i podaje przewidywane GB, budżet i wolny RAM. Budżet uwzględnia teraz także RAM wolny w Windows, nie tylko w WSL.
  - **Czas trwania i ETA** w linii stanu, najpierw z modelu czasu, potem z rzeczywistego tempa przebiegu.
  - **Propozycje:** propozycja silnika i propozycja szerokości, każda z przyciskiem Użyj; Auto proponuje najwyżej 10^11 liczb na przebieg v7 (szerszy prawie nie przyspiesza), a w Eksploracji przelicza iteracje × szerokość na mniej, szerszych przebiegów.
  - **Planer celów:** lista liczb (każda z opcjonalnym promieniem) dzielona na najszybszy zestaw przebiegów Atlasa i Pseudosquares; Użyj wypełnia Quick-gen zaplanowanym przebiegiem.
  - **Formularz pipeline** w czterech ramkach, które mieszczą się na ekranie 13" Full HD przy 150 %; świeża instalacja zaczyna od jednej instancji, jednej partii, silnika v7 i workerów Max (wszystkie procesory widoczne w WSL).
- **Konstelacje → Gęstość:** trafienia każdego wariantu krotki na tle przewidywania Hardy'ego-Littlewooda, dokładnie na przeskanowanych odcinkach, ze stosunkiem, odchyleniem i wykresem dla każdego piętra.
- **Badania → Nieredukowalność:** **Pierwszość** rozstrzyga, czy liczba jest pierwsza, wyłącznie z jej reszt (twierdzenie T6); **Liczenie multiplikatywne** pokazuje logarytm dyskretny i czy liczba jest kwadratem modulo q (twierdzenie T9). Każda ma samotest na 1000 losowych przypadkach.
- **Pola liczbowe:** wszystkie 195 czytają dowolny popularny zapis, wpisany lub wklejony („1 000 000”, „1,000,000”, „10^25+3”, „3×10^24”, „1,5E+25”); nieużyteczna albo spoza zakresu wartość zabarwia pole na czerwono, niejednoznaczna („3,000”) proponuje oba odczyty.
- **O programie → Ten komputer:** sprzęt Windows i WSL oraz limit RAM-u WSL z wierszem do jego zmiany (propozycja z RAM-u Windows, ostrzeżenie powyżej niej, kopia `.wslconfig` i restart WSL tylko wtedy, gdy nie trwa żaden przebieg).
- **Benchmark:** każdy przebieg zapisuje swój komputer i obciążenie CPU przed nim i w trakcie; model czasu kalibruje się tylko z przebiegów tego komputera. BENCHMARK.md otwiera nowa seria silników (v7.2, v7.4, pt1 na tle Pseudosquares Prime Sieve).
- **Poprawka:** dolny pasek postępu trzyma postęp zgłoszony przez zadanie.

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
