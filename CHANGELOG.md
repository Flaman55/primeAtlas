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

### +30 — Engine version in the benchmark log, time simulation calibrated per version

- English: Every benchmark_log.csv row now records the full engine version (for example
  v5.1 or v6.0) next to the engine name. The Time simulation calibrates each engine from
  the rows of its newest version once there are two of them, so a faster release is no
  longer averaged with the slower one, and the model note names that version. Older rows
  without a version still count until two new rows exist.
- Polski: Każdy wiersz benchmark_log.csv zapisuje teraz pełną wersję silnika (np. v5.1
  albo v6.0) obok nazwy silnika. Symulacja czasu kalibruje każdy silnik z wierszy jego
  najnowszej wersji, gdy są co najmniej dwa, więc szybsze wydanie nie jest już uśredniane
  z wolniejszym, a notka modelu podaje tę wersję. Starsze wiersze bez wersji liczą się,
  dopóki nie ma dwóch nowych.

### +31 — primesieve mode: native runs, honest labels, threads in every row

- English: primesieve mode gets a Native checkbox. With it, Atlas runs the primesieve
  program itself and times only its process: "count" sieves the range and counts the
  primes on the threads primesieve picks (shown on the sieve charts, the same work as an
  engine's sieve phase), "print" sieves and writes every prime as primesieve's own text
  into a primesieve folder next to Atlas storage (one thread, shown on the whole-run
  chart; Atlas does not read these files). Without it, the mode works as before and fills
  Atlas storage, but its time includes converting primesieve's result into Atlas windows,
  so the charts now call it "primesieve (Atlas format)" instead of primesieve. Every
  benchmark row records its sieve and write threads, and each chart line names its engine
  version and threads. The static primesieve reference points are gone: they came from a
  shorter range, where primesieve's fixed setup weighs more, and made a comparison look
  better than it is; measure primesieve natively at the same width instead (floor 19, same
  ranges: primesieve count 8.99 G numbers/s against v6.0's sieve phase 6.69 G/s, 24
  threads). The wrapper rows also log their sieve/write phases, bytes, range and peak RAM.
  Every chart point names the range it was measured on ("@ 10^11"), and a chart that sets
  points of different widths on one floor says so under it and in the PDF. A Filter window
  chooses the runs the charts compare by engine build, sieve threads, write threads and
  range width; the PDF follows it and names it. Its "Sieve measure" choice switches the
  sieve chart between the engine's own sieve phase (default), the sieve with startup
  overhead (timed by the orchestrator from launching the scanner process to the end of its
  sieve: Python start, imports, buffer allocation, library load; read once per run outside
  the engine, so it does not slow it; a new sieve_wall_seconds column) and that overhead
  alone (the numbers/s the startup takes, and that as % of the engine-phase speed), so
  both figures can be shown side by side. The Benchmark tab rereads the log when a
  generation run ends, so the new run shows without Refresh.
- Polski: Tryb primesieve dostaje checkbox Natywny. Z nim Atlas uruchamia sam program
  primesieve i mierzy tylko jego proces: "count" przesiewa zakres i liczy liczby pierwsze
  na tylu wątkach, ile dobierze primesieve (na wykresach sitowania, to ta sama praca co
  faza sita silnika), "print" przesiewa i zapisuje każdą liczbę pierwszą własnym tekstem
  primesieve do katalogu primesieve obok magazynu Atlasa (jeden wątek, na wykresie całego
  przebiegu; Atlas tych plików nie czyta). Bez niego tryb działa jak dotąd i wypełnia
  magazyn Atlasa, ale jego czas obejmuje przekształcenie wyniku primesieve w okna Atlasa,
  więc wykresy nazywają go teraz "primesieve (Atlas format)", a nie primesieve. Każdy
  wiersz benchmarku zapisuje wątki sita i zapisu, a każda linia wykresu podaje wersję
  silnika i wątki. Statyczne punkty odniesienia primesieve zniknęły: pochodziły z
  krótszego zakresu, na którym stały koszt startu primesieve waży więcej, i zawyżały
  porównanie; mierz primesieve natywnie przy tej samej szerokości (piętro 19, te same
  zakresy: primesieve count 8,99 G liczb/s wobec fazy sita v6.0 6,69 G/s, 24 wątki).
  Wiersze nakładki zapisują też fazy sita i zapisu, bajty, zakres i szczytowy RAM.
  Każdy punkt wykresu podaje zakres, na którym go zmierzono ("@ 10^11"), a wykres, który
  na jednym piętrze zestawia punkty różnej szerokości, mówi o tym pod spodem i w PDF.
  Okno Filtr wybiera przebiegi do porównania według wersji silnika, wątków sita, wątków
  zapisu i szerokości zakresu; PDF idzie za filtrem i go podaje. Jego wybór "Miara sita"
  przełącza wykres sita między własną fazą sita silnika (domyślnie), sitem z narzutem
  startowym (mierzonym przez orchestrator od uruchomienia procesu skanera do końca jego
  sita: start Pythona, importy, alokacja bufora, ładowanie biblioteki; odczyt raz na
  przebieg poza silnikiem, więc go nie spowalnia; nowa kolumna sieve_wall_seconds) i samym
  narzutem (liczby/s, które zabiera start, i to w % prędkości fazy sita), więc oba wyniki
  można pokazać obok siebie.
  Zakładka Benchmark wczytuje log ponownie po zakończeniu generowania, więc nowy przebieg
  widać bez klikania Odśwież.

### +32 — Benchmark: RAM per run chart

- English: The Benchmark tab's charts stand one under another: the sieve chart on top, the
  whole run below it, and a new third chart at the bottom: the peak RAM of each run in MB
  and the RAM per window, one line per engine build and thread setup, with
  the same legend toggles, log scale and pinned axes as the other charts. Native primesieve
  runs log the program's peak RAM but write no Atlas windows, so they show MB per run only.
  The Filter window's sieve measure now names the sieve chart instead of the lower chart.
  The page is taller than the default window and scrolls. The PDF report adds a page with
  the same two charts.
- Polski: Wykresy zakładki Benchmark stoją jeden pod drugim: na górze wykres sita, pod nim
  cały przebieg, a na dole nowy, trzeci wykres: szczytowy RAM każdego uruchomienia w MB
  i RAM na okno, jedna linia na wersję silnika i układ wątków, z tymi
  samymi przełącznikami legendy, skalą logarytmiczną i przypinaniem osi co pozostałe
  wykresy. Natywne przebiegi primesieve zapisują szczytowy RAM programu, ale nie zapisują
  okien Atlasa, więc mają tylko MB na uruchomienie. Miara sita w oknie Filtr wskazuje teraz
  wykres sita zamiast dolnego wykresu. Strona jest wyższa niż domyślne okno i się przewija.
  Raport PDF dostaje stronę z tymi samymi dwoma wykresami.

### +33 — Benchmark: export as CSV, SVG, HTML page and HTML snippet

- English: Next to "Save PDF", the Benchmark tab has an "Export" menu: CSV (the log's
  rows), SVG (the charts), an HTML page (charts and tables in one file to open in a
  browser) and an HTML snippet (the same content as one block to paste into another
  web page). Every export shows what the tab shows: the runs the Filter window keeps, the
  sieve measure, log scale, reference points, hidden lines and pinned axes, and the charts
  look like the PDF's; the HTML names the filter, the measure and the floors whose points
  differ in range width, as the PDF does.
- Polski: Obok „Zapisz PDF” zakładka Benchmark ma menu „Eksport”: CSV (wiersze logu),
  SVG (wykresy), strona HTML (wykresy i tabele w jednym pliku do otwarcia w
  przeglądarce) oraz fragment HTML (ta sama treść jako jeden blok do wklejenia na inną
  stronę). Każdy eksport pokazuje to, co zakładka: przebiegi, które zostawia okno Filtr,
  miarę sita, skalę logarytmiczną, punkty odniesienia, ukryte linie i przypięte osie,
  a wykresy wyglądają jak w PDF; HTML podaje filtr, miarę i piętra, na których punkty
  mają różną szerokość zakresu, tak jak PDF.

### +34 — Benchmark: zoom, charts in their own windows, interactive HTML

- English: The Benchmark charts zoom like a picture: unzoomed, a chart shows all of
  itself; the mouse wheel zooms into the part under the pointer, dragging with the left
  button moves over the chart, and a double click or a middle click shows the whole
  charts again. Lines run on to the edge, so a zoomed part between two floors shows the
  line passing through. All three charts follow the same floors, each zooms its own Y
  axis, and the exports draw what is in view. A tooltip lists every point drawn on the
  same spot, so a right-axis square on another line's circle can still be read.
  "Open in new window" above each chart shows it in a window of
  its own, which zooms, filters and toggles together with the tab. The exported HTML
  page and snippet are interactive: zoom and pan, legend entries that hide and show
  lines, the Filter window's dimensions, log scale, reference points and a chart text
  size, with the tables following the filter; the wheel zooms only over a chart, beside
  it the page scrolls; they open in the tab's view.
- Polski: Wykresy Benchmarku przybliża się jak obraz: bez zoomu wykres pokazuje się
  cały; kółko myszy przybliża fragment pod kursorem, przeciąganie lewym przyciskiem
  przesuwa po wykresie, a dwuklik lub środkowy klik znowu pokazuje całe wykresy. Linie
  biegną do krawędzi, więc przybliżony fragment między dwoma piętrami pokazuje
  przechodzącą przez niego linię. Wszystkie trzy wykresy pokazują te same piętra, każdy
  przybliża własną oś Y, a eksporty rysują to, co widać. Dymek pokazuje wszystkie
  punkty narysowane w jednym miejscu, więc kwadrat prawej osi leżący na kółku innej linii
  też da się odczytać. „Otwórz w nowym oknie” nad każdym wykresem pokazuje go
  w osobnym oknie, które przybliża się, filtruje i przełącza razem z zakładką.
  Eksportowana strona HTML i fragment HTML są interaktywne: przybliżanie i
  przesuwanie, wpisy legendy ukrywające i pokazujące linie, wymiary okna Filtr, skala
  logarytmiczna, punkty odniesienia i rozmiar tekstu wykresów, a tabele idą za filtrem;
  kółko przybliża tylko nad wykresem, obok niego przewija stronę; otwierają się w
  widoku zakładki.

### +35 — Engine v5.2: parallel window writer

- English: Engine v5 runs as v5.2: the same sieve as v5.1, but its windows are written
  by a pool of threads, the one v6 uses, set by the new "v5 write threads" field
  (default 8). On a /mnt drive, 1,000 windows at floor 19 now write in about 4.8 s
  instead of 25 s, and the whole run takes about 8 s instead of 29 s. The files are
  byte for byte the ones v5.1 writes; v5.1 stays in the tree for comparison.
- Polski: Silnik v5 działa jako v5.2: to samo sito co v5.1, ale okna zapisuje pula
  wątków, ta sama co w v6, ustawiana nowym polem „Wątki zapisu v5” (domyślnie 8). Na
  dysku /mnt 1000 okien na piętrze 19 zapisuje się teraz w około 4,8 s zamiast 25 s,
  a całe uruchomienie trwa około 8 s zamiast 29 s. Pliki są bajt w bajt takie, jakie
  zapisuje v5.1; v5.1 zostaje w drzewie do porównań.

### +36 — Settings: WSL component versions, duplicate-copy warning

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

### +37 — Engine v6.1: faster marking, same output

- English: The default engine v6 runs as v6.1. It finds exactly the same primes and writes
  byte for byte the same windows as v6.0, but marks the multiples of the small sieving primes
  a whole turn of the wheel at a time instead of one by one, and writes the bucket hits of the
  larger primes in full cache lines without first reading them from memory. Count-only on 24
  threads: floor 19, 10^11 numbers, the sieve takes 13.2-14.2 s instead of 15.4-18.5 s; floor
  25, 2*10^11 numbers, 134-141 s instead of 147-155 s. The gain shrinks with the floor: in
  full runs from the GUI v6.1 is faster on the low floors and practically equal to v6.0 from
  floor 26 up. v6.0 stays in the tree for comparison, and benchmark rows name the version,
  so the charts keep the two apart.
- Polski: Domyślny silnik v6 działa jako v6.1. Znajduje dokładnie te same liczby pierwsze i
  zapisuje bajt w bajt te same okna co v6.0, ale wielokrotności małych liczb pierwszych
  zaznacza całym obrotem koła naraz zamiast po jednej, a trafienia większych liczb pierwszych
  zapisuje do kubełków pełnymi liniami cache, bez wcześniejszego czytania ich z pamięci. Samo
  liczenie na 24 wątkach: piętro 19, 10^11 liczb, sito trwa 13,2-14,2 s zamiast 15,4-18,5 s;
  piętro 25, 2*10^11 liczb, 134-141 s zamiast 147-155 s. Zysk maleje z piętrem: w pełnych
  przebiegach z GUI v6.1 jest szybszy na niskich piętrach, a od piętra 26 praktycznie równy
  v6.0. v6.0 zostaje w drzewie do porównań, a wiersze benchmarku podają wersję, więc wykresy
  je rozdzielają.

### +38 — Engine v7: jump gear for the deep-floor sieving primes

- English: New engine v7 in the engine list (code v7.0), next to the default v6. It finds
  exactly the same primes and writes byte for byte the same windows as v6.1. On deep floors
  most sieving primes have no multiple in a run's numbers at all, yet v6 computes where each
  one would hit. v7's jump gear walks the large primes' range in blocks and finds only those
  whose multiple lands in the run, so that stage costs in proportion to the run's width, not
  to the number of primes below sqrt(N). Two new knobs: the jump threshold (where the gear
  takes over, 0 = off) and the jump block length. Count-only, 2*10^11 numbers, 24 threads,
  sieve time v6.1 -> v7: floor 26 330 -> 241 s, floor 27 927 -> 320 s, floor 28 3206 ->
  604 s (5.3 times faster); at that width the gear stays off at floor 25. With 1000
  windows (10^10 numbers) the gear is on from floor 25 and sieves about 2 times faster;
  a higher threshold gains more there (floor 28: 2514 -> 756 s at threshold 3000 %).
  Under the Auto knob profile (v5, v6, v7) the segment and bucket fields now show the
  values the next run gets, for the width edited last; before, they showed 2 MiB / 8 GiB
  whatever the width.
- Polski: Nowy silnik v7 na liście silników (kod v7.0), obok domyślnego v6. Znajduje
  dokładnie te same liczby pierwsze i zapisuje bajt w bajt te same okna co v6.1. Na
  głębokich piętrach większość liczb pierwszych situjących nie ma w liczbach uruchomienia
  żadnej wielokrotności, a v6 i tak liczy dla każdej, gdzie by trafiła. Bieg skokowy v7
  przechodzi zakres dużych liczb pierwszych blokami i znajduje tylko te, których
  wielokrotność wpada w uruchomienie, więc ten etap kosztuje proporcjonalnie do szerokości
  uruchomienia, a nie do liczby liczb pierwszych poniżej sqrt(N). Dwa nowe pokrętła: próg
  biegu skokowego (od którego miejsca bieg przejmuje pracę, 0 = wyłączony) i długość bloku.
  Samo zliczanie, 2*10^11 liczb, 24 wątki, czas sita v6.1 -> v7: piętro 26 330 -> 241 s,
  piętro 27 927 -> 320 s, piętro 28 3206 -> 604 s (5,3 raza szybciej); przy tej
  szerokości na piętrze 25 bieg jest wyłączony. Przy 1000 oknach (10^10 liczb) bieg działa
  od piętra 25 i sito jest około 2 razy szybsze; wyższy próg daje tam więcej (piętro 28:
  2514 -> 756 s przy progu 3000 %). Przy profilu pokręteł Auto (v5, v6, v7) pola segmentu
  i kubełków pokazują teraz wartości, które dostanie następny przebieg, dla ostatnio
  zmienionej szerokości; wcześniej pokazywały 2 MiB / 8 GiB niezależnie od szerokości.

### +39 — Benchmark runs: measure without writing into the storage

- English: A "Benchmark (no storage writes)" checkbox next to Generate replaces "Write PGS2
  files" and works in every generation mode. A benchmark run sieves and counts but leaves
  the storage as it was: no window files, no floor folder, no floor_meta.json entry; before,
  a count-only run still added its row to the floor's floor_meta.json. Its row in
  benchmark_log.csv carries the new run_purpose column (benchmark or storage; older
  count-only rows count as benchmark), and the Benchmark tab's Filter window has a Run
  purpose dimension: benchmark runs, storage runs or both. The Filter window now also
  decides which runs the tab's table lists (before, the table always showed the whole
  log); the charts and every export already followed it. Every value in the Filter window
  is clickable at once: a dimension starts at All, the first value clicked leaves only it,
  further clicks add or remove values, and All goes back to every run (before, a dimension
  had to be switched on first and then showed every value selected). The HTML page and
  snippet export only the runs the filter keeps (All exports the whole log; before, they held
  every run), and their own filter works the same way. A value an engine does not log
  (e.g. the per-window time of primesieve's count mode) shows a dash instead of an empty
  cell in the tab's table and the HTML and PDF tables; the CSV export keeps it empty. In the
  PDF, SVG and HTML charts the legend starts after a long chart title instead of over it
  (e.g. the Polish RAM chart).
- Polski: Checkbox „Benchmark (bez zapisu do magazynu)” obok przycisku Generuj zastępuje
  „Zapisuj pliki PGS2” i działa w każdym trybie generowania. Przebieg benchmarkowy
  przesiewa i liczy, ale zostawia magazyn bez zmian: bez plików okien, folderu piętra i
  wpisu w floor_meta.json; wcześniej przebieg samego zliczania dopisywał swój wiersz do
  floor_meta.json piętra. Jego wiersz w benchmark_log.csv ma nową kolumnę run_purpose
  (benchmark albo storage; starsze wiersze samego zliczania liczą się jako benchmark), a
  okno Filtr zakładki Benchmark ma wymiar Cel przebiegu: przebiegi benchmarkowe,
  magazynowe albo oba. Okno Filtr decyduje teraz także o tym, które przebiegi pokazuje
  tabela zakładki (wcześniej tabela zawsze pokazywała cały log); wykresy i każdy eksport
  już za nim szły. Każda wartość w oknie Filtr jest od razu klikalna: wymiar zaczyna od
  Wszystkie, pierwsza kliknięta wartość zostaje sama, kolejne kliknięcia dokładają albo
  usuwają wartości, a Wszystkie wraca do wszystkich przebiegów (wcześniej wymiar trzeba
  było najpierw włączyć, a potem pokazywał wszystkie wartości zaznaczone). Strona HTML i
  fragment HTML eksportują tylko przebiegi przepuszczone przez filtr (Wszystkie eksportuje
  cały log; wcześniej zawierały każdy przebieg), a ich własny filtr działa tak samo.
  Wartość, której silnik nie zapisuje (np. czas na okno w trybie zliczania primesieve),
  pokazuje kreskę zamiast pustej komórki w tabeli zakładki oraz w tabelach HTML i PDF;
  eksport CSV zostawia ją pustą. Na wykresach PDF, SVG i HTML legenda zaczyna się za długim
  tytułem wykresu zamiast na nim (np. polski wykres RAM).

### +40 — Pseudosquares mode: Kim Walisch's Pseudosquares Prime Sieve as a native engine

- English: Quick generation has a new Pseudosquares mode that runs Kim Walisch's
  Pseudosquares Prime Sieve program (BSD 2-Clause License) itself. The program outputs only
  proven primes and reaches 10^33 (floor 32), past primesieve's 2^64. count finds and counts
  the primes on Auto or a chosen number of threads and appears on the sieve charts; print
  writes every prime as text into pseudosquares/10pN/ on one thread and appears on the
  whole-run chart. Neither writes into the storage. Each row names the program's version and
  build commit, e.g. "Pseudosquares count (native) 1.2 (fccb96e), 24 thr". Settings → Updates
  builds the program inside WSL from a pinned commit of its GitHub repository (Install /
  Rebuild, which first installs cmake, g++ and git as root when they are missing). The setup
  wizard has an optional box for the same build. The component versions list shows the
  program and warns when its build is not the pinned one. Every native run (Pseudosquares and
  primesieve's Native mode, count and print) is a benchmark run: the Benchmark checkbox is
  shown checked and locked in those modes, and the Run purpose filter lists native print runs
  under Benchmark, older primesieve print rows included (before, they were listed under
  Storage although their text is not Atlas storage). Root commands run from Settings now log
  their whole output; before, the primecount install logged only its last step.
- Polski: Szybkie generowanie ma nowy tryb Pseudosquares, który uruchamia sam program
  Pseudosquares Prime Sieve Kima Walischa (licencja BSD 2-Clause). Program zwraca wyłącznie
  udowodnione liczby pierwsze i sięga 10^33 (piętro 32), dalej niż 2^64 primesieve. count
  znajduje i liczy liczby pierwsze na Auto albo na wybranej liczbie wątków i trafia na
  wykresy sita; print zapisuje każdą liczbę pierwszą jako tekst do pseudosquares/10pN/ na
  jednym wątku i trafia na wykres całego przebiegu. Żaden z nich nie zapisuje do magazynu.
  Każdy wiersz podaje wersję programu i commit kompilacji, np. „Pseudosquares count (native)
  1.2 (fccb96e), 24 thr”. Ustawienia → Aktualizacje budują program w WSL z przypiętego commita
  jego repozytorium na GitHubie (Zainstaluj / Przebuduj; brakujące cmake, g++ i git instaluje
  najpierw jako root). Kreator konfiguracji ma opcjonalne pole na tę samą kompilację. Lista
  wersji komponentów pokazuje program i ostrzega, gdy jego kompilacja nie jest przypiętą.
  Każdy przebieg natywny (Pseudosquares i tryb Native primesieve, count i print) jest
  przebiegiem benchmarkowym: w tych trybach checkbox Benchmark jest zaznaczony i zablokowany,
  a filtr Cel przebiegu pokazuje natywne przebiegi print w Benchmarku, także starsze wiersze
  print primesieve (wcześniej trafiały do Magazynu, choć ich tekst nie jest magazynem
  Atlasa). Polecenia roota uruchamiane z Ustawień zapisują teraz w logu całe swoje wyjście; wcześniej
  instalacja primecount zapisywała tylko ostatni krok.

### +41 — Engine v7.1: jump threshold from a cost model, progress by estimated cost

- English: The v7 engine now runs code v7.1. Where the jump gear takes over the large sieving
  primes is computed from a cost model of the run's floor and width,
  p* = ln p* * (a * sqrt(first / span) + b * span): the gear's block setups (which dominate on
  narrow runs and deep floors) next to its landings (which dominate on wide runs). v7.0 knew
  only the second term, so on narrow runs its default threshold was far too low. The knob
  "v7 jump threshold (% of model)" replaces "v7 jump threshold (%)" (100 = the model, 0 =
  off), and the model's a and b are knobs of their own (defaults 300 and 10 %, fitted to v7.0's
  measured best thresholds at floors 26-28). The progress percent and ETA of a v7 run follow
  the estimated cost of the finished work instead of the number of finished pieces, the
  console shows each sieve stage's time, and the shared progress bar follows the printed
  percent. The threshold no longer needs tuning to the run's width: at the defaults v7.1
  sieves 1e10 numbers at floor 28 in 717 s (v7.0: 1178 s at its default, 756 s at the best
  hand-picked threshold) and 2e11 numbers at floor 27 in 235 s (v7.0: 268 s). v7.0 stays in
  the repository for comparison. Output is unchanged.
