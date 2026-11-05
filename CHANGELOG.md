# Changelog

Versions follow [Semantic Versioning](https://semver.org/): a new feature raises the minor
number, a fix-only release the patch number. This file is the version's single source
(`primeatlas/core/version.py` reads it): the release is the newest `## X.Y.Z — date`
heading, and every merge into `main` after it appends one entry `### +N — title` to the
`## Since X.Y.Z` section, English first, then Polish. Entries are never edited; a
correction is a new entry. The app shows release, merge count and commit, e.g.
`1.2.0+24 (f59ce41)`, because Settings → Updates moves every copy along `main` between
releases. A release renames `## Since X.Y.Z` to `## A.B.C — date` and tags `vA.B.C`.

## Since 1.2.0

### +1 — Engine pt1: partial sieve + BPSW, separate D/P window stores (#6)

- English: New sieve engine pt1 for deep floors: each window is sieved only up to B
  (default N^1/4) and the survivors are proved by BPSW, so the fixed cost of generating
  every sieving prime up to sqrt(N) disappears. Its windows go to their own D/P stores.
- Polski: Nowy silnik sita pt1 dla głębokich pięter: każde okno jest przesiewane tylko do
  B (domyślnie N^1/4), a pozostałe liczby potwierdza test BPSW, więc znika stały koszt
  generowania wszystkich liczb pierwszych do sqrt(N). Jego okna trafiają do osobnych
  magazynów D/P.

### +2 — Close guard: save-point stop on close, Stop button, start-up recovery (#7)

- English: Closing the app during a Generation job no longer kills it mid-write: it asks
  the job to stop at its next save point, a Stop button does the same, and the next start
  settles a run that was cut off.
- Polski: Zamknięcie aplikacji w trakcie generowania nie przerywa już zapisu w połowie:
  zadanie zatrzymuje się w najbliższym punkcie zapisu, to samo robi przycisk Stop, a
  kolejne uruchomienie porządkuje przerwany przebieg.

### +3 — Benchmark charts: pin a y-axis bound from a point's menu (#8)

- English: Right-clicking a benchmark chart point sets its value as the max or min of
  that point's y-axis, with resets per axis and for the whole chart.
- Polski: Prawy klik na punkcie wykresu benchmarku ustawia jego wartość jako maksimum lub
  minimum osi Y tego punktu; są też resety dla każdej osi i całego wykresu.

### +4 — Polish locale: leftover English labels translated, diacritics restored (#9)

- English: The Polish UI no longer shows English column headers, and the WSL setup wizard
  has its Polish diacritics back.
- Polski: Polski interfejs nie pokazuje już angielskich nagłówków kolumn, a kreator
  konfiguracji WSL ma z powrotem polskie znaki.

### +5 — Benchmark PDF: logical tables, one-metric charts, no truncated cells (#10)

- English: The benchmark PDF splits the log into readable tables and draws one metric per
  chart; no cell is cut short. The Constellation records PDF no longer truncates cells.
- Polski: PDF benchmarku dzieli log na czytelne tabele i rysuje jedną miarę na wykres;
  żadna komórka nie jest ucinana. PDF rekordów konstelacji też nie ucina już komórek.

### +6 — GUI tests isolated from the real storage (#11)

- English: Every test that builds the app runs on its own temporary storage and never
  saves the user's settings.
- Polski: Każdy test budujący aplikację działa na własnym tymczasowym magazynie i nie
  zapisuje ustawień użytkownika.

### +7 — benchmark_log.csv header defined once (#12)

- English: All engine writers take the benchmark_log.csv header from one module,
  `prime_sieve/benchmark_log_schema.py`.
- Polski: Wszystkie silniki biorą nagłówek benchmark_log.csv z jednego modułu,
  `prime_sieve/benchmark_log_schema.py`.

### +8 — floor_meta.json rows written by one module (#13)

- English: The four drifted copies that append a row to a floor's floor_meta.json are
  replaced by `prime_sieve/floor_meta_store.py`; the Hybrid mode now writes it too.
- Polski: Cztery rozbieżne kopie dopisywania wiersza do floor_meta.json piętra zastępuje
  `prime_sieve/floor_meta_store.py`; tryb Hybrid też go teraz zapisuje.

### +9 — pt1 writes a slab while the next one is sieved (#14)

- English: pt1 overlaps writing slab k with sieving slab k+1: about 23 % less wall time on
  a 100,000-window floor-27 run.
- Polski: pt1 zapisuje porcję k w trakcie przesiewania porcji k+1: około 23 % krócej na
  przebiegu 100 000 okien na piętrze 27.

### +10 — Auto RAM budget as an adjustable field (#15)

- English: The share of free WSL RAM that Auto and Restore size v4.1/v5 runs against is a
  field (default 50 %), so a large host can run more windows per run.
- Polski: Udział wolnego RAM-u WSL, do którego Auto i Przywracanie dopasowują przebiegi
  v4.1/v5, jest polem (domyślnie 50 %), więc duży komputer może liczyć więcej okien na
  przebieg.

### +11 — generation_tab.py split into section modules (#16)

- English: The Generation tab's code is split by section; no change in behavior.
- Polski: Kod zakładki Generowanie podzielony na moduły według sekcji; bez zmian w
  działaniu.

### +12 — Generation backend split; constellation_finder_v2_1 (#17)

- English: The Generation backend is split into nine modules, and the GUI launches
  constellation_finder_v2_1, an unchanged copy of the frozen v2; no change in behavior.
- Polski: Zaplecze generowania podzielone na dziewięć modułów, a GUI uruchamia
  constellation_finder_v2_1, niezmienioną kopię zamrożonego v2; bez zmian w działaniu.

### +13 — Settings tab split into six modules (#18)

- English: The Settings tab's code is split by area; no change in behavior.
- Polski: Kod zakładki Ustawienia podzielony według obszarów; bez zmian w działaniu.

### +14 — Goldbach research tab split into three modules (#19)

- English: The Goldbach research tab's code is split by concern; no change in behavior.
- Polski: Kod zakładki badań Goldbacha podzielony według zadań; bez zmian w działaniu.

### +15 — Ring geometry split into six modules (#20)

- English: The Rings geometry code is split by topic; no change in behavior.
- Polski: Kod geometrii pierścieni podzielony według tematów; bez zmian w działaniu.

### +16 — Renderer split into four modules (#21)

- English: The visualization renderer is split by responsibility; no change in behavior.
- Polski: Renderer wizualizacji podzielony według odpowiedzialności; bez zmian w
  działaniu.

### +17 — Ring sound survives a Python switch (#22)

- English: sounddevice is listed in requirements.txt, so the start-up check offers it for
  whichever Python runs the app and the Rings sound keeps working.
- Polski: sounddevice jest w requirements.txt, więc kontrola przy starcie proponuje jego
  instalację dla Pythona, który uruchamia aplikację, i dźwięk pierścieni dalej działa.

### +18 — k-tuple sieve split: ktuple_sieve_v2_1 (#23)

- English: The k-tuple sieve is split into ktuple_sieve_v2_1 and three modules; the GUI
  launches it; the frozen v2 is kept; no change in behavior.
- Polski: Sito k-tupli podzielone na ktuple_sieve_v2_1 i trzy moduły; GUI je uruchamia;
  zamrożone v2 zostaje; bez zmian w działaniu.

### +19 — Constellation search split: constellation_finder_v2_2 (#24)

- English: The constellation search is split into constellation_finder_v2_2 and seven
  modules; the GUI launches it; no change in behavior.
- Polski: Szukanie konstelacji podzielone na constellation_finder_v2_2 i siedem modułów;
  GUI je uruchamia; bez zmian w działaniu.

### +20 — Main window split into primeatlas/app/ (#25)

- English: prime_atlas_v2.py is the entry point only; the main window lives in
  primeatlas/app/, one module per tab section; no change in behavior.
- Polski: prime_atlas_v2.py jest tylko punktem startowym; główne okno jest w
  primeatlas/app/, jeden moduł na sekcję zakładek; bez zmian w działaniu.

### +21 — Oversized test files split (#26)

- English: Five test files over 1000 lines are split by tested module, and a new test
  keeps every code file under the ceiling.
- Polski: Pięć plików testów ponad 1000 linii podzielonych według testowanego modułu, a
  nowy test pilnuje limitu dla każdego pliku kodu.

### +22 — constellation_finder_v2_3 + ktuple_sieve_v2_2: storage folder passed explicitly (#27)

- English: The constellation search and the k-tuple sieve take the storage folder as a
  parameter instead of a module global; the GUI launches the new versions; same output.
- Polski: Szukanie konstelacji i sito k-tupli dostają folder magazynu jako parametr zamiast
  zmiennej globalnej; GUI uruchamia nowe wersje; wynik ten sam.

### +23 — docs/design and docs/adr (#28)

- English: Design documentation (overview, data, flows, a page per module, generated
  parameter tables) and the architecture decision records.
- Polski: Dokumentacja projektu (przegląd, dane, przepływy, strona na moduł, generowane
  tabele parametrów) i zapisy decyzji architektonicznych.

### +24 — Version from CHANGELOG.md with a merge counter

- English: The app shows the release plus the number of merges since it (e.g. 1.2.0+24),
  and the About tab lists the changes since the last release in the UI language, with a
  link to the full CHANGELOG.md.
- Polski: Aplikacja pokazuje wydanie i liczbę zmian od niego (np. 1.2.0+24), a zakładka
  O programie wypisuje zmiany od ostatniego wydania w języku interfejsu, z linkiem do
  pełnego CHANGELOG.md.

### +25 — Time simulation window

- English: A "Time simulation" window on the Generation tab shows how the run width and the
  floor set the prep cost (sieving primes up to sqrt of the run's end), the speed and the
  total time, calibrated from your own benchmark_log.csv; its sliders fill the Quick
  generation Floor and Width fields.
- Polski: Okno „Symulacja czasu” w zakładce Generacja pokazuje, jak szerokość przebiegu
  i piętro wyznaczają koszt przygotowania (liczby pierwsze do pierwiastka z końca
  przebiegu), prędkość i łączny czas, na podstawie Twojego benchmark_log.csv; suwaki
  wypełniają pola Piętro i Szerokość Szybkiej generacji.

### +26 — Engine v6.0 (wheel-30 buffer) as default, engine v5.1, knob profiles and info tips

- English: New default engine v6.0 stores 30 numbers per byte instead of 16, so one run
  in the same RAM covers 1.875 times as many numbers and pays the per-run generation of
  the sieving primes less often; its windows are byte-identical to v5's. Engine v5 runs
  as v5.1 with measured defaults (2 MiB segments, 8 GiB buckets, longer runs): on floor
  25 a run of 2e11 numbers sieves 43 % faster. In the same RAM, v6.0 is about 2x v5.1 on
  floors 25-27. Each engine has its own knobs, now shown only for the selected engine and
  each with an "i" tip saying how it affects the run. A "Knob profile" list sets v5's or
  v6's knobs in one choice: Old, New (long runs), Intermediate (short runs), Custom, and
  Auto (default), which picks segment and bucket sizes by the run's window count, per
  engine (v6's short runs are fastest with 128 KiB segments). v6 writes its window files
  natively and with several threads (new field "v6 write threads", default 8): 1,000
  windows on a /mnt drive take 2.3 s instead of 29 s, and the console shows the write
  progress. The D-proves-P check after a run compares windows in parallel and updates its
  lists once per batch, with progress lines (60,000 windows: minutes instead of over an
  hour); its time is logged in the new benchmark column verify_seconds.
- Polski: Nowy domyślny silnik v6.0 zapisuje 30 liczb w bajcie zamiast 16, więc jedno
  uruchomienie w tym samym RAM obejmuje 1,875 razy więcej liczb i rzadziej płaci za
  generowanie liczb pierwszych situjących; jego okna są identyczne bajt w bajt z oknami
  v5. Silnik v5 działa jako v5.1 ze zmierzonymi ustawieniami domyślnymi (segmenty 2 MiB,
  kubełki 8 GiB, dłuższe uruchomienia): na piętrze 25 uruchomienie 2e11 liczb sitowało się
  o 43 % szybciej. W tym samym RAM v6.0 jest około 2x szybszy od v5.1 na piętrach 25-27.
  Każdy silnik ma własne pokrętła, widoczne teraz tylko dla wybranego silnika, każde z
  dymkiem „i” mówiącym, jak wpływa na generowanie. Lista „Profil pokręteł” ustawia
  pokrętła v5 lub v6 jednym wyborem: Stare, Nowe (długie przebiegi), Pośrednie (krótkie
  przebiegi), Własne oraz Auto (domyślnie), które dobiera segment i kubełki do liczby
  okien w przebiegu, osobno dla każdego silnika (krótkie przebiegi v6 są najszybsze z
  segmentami 128 KiB). v6 zapisuje pliki okien natywnie i kilkoma wątkami (nowe pole
  „Wątki zapisu v6”, domyślnie 8): 1000 okien na dysku /mnt zajmuje 2,3 s zamiast 29 s,
  a konsola pokazuje postęp zapisu. Sprawdzenie „D dowodzi P” po przebiegu porównuje okna
  równolegle i aktualizuje swoje listy raz na porcję, z liniami postępu (60 000 okien:
  minuty zamiast ponad godziny); jego czas trafia do nowej kolumny benchmarku
  verify_seconds.

### +27 — UI polish: ms/window, engine prime count, live time simulation, Floor spinboxes

- English: A fast run's console summary shows its time per window in milliseconds
  (3.00 ms/window instead of 0.00 s/window) and a run under a minute in tenths of a
  second. After a run that writes files, the prime count comes from the engine's own
  report instead of re-reading every window header, so a long run's summary no longer
  waits on thousands of file opens. The Time simulation window reloads the benchmark log
  when a run finishes while it is open. Every Quick-gen Floor field is a spinbox, and the
  mouse wheel over any enabled spinbox or drop-down list changes its value without
  scrolling the page.
- Polski: Podsumowanie szybkiego przebiegu w konsoli podaje czas na okno w milisekundach
  (3,00 ms/okno zamiast 0,00 s/okno), a przebieg krótszy niż minuta w dziesiątych
  częściach sekundy. Po przebiegu zapisującym pliki liczba liczb pierwszych pochodzi z
  raportu samego silnika, a nie z ponownego odczytu nagłówka każdego okna, więc
  podsumowanie długiego przebiegu nie czeka już na tysiące otwarć plików. Okno symulacji
  czasu wczytuje log benchmarku ponownie, gdy przebieg skończy się przy otwartym oknie.
  Każde pole Piętro w Szybkiej generacji jest polem ze strzałkami, a kółko myszy nad
  dowolnym aktywnym takim polem lub listą rozwijaną zmienia wartość bez przewijania
  strony.

### +28 — Atlas remembers its forms across restarts

- English: Form fields keep their last value when Atlas is closed and opened again:
  Quick-gen (every mode), the Generation pipeline, constellation and k-tuple forms (no
  Run needed any more), Research, Constellations, Primality, the primesieve calculator and
  the Benchmark chart options. One file per install (`ui_state.json`, next to
  `app_settings.json`) holds them, so switching the storage folder keeps the forms; the
  values the Generation forms kept per storage folder are carried over once. Fields that
  would act on their own at the next start stay empty: Quick-gen's starting point and the
  k-tuple "reset checkpoint" box start blank every time.
- Polski: Pola formularzy zachowują ostatnią wartość po zamknięciu i ponownym
  otwarciu Atlasa: Szybkie generowanie (wszystkie tryby), formularze potoku generowania,
  konstelacji i k-krotek (bez potrzeby klikania Uruchom), Badania, Konstelacje,
  Pierwszość, kalkulator primesieve i opcje wykresów Benchmarku. Trzyma je jeden plik na
  instalację (`ui_state.json`, obok `app_settings.json`), więc zmiana folderu magazynu nie
  zmienia formularzy; wartości, które formularze generowania trzymały dotąd w magazynie,
  są przenoszone raz. Pola, które przy następnym starcie zadziałałyby same, zostają
  puste: punkt startowy Szybkiego generowania i pole „reset checkpointu” k-krotek
  startują zawsze niezaznaczone.

### +29 — Time simulation: predicted RAM, width capped by the RAM budget

- English: The Time simulation window shows how much RAM the run will take, in GB and as
  a share of the RAM free in WSL. The width slider stops at the widest run that fits the
  RAM budget set in the pipeline form's advanced settings, and moves as soon as that
  budget or the bucket memory changes. An info tip next to the RAM line says where to
  change the budget, that 50 % is the recommended value, and what a higher one risks:
  swapping, the run killed for lack of memory, a system that stops responding. A width
  typed above the budget still runs, and the RAM line flags it.
- Polski: Okno symulacji czasu pokazuje, ile RAM zajmie uruchomienie, w GB i jako część
  wolnego RAM w WSL. Suwak szerokości zatrzymuje się na najszerszym uruchomieniu, które
  mieści się w budżecie RAM ustawionym w ustawieniach zaawansowanych formularza
  pipeline, i przesuwa się od razu po zmianie budżetu albo pamięci kubełków. Dymek przy
  linii RAM mówi, gdzie zmienić budżet, że zalecane jest 50 % i czym grozi wyższa
  wartość: swapowaniem, zabiciem uruchomienia z braku pamięci, zawieszeniem systemu.
  Szerokość wpisana powyżej budżetu nadal się uruchomi, a linia RAM to oznacza.

### +30 — Settings: WSL component versions, duplicate-copy warning

- English: Settings → Updates → WSL environment has a "Component versions" button. It
  reads from WSL the distribution, Python, numpy, gcc, and the versions of libprimesieve
  and libprimecount together with the file each one is loaded from. When a library is
  installed twice (for example the apt package next to a build under /usr/local), a
  warning lists every copy with its version and says which one PrimeAtlas loads; a
  second warning appears when the engines load a different copy than Python.
- Polski: Ustawienia → Aktualizacje → Środowisko WSL mają przycisk „Wersje
  komponentów”. Odczytuje z WSL dystrybucję, Pythona, numpy, gcc oraz wersje
  libprimesieve i libprimecount razem z plikiem, z którego każda jest ładowana. Gdy
  biblioteka jest zainstalowana dwa razy (np. pakiet apt obok buildu w /usr/local),
  ostrzeżenie wymienia każdą kopię z wersją i mówi, którą ładuje PrimeAtlas; drugie
  ostrzeżenie pojawia się, gdy silniki ładują inną kopię niż Python.

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