- Polski: Silnik v7 uruchamia teraz kod v7.1. Miejsce, od którego bieg skokowy przejmuje duże
  liczby pierwsze situjące, wynika z modelu kosztu dla piętra i szerokości uruchomienia,
  p* = ln p* * (a * sqrt(first / span) + b * span): przygotowania bloków biegu (przeważają przy
  wąskich uruchomieniach i na głębokich piętrach) obok jego trafień (przeważają przy szerokich
  uruchomieniach). v7.0 znał tylko drugi człon, więc przy wąskich uruchomieniach jego domyślny
  próg był o wiele za niski. Pokrętło „Próg biegu skokowego v7 (% modelu)” zastępuje „Próg
  biegu skokowego v7 (%)” (100 = model, 0 = wyłączony), a a i b modelu mają własne pokrętła
  (domyślnie 300 i 10 %, dopasowane do najlepszych progów zmierzonych dla v7.0 na piętrach
  26-28). Procent postępu i ETA uruchomienia v7 idą za szacowanym kosztem wykonanej pracy
  zamiast za liczbą skończonych kawałków, konsola pokazuje czas każdego etapu sita, a wspólny
  pasek postępu idzie za wypisanym procentem. Progu nie trzeba już dobierać do szerokości
  uruchomienia: przy ustawieniach domyślnych v7.1 przesiewa 1e10 liczb na piętrze 28 w 717 s
  (v7.0: 1178 s przy domyślnym progu, 756 s przy najlepszym progu dobranym ręcznie), a 2e11
  liczb na piętrze 27 w 235 s (v7.0: 268 s). v7.0 zostaje w repozytorium do porównań. Wynik
  się nie zmienia.

### +42 — Benchmark charts: width on the x axis, point choice, floor filter

- English: The Filter window of the Benchmark tab sets the charts' x axis: the floor, as before,
  or the width of the run (numbers sieved, log scale), where each engine build, thread setup and
  floor is a line of its own ("v7.1, 24 thr @ f28") and the floors of one engine are shades of
  its color. So the same engine compares over width floor by floor: select floors 27, 28 and 29
  and every engine measured there shows three lines. A new filter dimension "Floor" picks the
  floors. Each chart (whole run, sieve, RAM) chooses which run stands for several runs on the
  same line and x: the last (default), the lowest or the highest value, the run selected in
  the table below, or all of them as separate points (repeated runs one above the other, the
  spread of the measurements). Clicking a run in the table switches all three charts to it and
  rings its points; up/down in the table move between runs and left/right turn the page. Changing the axis shows the whole charts; runs
  without a known width are left out of the width axis and counted under the chart. The PDF,
  SVG and HTML exports follow the axis and the choices, and the interactive HTML page has its own
  x-axis and point selectors.
- Polski: Okno Filtr zakładki Benchmark ustawia oś X wykresów: piętro, jak dotąd, albo szerokość
  przebiegu (przesiane liczby, skala logarytmiczna), na której każda wersja silnika, ustawienie
  wątków i piętro to osobna linia („v7.1, 24 thr @ f28”), a piętra jednego silnika to odcienie
  jego koloru. Ten sam silnik porównuje się więc po szerokości piętro po piętrze: zaznacz piętra
  27, 28 i 29, a każdy silnik zmierzony na nich pokaże trzy linie. Nowy wymiar filtra „Piętro”
  wybiera piętra. Każdy wykres (cały przebieg, sito, RAM) wybiera, który przebieg reprezentuje
  kilka przebiegów na tej samej linii i x: ostatni (domyślnie), o najniższej albo najwyższej
  wartości, przebieg zaznaczony w tabeli poniżej albo wszystkie jako osobne punkty (powtórzone
  przebiegi jeden nad drugim, czyli rozrzut pomiarów). Kliknięcie przebiegu w tabeli przełącza na
  niego wszystkie trzy wykresy i obwodzi jego punkty; strzałki góra/dół w tabeli przechodzą
  między przebiegami, a lewo/prawo zmieniają stronę. Zmiana osi pokazuje całe wykresy; przebiegi bez znanej szerokości nie trafiają
  na oś szerokości, a ich liczba jest podana pod wykresem. Eksport PDF, SVG i HTML idzie za osią
  i wyborami, a interaktywna strona HTML ma własny wybór osi X i punktu.

### +43 — About: copy the version, commit shown in worktrees

- English: The About tab has a copy icon next to the version line, which puts the line
  ("Version 1.2.0+43 (abcdef1)") on the clipboard for bug reports. The commit in the version
  label and the title bar is now shown also when the app runs from a linked git worktree,
  whose branch refs live in the main repository's git directory.
- Polski: Zakładka O programie ma ikonkę kopiowania obok wiersza wersji, która kładzie ten wiersz
  („Wersja 1.2.0+43 (abcdef1)”) do schowka, np. do zgłoszenia błędu. Commit w etykiecie wersji
  i na pasku tytułu jest teraz widoczny także wtedy, gdy aplikacja działa z dołączonego
  worktree gita, którego gałęzie są zapisane w katalogu git głównego repozytorium.

### +44 — Benchmark-mode measurements kept through integration, restore and full backup

- English: Benchmark-mode rows (runs that only measure, every native primesieve and
  Pseudosquares run) live only in benchmark_log.csv, not in a floor's floor_meta.json, so
  three paths used to lose them. Integrating an external storage now appends that storage's
  benchmark rows of each integrated floor to the local log. Restoring a backup puts the
  backup's log back but keeps the newer benchmark rows it lacks (the Restore log says how
  many). A full-data backup keeps the floor's benchmark rows next to its files and restoring
  the floor brings them back. Rows are matched by their key, so nothing is added twice.
- Polski: Wiersze trybu benchmark (przebiegi, które tylko mierzą, oraz każdy natywny przebieg
  primesieve i Pseudosquares) są tylko w benchmark_log.csv, nie w floor_meta.json piętra,
  więc trzy ścieżki je gubiły. Integracja zewnętrznego magazynu dopisuje teraz do lokalnego
  logu jego wiersze benchmarków z każdego integrowanego piętra. Przywrócenie backupu wstawia
  log z backupu, ale zachowuje nowsze wiersze benchmarków, których backup nie ma (dziennik
  przywracania podaje ich liczbę). Pełny backup piętra przechowuje wiersze benchmarków obok
  plików, a przywrócenie piętra je oddaje. Wiersze są porównywane po kluczu, więc nic nie
  dochodzi dwa razy.

### +45 — Engine v7.2: jump gear blocks sized by the cost model

- English: The v7 engine now runs code v7.2. The jump gear's block length is no longer fixed:
  the cost model picks the length that balances block setups against landing candidates for
  the run's floor and width (longer blocks on narrow runs and deep floors), and each block is
  set up about a third faster. The threshold where the gear takes over follows the cheaper
  gear. The output is the same as before. Measured on runs of 1e10 numbers (count only, 24
  threads): floor 25 about 33 -> 18 s, floor 26 95 -> 32 s, floor 27 253 -> 65 s, floor 28
  717 -> 140 s, floor 29 about 2260 -> 312 s; 2e11 numbers at floor 28 446 -> 312 s. The field
  "v7 jump block (%)" becomes "v7 jump block (% of model)" (default 100); v7.1 stays in the
  repository for comparison.
- Polski: Silnik v7 działa teraz na kodzie v7.2. Długość bloku biegu skokowego nie jest już
  stała: model kosztu dobiera ją tak, by zrównoważyć przygotowania bloków i kandydatów
  lądowania dla piętra i szerokości przebiegu (dłuższe bloki przy wąskich przebiegach
  i głębokich piętrach), a każdy blok przygotowuje się o około jedną trzecią szybciej. Próg,
  od którego działa bieg skokowy, idzie za tańszym biegiem. Wynik jest taki sam jak wcześniej.
  Zmierzone na przebiegach 1e10 liczb (tylko liczenie, 24 wątki): piętro 25 około 33 -> 18 s,
  piętro 26 95 -> 32 s, piętro 27 253 -> 65 s, piętro 28 717 -> 140 s, piętro 29 około
  2260 -> 312 s; 2e11 liczb na piętrze 28 446 -> 312 s. Pole „Blok biegu skokowego v7 (%)”
  staje się „Blok biegu skokowego v7 (% modelu)” (domyślnie 100); v7.1 zostaje w repozytorium
  do porównań.

### +46 — Engine pt1.1: P windows proven to D, right after sieving or later

- English: pt1 now runs code pt1.1 and can turn its P windows (BPSW, from 3.3e24) into proven
  D windows. The new pt1 checkbox "Verify P -> D after sieving" proves each P window right
  after its sieve: the window is sieved again and every survivor is decided by the
  pseudosquares test, a proof below about 1.8e34. A window whose proven primes equal the BPSW
  ones is stored as D/P; a different one stays P and is listed in DP_MISMATCH.txt. Unticked,
  pt1 writes P at full speed and the new Generation section "Verify P -> D" proves a floor's
  P windows later: floor and window width (a power of ten) step with the mouse wheel, the
  window count is read from the store (all by default, fewer proves only the first ones), and
  threads are Auto (the pipeline's workers), Max or a number. The run log shows the sieve alone, the proof and how much the speed drops
  (floor 29, 1e8 numbers, 24 threads: sieve 0.9 s, proof 8 s); the Benchmark charts draw such
  a run twice, "pt1.1 P" (sieve) and "pt1.1 D proof" (sieve + proof), and the store
  verification's own rows stay in the table only.
- Polski: pt1 działa teraz na kodzie pt1.1 i potrafi zamienić swoje okna P (BPSW, od
  3,3e24) w udowodnione okna D. Nowe pole pt1 „Weryfikuj P -> D po sitowaniu” dowodzi
  każdego okna P zaraz po jego sitowaniu: okno jest przesiewane ponownie, a każda ocalała
  liczba rozstrzygana testem pseudokwadratów, który jest dowodem poniżej około 1,8e34. Okno,
  którego udowodnione liczby pierwsze są równe tym z BPSW, trafia do magazynu jako D/P; inne
  zostaje P i jest wpisane do DP_MISMATCH.txt. Bez zaznaczenia pt1 zapisuje P z pełną
  prędkością, a nowa sekcja Generowania „Weryfikacja P -> D” dowodzi okien P piętra później:
  piętro i szerokość okna (potęga dziesięciu) zmienia się kółkiem myszy, liczba okien jest
  odczytywana z magazynu (domyślnie wszystkie, mniej dowodzi tylko pierwszych), a wątki to
  Auto (workers potoku), Max albo liczba.
  Log pokazuje samo sitowanie, dowód i o ile spada prędkość (piętro 29, 1e8 liczb, 24 wątki:
  sito 0,9 s, dowód 8 s); wykresy Benchmarku rysują takie uruchomienie dwa razy, „pt1.1 P”
  (sito) i „pt1.1 D proof” (sito + dowód), a wiersze weryfikacji magazynu zostają tylko
  w tabeli.

### +47 — Benchmark legend: line colors of your choice, shorter native names

- English: A right-click on a Benchmark legend entry sets the color of that engine's lines
  (every chart and the chart windows follow it, remembered between sessions, per theme) or
  brings back one default or all of them. Each theme has its own default palette, an
  engine keeping its hue in both, every color readable on its own background; the exports
  have a white background and use the light theme's colors. Colors that were too dark on
  the dark theme are brighter (Pseudosquares count, primesieve count, v6). Native lines have shorter
  names, "PSS count", "PSS print", "primesieve count", "primesieve print" and "primesieve
  Atlas", without the build commit (still in the table), so a legend entry takes one slot,
  e.g. "PSS count 1.2, 24 thr".
- Polski: Prawy klik na wpisie legendy Benchmarku ustawia kolor linii tego silnika
  (stosują go wszystkie wykresy i okna wykresów, zapamiętany między sesjami, osobno dla
  każdego motywu) albo przywraca jeden domyślny kolor lub wszystkie. Każdy motyw ma własną
  domyślną paletę, silnik zachowuje w obu swój odcień, a każdy kolor jest czytelny na swoim
  tle; eksporty mają białe tło i używają kolorów jasnego motywu. Kolory za ciemne
  w ciemnym motywie są jaśniejsze (Pseudosquares count, primesieve count, v6). Linie
  natywne mają krótsze nazwy, „PSS count”, „PSS print”, „primesieve count”, „primesieve
  print” i „primesieve Atlas”, bez commita kompilacji (nadal w tabeli), więc wpis legendy
  zajmuje jedno miejsce, np. „PSS count 1.2, 24 thr”.

### +48 — Pseudosquares up to floor 33, Delete benchmarks, pi(L) notice

- English: Quick-gen's Pseudosquares mode reaches the program's own stop, 1.73·10^33
  (its code's bound; its help rounds it to 10^33), so floor 33 runs up to there; a From
  past it is refused. Settings → Backup has "Delete benchmarks": it clears every row of
  benchmark_log.csv (its header stays) and leaves the floors, primes and constellations
  alone; the Benchmark tab reloads. Counting pi(L) (both pi checkboxes, still off by
  default) now shows a notice before a run that counts it from zero on its floor (the
  floor's first count, or a run below the floor's cached L), with the estimated extra time
  and [Enable] / [Leave disabled]: only that run's total time holds the count, later runs on
  the floor reuse it. With the count off, or on a floor that has its count, nothing changes.
- Polski: Tryb Pseudosquares w Quick-gen sięga własnej granicy programu, 1,73·10^33
  (granica z jego kodu; pomoc zaokrągla ją do 10^33), więc piętro 33 działa do tego
  miejsca; Od powyżej niej jest odrzucane. Ustawienia → Backup ma „Usuń
  benchmarki”: usuwa wszystkie wiersze benchmark_log.csv (nagłówek zostaje), a piętra,
  liczby pierwsze i konstelacje zostawia; zakładka Benchmark odświeża się. Liczenie
  π(L) (oba pola π, nadal domyślnie wyłączone) pokazuje teraz komunikat przed
  przebiegiem, który liczy je na swoim piętrze od zera (pierwsze liczenie na piętrze albo
  przebieg poniżej zapamiętanego L piętra), z szacowanym dodatkowym czasem i przyciskami
  [Włącz] / [Zostaw wyłączone]: tylko czas całkowity tego przebiegu zawiera liczenie,
  kolejne przebiegi na piętrze korzystają z wyniku. Przy wyłączonym liczeniu albo na
  piętrze, które ma już π, nic się nie zmienia.

### +49 — Benchmark run table: fewer columns, speeds first

- English: The Benchmark tab's run table, its CSV export and the HTML and PDF report tables
  show one set of 20 columns (the reports add floor and run) instead of the log's 30-odd
  raw ones, the most used first: engine, sieve n/s and run n/s (the values the charts draw,
  missing from the table until now), time, s/window, numbers, windows; then purpose,
  status, threads; the phases; the results. Columns that repeated another under a different
  name or were a quotient of two (write_files and run_purpose, the instance and session
  times, the window range, primes per window and per second, bytes written) are merged or
  left out, and so is base_gen_seconds (hundredths of a second). A native count, which
  writes no window, shows its range as its windows and time / windows as s/window instead
  of 0 windows and none. Headers are translated. benchmark_log.csv itself keeps every
  column. The Filter window scrolls once its choices do not fit, keeps Clear and Close in
  view at any height and opens within the screen.
- Polski: Tabela przebiegów w zakładce Benchmark, jej eksport CSV oraz tabele raportu HTML
  i PDF pokazują jeden zestaw 20 kolumn (raporty dodają piętro i przebieg) zamiast ponad 30
  surowych kolumn logu, od najważniejszych: silnik, n/s sita i n/s przebiegu (wartości z
  wykresów, których dotąd w tabeli nie było), czas, s/okno, liczby, okna; potem cel,
  status, wątki; fazy; wyniki. Kolumny powtarzające inną pod inną nazwą albo będące
  ilorazem dwóch innych (write_files i run_purpose, czasy instancji i sesji, zakres okien,
  liczby pierwsze na okno i na sekundę, zapisane bajty) są scalone albo pominięte, podobnie
  base_gen_seconds (setne części sekundy). Natywny licznik, który nie zapisuje okien,
  pokazuje jako okna swój zakres, a jako s/okno czas / okna, zamiast 0 okien i braku
  wartości. Nagłówki są przetłumaczone. Sam benchmark_log.csv zachowuje wszystkie kolumny.
  Okno Filtra przewija się, gdy wybory się nie mieszczą, przyciski Wyczyść i Zamknij są
  widoczne przy każdej wysokości, a okno otwiera się w granicach ekranu.

### +50 — Benchmark: selected row at the top, point and axis menus, view kept

- English: Selecting a run or a floor in the Benchmark tab's table scrolls it to the top of
  the table, directly under the column headings, so its cells line up with the headings;
  the rest of the table still scrolls up and down. The last rows get there too: blank space
  below the last row lets them reach the top. A right-click in the table clears the
  selected run and the charts go back to the point choice they had before it (last, min,
  max or all); a chart's right-click menu now sets that chart's point choice too, without
  the Filter window, and hides or shows all its left-axis (circles) or right-axis
  (squares) lines in one click. The filter, the sieve measure, the x axis, the point
  choices and the hidden lines are kept across restarts.
- Polski: Zaznaczenie przebiegu albo piętra w tabeli zakładki Benchmark przewija go na górę
  tabeli, tuż pod nagłówki kolumn, więc jego komórki stoją przy nagłówkach; resztę tabeli
  nadal można przewijać w górę i w dół. Ostatnie wiersze też tam trafiają: puste miejsce pod
  ostatnim wierszem pozwala im dojść na górę. Prawy klik w tabeli odznacza przebieg, a
  wykresy wracają do wyboru punktu sprzed zaznaczenia (ostatni, min, max albo wszystkie);
  menu prawego kliku na wykresie ustawia teraz także wybór punktu tego wykresu, bez okna
  Filtra, oraz jednym kliknięciem ukrywa lub pokazuje wszystkie jego linie lewej osi
  (kółka) albo prawej osi (kwadraty). Filtr, miara sita, oś X, wybór punktów i ukryte
  linie są zapamiętywane do następnego uruchomienia.

### +51 — Verify P -> D by a v7.3 sieve, also after a pt1 run

- English: Section D of the Generation tab gets a Method field: the pt1.1 proof as before,
  or the new v7.3 sieve, which sieves the adjacent P windows completely with engine v7.2 in
  passes of up to 10^Pass numbers (default 10^11, about 3.3 GB of RAM) and moves the equal
  ones to the D store as D/P. A v7.2 pass takes a near fixed time per floor whatever its
  width, so on wide ranges the sieve is much faster than the proof (floor 29: about 15x at
  10^11 numbers). Next to the method, an estimate of both methods' time for the chosen
  windows, from the benchmark log. Store verification rows (pt1_verify, v73_verify) no
  longer show "write ?" next to their threads: they write no windows.
  pt1's checkbox becomes "Verify P -> D after the run" and uses the method and pass chosen
  in Section D: once the run has finished, its own P windows are proven by the pt1.1 proof
  or by one wide v7.3 sieve pass, instead of a proof slab by slab inside the scan. The run
  logs two rows, the verification and pt1's run with the verification's time; the hint next
  to the checkbox names the method and a click on it scrolls to Section D. The run summary
  and the Benchmark table show the run speed without and with the verification and the
  speed it costs (the difference, in n/s); the chart draws both lines. The table's Proof
  column goes: the Verify column shows a verification's time, whenever it was run.
  A stopped run is not verified; a Benchmark run writes no windows, so the checkbox is
  greyed out under Benchmark, with the reason in a tooltip.
- Polski: Sekcja D zakładki Generowanie dostaje pole Metoda: dowód pt1.1 jak dotąd albo
  nowe sito v7.3, które w całości przesiewa sąsiednie okna P silnikiem v7.2 w przejściach do
  10^Przejście liczb (domyślnie 10^11, około 3,3 GB RAM) i przenosi zgodne okna do magazynu
  D jako D/P. Przejście v7.2 trwa na danym piętrze prawie stały czas niezależnie od
  szerokości, więc na szerokich zakresach sito jest dużo szybsze od dowodu (piętro 29: około
  15x przy 10^11 liczb). Obok metody szacunek czasu obu metod dla wybranych okien, z logu
  benchmarków. Wiersze weryfikacji magazynu (pt1_verify, v73_verify) nie pokazują już
  "write ?" przy wątkach: nie zapisują okien.
  Pole pt1 staje się „Weryfikuj P -> D po przebiegu” i używa metody oraz przejścia
  wybranych w Sekcji D: po zakończeniu przebiegu jego własne okna P są dowodzone dowodem
  pt1.1 albo jednym szerokim przejściem sita v7.3, zamiast dowodu slab po slabie w trakcie
  skanu. Przebieg zapisuje dwa wiersze: weryfikację i przebieg pt1 z czasem weryfikacji;
  podpowiedź obok pola pokazuje metodę, a kliknięcie w nią przewija do Sekcji D.
  Podsumowanie przebiegu i tabela Benchmark pokazują prędkość przebiegu bez weryfikacji
  i z nią oraz spadek prędkości przez weryfikację (różnica, w n/s); wykres rysuje obie
  linie. Znika
  kolumna Dowód: kolumna Weryfikacja pokazuje czas weryfikacji, niezależnie od tego, kiedy
  ją uruchomiono. Przebieg zatrzymany nie jest weryfikowany; przebieg benchmarku nie
  zapisuje okien, więc przy zaznaczonym Benchmarku pole jest wyszarzone, a dymek mówi
  dlaczego.

### +52 — Benchmark: a hidden axis stays hidden for new lines

- English: A chart axis hidden from the chart's right-click menu ("Hide left-axis lines" or
  "... right-axis lines") stays hidden when a new line appears on it: a new run after
  generation or a wider filter no longer brings back its circles or squares. A legend
  click on one of its lines shows that line alone; Show brings all back.
- Polski: Oś wykresu ukryta z menu kontekstowego („Ukryj linie lewej osi” albo „... prawej
  osi”) pozostaje ukryta, gdy pojawia się na niej nowa linia: nowy przebieg po
  generowaniu albo szerszy filtr nie przywraca już jej kółek ani kwadracików. Kliknięcie
  w legendzie jednej z jej linii pokazuje tylko tę linię; Pokaż przywraca wszystkie.

### +53 — Benchmark: copy table rows with Ctrl+C, fitted columns; tips stay inside the window

- English: The Benchmark run table gets a Copy column of boxes: tick runs, or a whole floor,
  across several floors, or all of them from the column heading, then Ctrl+C copies them as a Markdown table, ready to paste into a
  chat, and Ctrl+Shift+C as tab-separated values for a spreadsheet; the boxes clear after
  the copy. Ticking does not select or scroll the row. With nothing ticked, the selected rows
  are copied. Columns no copied run has a value in are left out. A hint above the table
  names both keys; its (i) explains how the copy works and how it is formatted. The (i)
  tips across the app now stay inside the window instead of running off its edge. The run
  table's columns fit their values: a heading longer than its values wraps onto two lines
  instead of widening the column.
- Polski: Tabela przebiegów Benchmarku dostaje kolumnę Kopiuj z kwadracikami: zaznaczasz
  przebiegi albo całe piętra, także z kilku pięter, albo wszystko klikiem w nagłówek
  kolumny, a Ctrl+C kopiuje je jako tabelę
  Markdown, gotową do wklejenia w czacie, Ctrl+Shift+C zaś jako wartości rozdzielone
  tabulatorami do arkusza; po skopiowaniu kwadraciki się czyszczą. Zaznaczanie nie wybiera
  ani nie przewija wiersza. Gdy nic nie jest zaznaczone, kopiują się wybrane wiersze.
  Kolumny bez wartości w żadnym kopiowanym przebiegu są pomijane. Podpowiedź nad tabelą
  podaje oba skróty, a jej (i) wyjaśnia, jak działa kopiowanie i jak formatuje dane.
  Dymki (i) w całej aplikacji mieszczą się teraz w oknie, zamiast wychodzić poza jego
  krawędź. Kolumny tabeli przebiegów dopasowują się do wartości: nagłówek dłuższy niż
  wartości zawija się w dwa wiersze, zamiast poszerzać kolumnę.

### +54 — Engines v7: the jump gear stays inside its proven range

- English: The jump gear of engines v7.0, v7.1 and v7.2 is now switched on only where it is
  proven exact: below 2^128 / 30 (about 1.13e37) and for buffers up to 2^48 numbers. Between
  that bound and the old limit 2^126 it could miss multiples; there the classic sieve now
  does the work. Blocks are capped at Q / 60 values of q and a block outside the gear's
  fixed-point range is checked number by number instead of being skipped. Output at every
  floor the app reaches is unchanged.
- Polski: Przekładnia skoków silników v7.0, v7.1 i v7.2 włącza się teraz tylko tam, gdzie jej
  dokładność jest udowodniona: poniżej 2^128 / 30 (około 1,13e37) i dla buforów do 2^48
  liczb. Między tą granicą a dawnym limitem 2^126 mogła gubić wielokrotności; tam pracuje
  teraz klasyczne sito. Bloki mają najwyżej Q / 60 wartości q, a blok poza zakresem
  stałoprzecinkowym przekładni jest sprawdzany liczba po liczbie zamiast pomijany. Wyniki na wszystkich
  piętrach, do których sięga aplikacja, są bez zmian.

### +55 — Engine v7.4: the jump gear reuses its three-gap steps

- English: The Generation tab's v7 engine is now code v7.4. Each thread keeps the jump gear's
  three-gap steps from its last block and reuses them when an exact certificate shows they
  still hold, which is the case for about 57 % of the blocks; otherwise it computes them as
  before. With 1e10 numbers and 24 threads, sieving is 4 % faster at floor 25, 7 % at
  floor 27, 8 % at floor 28 and 9 % at floor 29. Output is identical to v6.1. Benchmark rows
  show the engine as v7.4; v7.2 stays available for comparison.
- Polski: Silnik v7 w karcie Generowanie to teraz kod v7.4. Każdy wątek zachowuje kroki
  trzech odstępów przekładni skoków z poprzedniego bloku i używa ich ponownie, gdy dokładny
  certyfikat pokazuje, że nadal obowiązują. Dzieje się tak w około 57 % bloków, w pozostałych
  kroki liczone są jak dotąd. Przy 1e10 liczb i 24 wątkach sito jest szybsze o 4 % na
  piętrze 25, 7 % na 27, 8 % na 28 i 9 % na 29. Wyniki są identyczne z v6.1. Wiersze
  benchmarku pokazują silnik jako v7.4; v7.2 zostaje do porównań.

### +56 — Benchmark charts: axes, runs and their lines hide independently

- English: Hiding lines on a chart now works in three independent layers: the chart's axes
  (chart menu), a whole run (its name in the legend) and a run's line on one axis (its
  marker). A line is drawn only when no layer hides it, so each layer comes back exactly as
  it was left: a run switched off and on again shows only the axes it had, and a hidden axis
  stays hidden whatever is clicked in the legend. A marker is filled while its run keeps
  that line and dims while the line is not drawn.
- Polski: Ukrywanie linii na wykresie działa teraz w trzech niezależnych warstwach: osie
  wykresu (menu wykresu), cały przebieg (jego nazwa w legendzie) i linia przebiegu na jednej
  osi (jej znacznik). Linia jest rysowana tylko wtedy, gdy żadna warstwa jej nie ukrywa, więc
  każda warstwa wraca dokładnie taka, jaką zostawiono: przebieg wyłączony i włączony znów
  pokazuje tylko te osie, które miał, a ukryta oś zostaje ukryta bez względu na kliknięcia
  w legendzie. Znacznik jest wypełniony, póki przebieg ma tę linię, i przygaszony, gdy linia
  nie jest rysowana.

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
