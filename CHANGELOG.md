# Changelog

Versions follow [Semantic Versioning](https://semver.org/): a new feature raises the minor
number, a fix-only release the patch number. This file is the version's single source
(`primeatlas/core/version.py` reads it): the release is the newest `## X.Y.Z — date`
heading, and every merge into `main` after it appends one entry `### +N — title` to the
`## Since X.Y.Z` section, English first, then Polish. Entries are never edited; a
correction is a new entry. The app shows release, merge count and commit, e.g.
`1.2.0+24 (f59ce41)`, because Settings → Updates moves every copy along `main` between
releases. A release renames `## Since X.Y.Z` to `## A.B.C — date` and tags `vA.B.C`.

## Since 1.5.0

### +1 — One thread-count control, capped at WSL's CPUs

- English: Every thread count of the app (the pipeline form's workers, Section D's Threads,
  Pseudosquares' Threads and the v5/v6/v7 write threads) is now one control. Its list goes from
  1 to the CPU count WSL reports, and Max shows that count, e.g. "Max (8)"; Section D's Auto
  shows the workers it stands for. A larger number, typed or remembered from another computer,
  becomes Max (write threads: the count itself), so a run never asks for more threads than WSL
  has. Pseudosquares gains Max. The workers field's Auto button is gone: Max shows the same
  number. The app reads the CPU count once at startup in the background; every launch and the
  About tab's read refresh it.
- Polski: Każda liczba wątków w aplikacji (workers w formularzu potoku, Wątki w sekcji D, Wątki
  Pseudosquares i wątki zapisu v5/v6/v7) to teraz jedna kontrolka. Jej lista idzie od 1 do
  liczby procesorów, którą podaje WSL, a Max pokazuje tę liczbę, np. „Max (8)”; Auto w sekcji D
  pokazuje, ilu workerom odpowiada. Większa liczba, wpisana albo zapamiętana z innego komputera,
  zmienia się na Max (wątki zapisu: na samą liczbę procesorów), więc przebieg nigdy nie prosi o
  więcej wątków, niż ma WSL. Pseudosquares dostaje Max. Przycisk Auto przy workers znika: Max
  pokazuje tę samą liczbę. Aplikacja odczytuje liczbę procesorów raz przy starcie, w tle;
  każde uruchomienie i odczyt w zakładce O programie ją odświeżają.

### +2 — Section D: no Windows number without P windows

- English: When the chosen floor and width hold no P window, Section D's Windows field is now
  empty and greyed out, with "no P windows of this width" beside it; before, it showed a red 0,
  as if a wrong number had been typed. With P windows it holds their count as before, and a
  smaller number still proves only the first ones. The switch from Hybrid to primesieve gives a
  range narrower than 10^7 the width 1 instead of a red 0.
- Polski: Gdy wybrane piętro i szerokość nie mają żadnego okna P, pole Okna w sekcji D jest
  teraz puste i wyszarzone, a obok widać „brak okien P tej szerokości”; wcześniej pokazywało
  czerwone 0, jakby wpisano złą liczbę. Gdy okna P są, pole jak dotąd podaje ich liczbę, a
  mniejsza liczba nadal dowodzi tylko pierwszych okien. Przejście z Hybrid na primesieve daje
  zakresowi węższemu niż 10^7 szerokość 1 zamiast czerwonego 0.

### +3 — Section D: verify the first island in windows of a chosen width

- English: Section D now verifies the floor's first island: the run of adjacent P files from
  the smallest n (the next island comes once this one is D). One Window width field, in
  numbers (any notation, e.g. 1e8, shown short as 1e8, 9e7, 2.5e8), replaces the power-of-ten width and the v7.3 Pass fields:
  one file up to the island, for the v7.3 sieve up to what the free RAM allows; a value
  outside takes the nearest end, one between rounds down to whole files, and the last window
  holds the rest. A Split into windows field, with the island's size beside it, sets the same
  from the other side: a new width recounts the split, a new split recounts the width (evenly,
  in whole files). Verify now picks how many of those windows one run verifies, all by
  default. Auto picks the width: for the pt1.1 proof one file (the most windows, small
  portions at a time), for the v7.3 sieve the fewest windows the RAM allows, split evenly. A
  file wider than its neighbours (a 10^8 file among 10^7 ones) is recognised by its last prime
  and verified on its own at its width. Before, a width wider than the stored files counted
  only the files on its grid, and files of another width could be taken as wider ones.
- Polski: Sekcja D weryfikuje teraz pierwszą wyspę piętra: ciąg sąsiednich plików P od
  najmniejszego n (następna wyspa przychodzi, gdy ta stanie się D). Jedno pole Szerokość okna,
  w liczbach (dowolny zapis, np. 1e8, pokazywany krótko: 1e8, 9e7, 2.5e8), zastępuje szerokość jako potęgę dziesięciu i pole
  Przejście v7.3: od jednego pliku do całej wyspy, dla sita v7.3 do tego, na co pozwala wolny
  RAM; wartość spoza zakresu przyjmuje bliższy koniec, pośrednia jest zaokrąglana w dół do
  całych plików, a ostatnie okno mieści resztę. Pole Podział na okna, z rozmiarem wyspy obok,
  ustawia to samo z drugiej strony: nowa szerokość przelicza podział, nowy podział przelicza
  szerokość (po równo, w całych plikach). Weryfikuj teraz wybiera, ile z tych okien weryfikuje
  jedno uruchomienie, domyślnie wszystkie. Auto dobiera szerokość: dla dowodu pt1.1 jeden plik
  (najwięcej okien, małe porcje), dla sita v7.3 najmniej okien, na ile pozwala RAM, po równo.
  Plik szerszy od sąsiadów (plik 10^8 wśród plików 10^7) jest rozpoznawany po ostatniej liczbie
  pierwszej i weryfikowany osobno ze swoją szerokością. Wcześniej szerokość większa od
  zapisanych plików liczyła tylko pliki na swojej siatce, a pliki innej szerokości mogły być
  brane za szersze.

### +4 — Changelog: entries since 1.5.0 in merge order

- English: The entries since 1.5.0 now stand in merge order, +1 first, like every earlier
  section; About → Changes since release again lists the newest change at the top.
- Polski: Wpisy od 1.5.0 stoją teraz w kolejności scaleń, od +1, jak w każdej wcześniejszej
  sekcji; O programie → Zmiany od wydania znów pokazuje najnowszą zmianę na górze.

### +5 — Quick-gen: a range's gaps are filled, counts read the engine's store

- English: A range given by a starting point or From/To is checked window by window: gaps below
  windows stored further up the floor are generated instead of reported as "already in
  storage", and a search for a number in such a gap offers to generate it. Every window count
  shows the store the selected engine writes into (pt1: P from floor 24 on), and a floor stored
  up to its last window but with gaps points to "Fill gaps first".
- Polski: Zakres podany punktem startowym lub Od/Do jest sprawdzany okno po oknie: luki pod
  oknami zapisanymi wyżej na piętrze są generowane, zamiast zgłaszać „już w magazynie”, a
  wyszukanie liczby w takiej luce proponuje jej wygenerowanie. Każda liczba okien pokazuje
  magazyn, do którego pisze wybrany silnik (pt1: P od piętra 24), a piętro zapisane do ostatniego
  okna, ale z lukami, wskazuje „Najpierw wypełnij luki”.

### +6 — Pages: the mouse wheel scrolls the page under the pointer after Run or Generate

- English: The mouse wheel no longer stops scrolling a page after Run, Generate or a dialog
  until the pointer left the page and came back. Every turn scrolls the page under the pointer;
  in a page inside another page the inner one scrolls, or the outer one while the inner fits.
- Polski: Kółko myszy nie przestaje już przewijać strony po Uruchom, Generuj czy oknie
  dialogowym, aż wskaźnik wyjdzie poza stronę i wróci. Każdy obrót przewija stronę pod
  wskaźnikiem; w stronie zagnieżdżonej przewija się wewnętrzna, a gdy ta się mieści — zewnętrzna.

### +7 — Generation Section D: Run greyed out while the floor has no P windows

- English: Section D's Run is greyed out while the chosen floor has no P windows to prove, and
  active as soon as it has some, instead of opening an error dialog. The section recounts the
  floor's P windows after every engine's run and whenever the Generation tab is shown, so P
  windows removed in the primes tree count without changing the floor. After a pt1 run that
  writes files, Section D moves to that run's floor and runs Auto, so width and window count
  show the P windows the run left.
- Polski: Przycisk Uruchom w sekcji D jest wyszarzony, dopóki wybrane piętro nie ma okien P do
  udowodnienia, i aktywny, gdy tylko je ma, zamiast otwierać okno błędu. Sekcja przelicza okna
  P piętra po przebiegu każdego silnika i przy każdym pokazaniu zakładki Generowanie, więc okna
  P usunięte w drzewie liczb pierwszych liczą się bez zmiany piętra. Po przebiegu pt1, który
  zapisuje pliki, sekcja D przechodzi na piętro tego przebiegu i wykonuje Auto, więc szerokość
  i liczba okien pokazują okna P, które przebieg zostawił.

### +8 — Generation Section D: Width arrows step by round widths

- English: Section D's Width arrows and wheel step to the next round width (one significant
  digit: 1e8, 2e8, ... 9e8, 1e9; down 1e9 -> 9e8) instead of one file, so a big island is
  crossed in a few clicks. A width between two round ones steps to the round one on that side
  (2.5e8 -> 3e8 or 2e8). Every step is at least one file and stays within the range: above
  the island's last round width comes the island itself. A small island still steps file by
  file. Typing a width, the Split field and Auto are unchanged.
- Polski: Strzałki i kółko pola Szerokość w sekcji D przechodzą do następnej okrągłej
  szerokości (jedna cyfra znacząca: 1e8, 2e8, ... 9e8, 1e9; w dół 1e9 -> 9e8) zamiast o jeden
  plik, więc dużą wyspę przechodzi się w kilku kliknięciach. Szerokość między dwiema okrągłymi
  przechodzi do okrągłej po tej stronie (2.5e8 -> 3e8 albo 2e8). Każdy krok to co najmniej
  jeden plik i nie wychodzi poza zakres: nad ostatnią okrągłą szerokością wyspy jest sama
  wyspa. Mała wyspa nadal idzie plik po pliku. Wpisywanie szerokości, pole Podział i Auto się
  nie zmieniają.

### +9 — Numbers in the notation of the language, with a choice in Settings

- English: Every number the app shows (labels, tables, hints, visualization HUDs, the benchmark
  report) is now written in the notation of the interface language: 1 234 567,89 in Polish,
  1,234,567.89 in English. Settings > General gains Number format: Follow the language, or one
  of 1 234 567,89 · 1,234,567.89 · 1.234.567,89 · 1'234'567.89 · 1234567.89; like the language,
  the change restarts the app. Logs, CSV and other files, command lines and the values the app
  writes into number fields keep the plain form; short widths like 2.5e8 keep the dot.
- Polski: Każda liczba, którą pokazuje aplikacja (etykiety, tabele, podpowiedzi, HUD-y
  wizualizacji, raport benchmarku), jest teraz zapisana w notacji języka interfejsu:
  1 234 567,89 po polsku, 1,234,567.89 po angielsku. Ustawienia > Ogólne dostają Format liczb:
  Według języka albo jeden z 1 234 567,89 · 1,234,567.89 · 1.234.567,89 · 1'234'567.89 ·
  1234567.89; tak jak język, zmiana restartuje aplikację. Logi, CSV i inne pliki, wiersze
  poleceń i wartości wpisywane przez aplikację do pól liczbowych zostają w prostej postaci;
  krótkie szerokości jak 2.5e8 zachowują kropkę.

### +10 — Number field tips say what the field is for

- English: Hovering a number field now starts with what the field is for (with its unit,
  e.g. windows of 10 million numbers) and its range in the app's number notation
  ("Range: 1 to 100,000"); a range error groups the digits the same way. The list of accepted
  notations shows only on fields that take large numbers (no maximum, or a maximum of at least
  10^6); other fields get one short line of the power and scientific forms (10^4 · 1e4).
  The fraction line shows only on fields that take fractions.
- Polski: Dymek pola liczbowego zaczyna się teraz od tego, do czego pole służy (z jednostką,
  np. okna po 10 milionów liczb), i jego zakresu w notacji liczb aplikacji („Zakres: od 1 do
  100 000”); błąd zakresu grupuje cyfry tak samo. Lista przyjmowanych notacji pokazuje się
  tylko w polach na duże liczby (bez maksimum albo z maksimum co najmniej 10^6); pozostałe
  pola dostają jedną krótką linię o zapisie potęgi i naukowym (10^4 · 1e4). Linia o ułamkach
  pokazuje się tylko w polach, które przyjmują ułamki.

### +11 — Target planner: an example, the file form and an engine per target

- English: The target planner has an Insert example button that fills the targets field with
  a ready list (asking before it replaces other text); the same list is written into the
  storage folder as target_planner_example.txt, where Load file now opens, and an edited copy
  is never overwritten. "How does it work?" describes the file form: one target per line,
  # comments, .txt or .csv in UTF-8. A target line can end with an engine (v4.1, v5, v6, v7,
  pt1.1, pt1-pss, or pss for Pseudosquares): those targets are planned with that engine only,
  in runs of their own, and Use selects that engine in the Generation form. A run the named
  engine cannot time stays in the table without a time.
- Polski: Planer celów ma przycisk Wstaw przykład, który wpisuje do pola celów gotową listę
  (pytając, zanim zastąpi inny tekst); ta sama lista trafia do folderu zapisu jako
  target_planner_example.txt, w którym teraz otwiera się Wczytaj plik, a zmieniona kopia nigdy
  nie jest nadpisywana. „Jak to działa?” opisuje postać pliku: jeden cel w wierszu, komentarze
  #, .txt albo .csv w UTF-8. Wiersz celu może kończyć się silnikiem (v4.1, v5, v6, v7, pt1.1,
  pt1-pss albo pss dla Pseudosquares): takie cele są planowane tylko tym silnikiem, we własnych
  przebiegach, a Użyj wybiera ten silnik w formularzu Generacji. Przebieg, którego wskazany
  silnik nie umie oszacować, zostaje w tabeli bez czasu.

### +12 — Computers of the benchmark rows: hardware details and typed values

- English: Atlas now records the computer every run comes from in benchmark_machines.json in
  the storage folder: the CPU (model, cores, threads, base clock, L2/L3, family) and the RAM
  (size, modules, type, speed) read from Windows without admin rights, and the values Windows
  cannot give, typed in About → This computer → Fill in details: architecture, release year,
  turbo clock, RAM CL and XMP/EXPO, with a how-to of where to find them (BIOS/UEFI only as an
  option for advanced users) and a hint when the RAM runs above its JEDEC speed. After the
  first benchmark results from a computer Atlas asks once whether to fill them in. A hardware
  change starts a new entry, so older results keep the hardware they ran on. The file goes
  into backups and storage integration and is merged on restore, so no entry is lost; a
  damaged file is never overwritten, a copy is kept and Atlas says so.
- Polski: Atlas zapisuje teraz w benchmark_machines.json w folderze zapisu komputer, z którego
  pochodzi każdy przebieg: procesor (model, rdzenie, wątki, zegar bazowy, L2/L3, rodzina) i RAM
  (rozmiar, moduły, typ, szybkość) odczytane z Windows bez uprawnień administratora, oraz
  wartości, których Windows nie poda, wpisywane w O programie → Ten komputer → Uzupełnij dane:
  architektura, rok premiery, zegar turbo, CL pamięci i XMP/EXPO, z instrukcją, gdzie je
  znaleźć (BIOS/UEFI tylko jako opcja dla zaawansowanych) i podpowiedzią, gdy RAM pracuje
  szybciej niż JEDEC. Po pierwszych wynikach benchmarku z danego komputera Atlas raz pyta, czy
  je uzupełnić. Zmiana sprzętu zaczyna nowy wpis, więc starsze wyniki zachowują sprzęt, na
  którym powstały. Plik trafia do kopii zapasowych i integracji magazynu i jest scalany przy
  przywracaniu, więc żaden wpis nie ginie; uszkodzony plik nigdy nie jest nadpisywany, Atlas
  zachowuje jego kopię i o tym informuje.

### +13 — About: typed hardware values in the CPU and RAM details lines

- English: About → This computer shows the values typed for this computer inside the
  hardware lines instead of a separate "Typed in" line: architecture, release year and turbo
  in the CPU details, CL and XMP/EXPO in the installed RAM line. The CPU details now stand
  right under the CPU line and the RAM details right under the RAM line. A value not typed is
  simply left out.
- Polski: O programie → Ten komputer pokazuje wartości wpisane dla tego komputera w liniach
  sprzętu zamiast osobnej linii „Wpisane”: architekturę, rok premiery i turbo w szczegółach
  CPU, CL i XMP/EXPO w linii zainstalowanego RAM-u. Szczegóły CPU stoją teraz zaraz pod linią
  procesora, a szczegóły RAM-u zaraz pod linią RAM. Wartość niewpisana jest po prostu pomijana.

### +14 — Benchmark: the computer of each run, clickable, filterable and in the exports

- English: The Benchmark table's Computer cell names the computer a run ran on, e.g.
  "Ryzen 9 5900X (3f9a0c)": the CPU model and the start of its id, as recorded in
  benchmark_machines.json when the run started. A run from a computer without its file shows
  the id alone; a run from before the id was logged stays blank. A click on the cell opens the
  Computer window with every recorded state of that computer (hardware read from Windows and
  the values typed in About). The Filter window gains a Computer dimension, which also tells
  apart one computer before and after a RAM change. The HTML page and the PDF end with a
  "Computers" section, a table per computer of the exported runs, and each run's cell links to
  it; the CSV export writes the computers to a second file, <name>_computers.csv.
- Polski: Komórka Komputer w tabeli Benchmarku nazywa komputer, na którym szedł przebieg, np.
  „Ryzen 9 5900X (3f9a0c)”: model procesora i początek jego identyfikatora, tak jak zapisał je
  benchmark_machines.json w chwili startu przebiegu. Przebieg z komputera bez jego pliku
  pokazuje sam identyfikator, a przebieg sprzed zapisywania identyfikatora zostaje pusty.
  Kliknięcie komórki otwiera okno Komputer z każdym zapisanym stanem tego komputera (sprzęt
  odczytany z Windows i wartości wpisane w O programie). Okno Filtr dostaje wymiar Komputer,
  który rozróżnia też ten sam komputer przed wymianą RAM-u i po niej. Strona HTML i PDF kończą
  się sekcją „Komputery” z tabelą dla każdego komputera z eksportowanych przebiegów, a komórka
  każdego przebiegu do niej odsyła; eksport CSV zapisuje komputery do drugiego pliku,
  <nazwa>_computers.csv.

### +15 — Small screens: one layout pass for wrapping rows, Quick-gen modes and the floor nav wrap

- English: Rows that wrap to their width are now laid out by one coordinator, top-down and
  once per width change, so a row's own height can no longer start another layout and the app
  cannot hang in a layout loop. On a small screen (1280 x 720, e.g. a 13" Full HD laptop at
  150 %) the Quick-gen mode row wraps onto a second line instead of cutting off Pseudosquares
  and cudasieve; a mode name wider than the whole row is shortened with "…" and an ⓘ marker,
  and hovering it shows the full name. The floor page navigation above the Prime numbers tree
  wraps the same way, so Go is no longer cut; its buttons read Previous, Next, then the page
  count, as in the other page navigations. The tree pane is as wide as the wider of its
  columns and the navigation's widest group, and its horizontal scrollbar keeps its room
  (greyed out while not needed), so it no longer changes the tree's height. Under
  Constellations > Storage the tree pane keeps its share of the width when the window is
  resized, so making the window narrow and wide again restores the same split. The window can
  no longer be made narrower than 1280 px (or the screen), the narrowest width at which every
  tab is checked to show all its controls; it starts 1280 px wide.
- Polski: Rzędy zawijane do swojej szerokości układa teraz jeden koordynator, od góry i raz na
  zmianę szerokości, więc wysokość rzędu nie uruchamia już kolejnego układania, a aplikacja nie
  może zawisnąć w pętli układu. Na małym ekranie (1280 x 720, np. laptop 13" Full HD przy
  150 %) rząd trybów Quick-gen przechodzi do drugiej linii zamiast ucinać Pseudosquares
  i cudasieve; nazwa trybu szersza niż cały rząd jest skracana „…” ze znacznikiem ⓘ, a po
  najechaniu pokazuje pełną nazwę. Nawigacja stron piętra nad drzewem Liczb pierwszych zawija
  się tak samo, więc Idź nie jest już ucięte; przyciski czytają się Poprzednia, Następna, potem
  licznik stron, jak w pozostałych nawigacjach stron. Panel drzewa ma szerokość większą
  z dwóch: kolumn albo najszerszej grupy nawigacji, a jego poziomy pasek przewijania ma stałe
  miejsce (wyszarzony, gdy niepotrzebny), więc nie zmienia już wysokości drzewa.
  W Konstelacje > Magazyn panel drzewa zachowuje swój udział w szerokości przy zmianie
  rozmiaru okna, więc zwężenie i ponowne poszerzenie okna przywraca ten sam podział. Okna nie
  da się już zwęzić poniżej 1280 px (albo szerokości ekranu), najmniejszej szerokości, przy
  której każda zakładka ma sprawdzone, że pokazuje wszystkie swoje elementy; startuje
  z szerokością 1280 px.

## 1.5.0 — 2026-11-17

### +1 — Generation: RAM check on Generate, proposal from the run's start, native primesieve without storage

- English: Generate now checks a run's predicted RAM against the RAM budget: a pipeline run, or
  a Quick-gen run launched directly, over the budget (parallel instances counted) asks whether
  to run anyway and names the predicted GB, the budget and the free RAM; No launches nothing.
  The free RAM in WSL is read when the Generation tab opens and after every run, so the check
  and the engine proposal no longer wait for the Time simulation window. The Quick-gen engine
  proposal times the run from where Generate starts it (the typed starting point, or where the
  floor's stored windows end) instead of the floor's start. primesieve mode with Native on no
  longer compares the range with the stored windows (a native run writes nothing there): a
  blank From starts at the floor's start, as in Pseudosquares mode.
- Polski: Generuj sprawdza teraz przewidywany RAM przebiegu względem budżetu RAM-u: przebieg
  potoku albo przebieg Szybkiego generowania uruchamiany bezpośrednio, który przekracza budżet
  (z liczbą równoległych instancji), pyta, czy uruchomić mimo to, i podaje przewidywane GB,
  budżet i wolny RAM; Nie niczego nie uruchamia. Wolny RAM w WSL jest odczytywany przy
  otwarciu zakładki Generowanie i po każdym przebiegu, więc sprawdzenie i propozycja silnika
  nie czekają już na okno Symulacji czasu. Propozycja silnika w Szybkim generowaniu liczy
  przebieg od miejsca, w którym Generuj go zaczyna (wpisany punkt startowy albo koniec
  zapisanych okien piętra), a nie od początku piętra. Tryb primesieve z zaznaczonym Natywnie
  nie porównuje już zakresu z zapisanymi oknami (przebieg natywny nic tam nie zapisuje):
  puste Od zaczyna od początku piętra, jak w trybie Pseudosquares.

### +2 — Generation: running time and ETA of a run from the time model

- English: While a pipeline run or a Quick-gen run is generating, the status line ends with
  its running time and the estimated time left, refreshed every second. The estimate starts
  from the time model (the same calibration as the engine proposal) at launch, so it shows
  before the first progress line, and covers every iteration of a pipeline loop; once a tenth
  of the modelled work is reported, it follows the run's measured pace. Without a calibration
  for the engine only the running time shows.
- Polski: Podczas generowania przebiegiem potoku albo Szybkiego generowania linia statusu
  kończy się czasem trwania i szacowanym czasem do końca, odświeżanymi co sekundę. Szacunek
  startuje z modelu czasu (ta sama kalibracja co propozycja silnika) w chwili uruchomienia, więc
  widać go przed pierwszą linią postępu, i obejmuje wszystkie iteracje pętli potoku; gdy
  zgłoszona jest jedna dziesiąta modelowanej pracy, idzie za zmierzonym tempem przebiegu. Bez
  kalibracji silnika widać tylko czas trwania.

### +3 — Generation: pipeline form fits a small screen; defaults one instance, one batch, v7, workers Max

- English: The pipeline's Advanced settings are grouped into four frames (Range, Parallelism,
  Counting pi(L_final), Sieve engine), each laid out on its own, and the long pi(L_final)
  options wrap, so the whole form fits a 13" Full HD screen at 150 % scaling; before, the
  Batches / worker field fell outside the window. A fresh install now starts with one
  parallel instance, one batch per worker and engine v7 (also the default of
  orchestrator_v3.py, now code version 3.1). Workers accepts Max, now the default: every
  CPU WSL reports, read at each launch, so the form fits the machine it runs on. Values
  already remembered stay as they are.
- Polski: Ustawienia zaawansowane potoku są pogrupowane w cztery ramki (Zakres,
  Równoległość, Liczenie pi(L_final), Silnik sita), każda rozkładana osobno, a długie opcje
  pi(L_final) się zawijają, więc cały formularz mieści się na ekranie 13" Full HD przy
  skalowaniu 150%; wcześniej pole Batche / workera wypadało poza okno. Świeża instalacja
  zaczyna teraz od jednej instancji równoległej, jednego batcha na workera i silnika v7
  (też domyślnego w orchestrator_v3.py, teraz w wersji kodu 3.1). Pole workers przyjmuje Max,
  teraz domyślne: wszystkie procesory widoczne w WSL, odczytywane przy każdym uruchomieniu,
  więc formularz pasuje do komputera, na którym działa. Już zapamiętane wartości zostają bez
  zmian.

### +4 — Research: Irreducibility -> Primality, whether a number is prime from its residues

- English: Research -> Irreducibility has a sixth sub-tab, Primality. It decides whether A (the
  same number and layout as in Comparison) is prime from its residues alone, as the
  repository's theorem T6 (isPrimeRes) does: divisors m = 2, 3, ... are compared with A and m²
  with A on residues, and A mod m is read from the mixed-radix digits. It shows the verdict
  (prime, composite with the divisor found, or no answer when the fuel runs out or the run is
  stopped), the number of steps, the first and last steps, and a check against integer
  primality. A long run goes on in the background of the window with its progress shown and
  can be stopped. When the layout leaves too little room above A for the square test, a note
  says so; Fit for primality sets a layout with enough room. Test 1000 numbers checks random
  numbers against trial division and lists every case.
- Polski: Badania -> Nieredukowalność ma szóstą podzakładkę, Pierwszość. Rozstrzyga, czy A (ta
  sama liczba i układ co w Porównaniu) jest liczbą pierwszą, wyłącznie z jej reszt, tak jak
  twierdzenie T6 repozytorium (isPrimeRes): dzielniki m = 2, 3, ... są porównywane z A, a m²
  z A na resztach, a A mod m jest odczytywane z cyfr w systemie mieszanym. Pokazuje werdykt
  (pierwsza, złożona ze znalezionym dzielnikiem albo brak odpowiedzi, gdy skończy się paliwo
  lub przebieg zostanie zatrzymany), liczbę kroków, pierwsze i ostatnie kroki oraz sprawdzenie
  pierwszości na liczbach całkowitych. Długi przebieg toczy się w tle okna z widocznym
  postępem i można go zatrzymać. Gdy układ zostawia nad A za mało miejsca na test kwadratu,
  pojawia się uwaga; Dopasuj do pierwszości ustawia układ z wystarczającym zapasem. Test 1000
  liczb sprawdza losowe liczby dzieleniem próbnym i wypisuje każdy przypadek.

### +5 — Research: Irreducibility -> Multiplicative counting, discrete logarithm and squares mod q

- English: Research -> Irreducibility has a seventh sub-tab, Multiplicative counting, after the
  repository's theorem T9. For a modulus q, a base g (or Auto) and a number N it counts one
  cycle multiplicatively (start at 1, multiply by g per step) next to the ordinary counter
  modulo q − 1 and shows the order of g, whether both counters are equal at the same pairs of
  steps, the step at which the cycle reaches N mod q (the discrete logarithm) and, from the
  parity of that step, whether N is a square modulo q. The square reading is given only when g
  is a primitive root; otherwise the tab says why. A check compares it with Euler's criterion
  on integers. For small q the sech comb of modulus q − 1 is drawn with the returns to 1
  marked. Test 1000 cases checks random primes and numbers and lists every case.
- Polski: Badania -> Nieredukowalność ma siódmą podzakładkę, Liczenie multiplikatywne, według
  twierdzenia T9 repozytorium. Dla modułu q, podstawy g (albo Auto) i liczby N liczy jeden
  cykl multiplikatywnie (start od 1, w każdym kroku mnożenie przez g) obok zwykłego licznika
  modulo q − 1 i pokazuje rząd g, czy oba liczniki są równe w tych samych parach kroków, krok,
  w którym cykl osiąga N mod q (logarytm dyskretny), oraz z parzystości tego kroku, czy N jest
  kwadratem modulo q. Odczyt kwadratu jest podawany tylko, gdy g jest pierwiastkiem
  pierwotnym; w przeciwnym razie zakładka mówi dlaczego. Sprawdzenie porównuje go z
  kryterium Eulera na liczbach całkowitych. Dla małych q rysowany jest grzebień sech o module
  q − 1 z zaznaczonymi powrotami do 1. Test 1000 przypadków sprawdza losowe liczby pierwsze i
  liczby oraz wypisuje każdy przypadek.

### +6 — Constellations: Density, hits against the Hardy-Littlewood prediction

- English: Constellations has a fourth sub-tab, Density. For a chosen k (and an optional
  floor range) it compares the hits of each variant with the Hardy-Littlewood prediction
  C * integral dt / (ln t)^k, both over exactly the spans the constellation finder has
  scanned; hits the targeted k-tuple sieve wrote outside those spans are left out. Each row
  gives the floor, the pattern, the scanned width, hits, prediction, their ratio and the
  deviation in Poisson standard deviations, with a sum row per floor when k has several
  variants. A chart shows the ratio per floor with +-1/sqrt(prediction) bars for the row
  selected in the table. The scan runs in the background and can be stopped.
- Polski: Konstelacje mają czwartą podzakładkę, Gęstość. Dla wybranego k (i opcjonalnego
  zakresu pięter) porównuje trafienia każdego wariantu z przewidywaniem Hardy'ego-Littlewooda
  C * całka dt / (ln t)^k, w obu przypadkach dokładnie po przedziałach przeszukanych przez
  finder konstelacji; trafienia zapisane poza nimi przez celowane sito k-krotek są pomijane.
  Każdy wiersz podaje piętro, wzorzec, przeszukaną szerokość, trafienia, przewidywanie, ich
  iloraz i odchylenie w odchyleniach standardowych rozkładu Poissona, z wierszem sumy na
  piętro, gdy k ma kilka wariantów. Wykres pokazuje iloraz na piętro ze słupkami
  ±1/sqrt(przewidywanie) dla wiersza zaznaczonego w tabeli. Skan działa w tle i można go
  zatrzymać.

### +7 — Generation: width proposal under the engine proposal

- English: Quick-gen shows a width proposal with its own Use button under the engine
  proposal. With Benchmark ticked (Floor or Explore) it proposes 10,000 windows (10^11
  numbers, lowered to what the RAM budget allows) and gives the modelled sieving speed now
  and then: a wider window measures a higher speed, while one run's prep time stays the
  same. In Explore writing into the storage with more than one iteration it proposes the
  same total range in fewer, wider runs, with the modelled total time now and then. A Floor
  run writing into the storage gets no proposal. In Explore the engine proposal marks its
  time as one iteration's, and the Floor and Explore hints give the real width maximum
  (100,000 windows; v4.1: 1000).
- Polski: Szybkie generowanie pokazuje pod propozycją silnika propozycję szerokości z
  własnym przyciskiem Użyj. Przy zaznaczonym Benchmarku (Piętro albo Eksploracja) proponuje
  10 000 okien (10^11 liczb, mniej, jeśli budżet RAM nie pozwala) i podaje modelową prędkość
  sitowania teraz i po zmianie: szersze okno mierzy wyższą prędkość, a czas przygotowania
  jednego przebiegu się nie zmienia. W Eksploracji z zapisem do magazynu i więcej niż jedną
  iteracją proponuje ten sam łączny zakres w mniejszej liczbie szerszych przebiegów, z
  modelowym łącznym czasem teraz i po zmianie. Przebieg w trybie Piętro z zapisem do
  magazynu nie dostaje propozycji. W Eksploracji propozycja silnika zaznacza, że jej czas
  dotyczy jednej iteracji, a podpowiedzi trybów Piętro i Eksploracja podają prawdziwe
  maksimum szerokości (100 000 okien; v4.1: 1000).

### +8 — Generation: target planner

- English: A new collapsible Target planner section in the Generation tab takes a list of
  numbers, one per line, each optionally with a radius ("10**25+3 1000"), typed or loaded from
  a file. Plan splits them into runs with the fewest estimated seconds: targets close to each
  other share one Atlas run of the selected engine (at most the widest run the RAM budget
  allows), isolated ones go to Pseudosquares print, timed with the speeds in the benchmark log.
  Windows already in the storage are left out. The table lists each run with its range,
  windows, targets, method and time, and the summary compares the plan with separate Atlas
  runs and with Pseudosquares alone. Use fills Quick-gen with the selected run (Floor mode with
  Start and storage writing on, or Pseudosquares print); nothing starts by itself. A "How does
  it work?" button shows a short explanation.
- Polski: Nowa zwijana sekcja Planer celów w zakładce Generowanie przyjmuje listę liczb, po
  jednej w wierszu, każda z opcjonalnym promieniem ("10**25+3 1000"), wpisaną albo wczytaną z
  pliku. Planuj dzieli je na przebiegi o najmniejszym szacowanym czasie: cele leżące blisko
  siebie dzielą jeden przebieg Atlasa wybranym silnikiem (najwyżej tak szeroki, jak pozwala
  budżet RAM), pojedyncze trafiają do Pseudosquares print, z czasami z prędkości w logu
  benchmarku. Okna, które są już w magazynie, są pomijane. Tabela pokazuje każdy przebieg z
  zakresem, oknami, celami, metodą i czasem, a podsumowanie porównuje plan z osobnymi
  przebiegami Atlasa i z samym Pseudosquares. Użyj wypełnia Quick-gen wybranym przebiegiem
  (tryb Piętro ze Startem i włączonym zapisem albo Pseudosquares print); nic nie startuje samo.
  Przycisk "Jak to działa?" pokazuje krótkie wyjaśnienie.

### +9 — Number fields: any notation, a hint and a check

- English: Every number field in the app (195 fields: Quick-gen and its arrow fields, the
  pipeline form and engine knobs, Verify, k-tuples, primesieve calculator, Primality,
  Constellations, Research with Irreducibility, the visualizations, page go-to fields,
  Settings) reads a number in any common notation, typed or pasted: "1 000 000",
  "1,000,000", "1.000.000", "1'000'000", "1,00,00,000", "10^25", "10²⁵", "3×10^24",
  "1,5E+25", "10^25+3"; fraction fields (point sizes, angle, BPSW offset, comb scale) also
  "1,5". Before, "^" with another term was read as XOR ("10^25+3" gave 22) and "1,5"
  silently became 15. Hovering a field shows the accepted forms. Text that is not a usable
  number, or lies outside the field's range, turns the field red; text that can be read two
  ways ("3,000": 3000 or 3) offers both under the field, and a click writes the one meant. A
  valid number shows nothing. Red and the offer wait for a short pause in typing. The arrow
  fields no longer block keys outside digits; their range turns them red instead, and
  Quick-gen Generate refuses a red field of the selected mode (naming the reason) instead of
  falling back to a default width.
- Polski: Każde pole liczbowe w aplikacji (195 pól: Quick-gen z polami ze strzałkami,
  formularz potoku i ustawienia silników, Weryfikacja, k-krotki, kalkulator primesieve,
  Primality, Konstelacje, Badania z Nieredukowalnością, wizualizacje, pola skoku do strony,
  Ustawienia) czyta liczbę w dowolnym popularnym zapisie, wpisaną albo wklejoną:
  "1 000 000", "1,000,000", "1.000.000", "1'000'000", "1,00,00,000", "10^25", "10²⁵",
  "3×10^24", "1,5E+25", "10^25+3"; pola ułamkowe (rozmiary punktów, kąt, offset BPSW,
  skala grzebienia) także "1,5". Wcześniej "^" z kolejnym składnikiem było czytane jako XOR
  ("10^25+3" dawało 22), a "1,5" po cichu stawało się 15. Najechanie na pole pokazuje
  przyjmowane zapisy. Tekst, który nie jest użyteczną liczbą albo wychodzi poza zakres pola,
  podświetla pole na czerwono; tekst do odczytania na dwa sposoby ("3,000": 3000 albo 3)
  proponuje oba pod polem, a kliknięcie wpisuje właściwy. Poprawna liczba nie pokazuje
  niczego. Czerwień i propozycja czekają na krótką przerwę w pisaniu. Pola ze strzałkami nie
  blokują już klawiszy innych niż cyfry; ich zakres podświetla je na czerwono, a Generuj w
  Quick-gen odmawia startu przy czerwonym polu wybranego trybu (podając powód) zamiast
  przyjąć domyślną szerokość.

### +10 — Engine series 2026-11-16: v7.2, v7.4 and pt1 against the Pseudosquares Prime Sieve

- English: BENCHMARK.md opens with a new series on the same desktop (204 runs, equal prime
  counts): v7.4 against v7.2 at 10^9, 10^10 and 10^11 numbers per run on floors 18-30, both
  against the Pseudosquares Prime Sieve, and pt1 and pt1-pss on floors 30-35, with peak RAM.
  Speeds leave out the window write phase, which depends on the disk. The script, raw rows and
  the table generator are in `benchmarks/2026-11-16_engines/`. The engine v7.2 can again be
  selected outside the GUI (`PRIMEATLAS_SCANNER_VERSION=v7.2`) for A/B runs against v7.4;
  the GUI's v7 is still v7.4.
- Polski: BENCHMARK.md zaczyna się od nowej serii pomiarów na tym samym komputerze (204
  przebiegi, zgodne liczby liczb pierwszych): v7.4 wobec v7.2 przy 10^9, 10^10 i 10^11 liczb
  na przebieg na piętrach 18-30, oba wobec Pseudosquares Prime Sieve, oraz pt1 i pt1-pss na
  piętrach 30-35, ze szczytowym zużyciem RAM-u. Prędkości nie obejmują fazy zapisu okien,
  która zależy od dysku. Skrypt, surowe wiersze i generator tabel są w
  `benchmarks/2026-11-16_engines/`. Silnik v7.2 znów można wybrać poza GUI
  (`PRIMEATLAS_SCANNER_VERSION=v7.2`) do przebiegów A/B wobec v7.4; v7 w GUI to nadal v7.4.

### +11 — About: This computer (Windows and WSL hardware, WSL RAM limit)

- English: The About tab shows the computer Atlas runs on: Windows version, processor with
  its cores and threads, Windows RAM total and free, the WSL distro and kernel, the CPUs and
  RAM WSL sees, and the WSL RAM limit as a share of the Windows RAM with where it comes from
  (`memory=` in `.wslconfig`, or the WSL default of half the Windows RAM). It is read in the
  background the first time the tab is opened, so starting Atlas does not start WSL; a
  refresh icon reads it again and a copy icon copies it. Nothing needs admin rights; a
  value that cannot be read shows as unknown.
- Polski: Zakładka O programie pokazuje komputer, na którym działa Atlas: wersję Windows,
  procesor z liczbą rdzeni i wątków, RAM Windows (całkowity i wolny), dystrybucję i jądro
  WSL, procesory i RAM widziane przez WSL oraz limit RAM-u WSL jako część RAM-u Windows ze
  źródłem (`memory=` w `.wslconfig` albo domyślne ustawienie WSL: połowa RAM-u Windows).
  Dane są odczytywane w tle przy pierwszym otwarciu zakładki, więc start Atlasa nie
  uruchamia WSL; ikona odświeżania odczytuje je ponownie, a ikona kopiowania kopiuje. Nic
  nie wymaga uprawnień administratora; wartość, której nie da się odczytać, jest pokazana
  jako nieznana.

### +12 — Generation: RAM budget respects the RAM free in Windows

- English: The RAM budget is now a share of the lower of two readings: the RAM available in
  WSL and the RAM free in Windows. Before, only WSL's reading counted, so with a WSL limit
  close to the Windows RAM a run could be sized for memory Windows did not have left. This
  covers the RAM check on Generate, the engine and width proposals, the Time simulation
  window, the Quick-gen Auto buttons and Settings → Restore. Memory WSL already holds in its
  file cache counts only on the WSL side, so the reading errs low, never high.
- Polski: Budżet RAM-u jest teraz częścią mniejszej z dwóch wartości: RAM-u dostępnego w
  WSL i RAM-u wolnego w Windows. Wcześniej liczył się tylko odczyt z WSL, więc przy limicie
  WSL bliskim RAM-owi Windows przebieg mógł zostać dobrany do pamięci, której Windows już
  nie miał. Dotyczy to sprawdzenia RAM-u przy Generuj, propozycji silnika i szerokości, okna
  Symulacji czasu, przycisków Auto w Szybkim generowaniu i Ustawień → Przywracanie. Pamięć,
  którą WSL trzyma już w pamięci podręcznej plików, liczy się tylko po stronie WSL, więc
  odczyt może być zaniżony, nigdy zawyżony.

### +13 — Quick-gen: Auto stops v7 at 10^11 numbers, Explore's Auto keeps the total

- English: The Quick-gen Auto buttons propose at most 10,000 windows (10^11 numbers) per v7
  run, even when RAM allows more: in benchmark runs a wider v7 run gains little speed beyond
  it, while it takes more RAM. The limit is a new field in the advanced form, "v7 Auto: widest
  run", and a wider width typed by hand still runs. In Explore with more than one iteration,
  Auto now re-splits iterations × width into wider windows and fewer iterations, by priority:
  exactly the same total (13 × 40,000 becomes 52 × 10,000, 13 × 1 becomes 1 × 13); when no
  exact split saves iterations, the fewest iterations at the widest window with a few windows
  more (2 × 997 under 500 becomes 4 × 499, 2 windows more); when neither fits in 100
  iterations, the fields stay as typed. The dialog says which one it took. With one iteration
  Auto fills the width as in Floor only. The width proposal line uses the same limit and the
  same priority, and names the extra windows when there are any.
- Polski: Przyciski Auto w Szybkim generowaniu proponują najwyżej 10 000 okien (10^11 liczb)
  na przebieg v7, nawet gdy RAM pozwala na więcej: w pomiarach szerszy przebieg v7 prawie już
  nie przyspiesza, a zajmuje więcej RAM-u. Limit to nowe pole w formularzu zaawansowanym,
  „v7 Auto: najszerszy przebieg”, a szerokość wpisana ręcznie dalej działa. W Eksploracji z
  więcej niż jedną iteracją Auto dzieli teraz iteracje × szerokość na szersze okna i mniej
  iteracji, według priorytetu: dokładnie ta sama suma (13 × 40 000 daje 52 × 10 000, 13 × 1
  daje 1 × 13); gdy dokładny podział nie oszczędza iteracji, najmniej iteracji przy
  najszerszym oknie, o kilka okien więcej (2 × 997 przy 500 daje 4 × 499, o 2 okna więcej);
  gdy żaden nie mieści się w 100 iteracjach, pola zostają jak wpisane. Okno mówi, który
  wariant wybrało. Przy jednej iteracji Auto wypełnia szerokość jak w trybie Tylko piętro.
  Linia propozycji szerokości używa tego samego limitu i tego samego priorytetu, a dodatkowe
  okna podaje, gdy są.

### +14 — Benchmark: every run records its computer and the CPU load around it

- English: Every run started from Atlas now logs three more columns in benchmark_log.csv: the
  computer it ran on (a short id derived from Windows, not the computer's name), how busy the
  whole CPU was in the 5 seconds before the launch, and how busy it was while the run ran
  (Atlas's own work included). Atlas reads them from Windows without admin rights. The
  Benchmark table shows them as Computer, CPU before and CPU during, in the run group, and so
  do the CSV, HTML and PDF exports. About → This computer shows the id this computer's rows
  carry. Older rows and runs started outside Atlas keep these columns blank.
- Polski: Każdy przebieg uruchomiony z Atlasa zapisuje teraz w benchmark_log.csv trzy kolejne
  kolumny: komputer, na którym działał (krótki identyfikator wyliczony z Windows, nie nazwa
  komputera), jak bardzo był zajęty cały procesor przez 5 sekund przed startem i jak bardzo w
  trakcie przebiegu (razem z pracą samego Atlasa). Atlas odczytuje je z Windows bez uprawnień
  administratora. Tabela Benchmark pokazuje je w grupie przebiegu jako Komputer, CPU przed i
  CPU w trakcie, podobnie eksport CSV, HTML i PDF. O programie → Ten komputer pokazuje
  identyfikator, który niosą wiersze tego komputera. Starsze wiersze i przebiegi uruchomione
  poza Atlasem mają te kolumny puste.

### +15 — Time model: only this computer's runs calibrate it

- English: The time model behind the Time simulation window, the engine and width proposals,
  the run ETA and the target planner now leaves out benchmark rows another computer wrote,
  so a log copied from a faster or slower machine no longer skews this computer's estimates.
  Rows without a computer id (logged before +14, or runs started outside Atlas) still count.
- Polski: Model czasu, z którego korzystają okno Symulacji czasu, propozycje silnika i
  szerokości, ETA przebiegu i planer celów, pomija teraz wiersze benchmarku zapisane przez inny
  komputer, więc log skopiowany z szybszej albo wolniejszej maszyny nie zniekształca już
  szacunków tego komputera. Wiersze bez identyfikatora komputera (zapisane przed +14 albo z
  przebiegów uruchomionych poza Atlasem) nadal się liczą.

### +16 — About: change the WSL RAM limit from Atlas

- English: About → This computer has a row that sets how much RAM WSL may use (memory= in
  .wslconfig). It proposes Windows RAM minus a quarter (at least 3 GB left for Windows),
  accepts from WSL's default (half the RAM) up to the whole RAM, warns before a limit above the
  proposal (the computer can slow down, freeze or even switch off), shows the exact lines it
  will change and asks before saving; the old file is kept as a backup next to it and nothing
  else in the file changes. The new limit applies when WSL starts again: Atlas offers to
  restart WSL now, except while a Generation job runs. No admin rights needed.
- Polski: About → Ten komputer ma wiersz, który ustawia, ile RAM może używać WSL (memory= w
  .wslconfig). Proponuje RAM Windows minus jedną czwartą (co najmniej 3 GB zostaje dla Windows),
  przyjmuje od domyślnej wartości WSL (połowa RAM) do całego RAM, ostrzega przed limitem powyżej
  proponowanego (komputer może zwolnić, zawiesić się lub nawet wyłączyć), pokazuje dokładnie
  zmieniane linie i pyta przed zapisem; stary plik zostaje obok jako kopia zapasowa, a reszta
  pliku się nie zmienia. Nowy limit działa po ponownym starcie WSL: Atlas proponuje restart WSL
  od razu, chyba że trwa zadanie generowania. Nie wymaga uprawnień administratora.

### +17 — About: WSL limit Save does nothing when nothing would change

- English: Save in the WSL RAM limit row does nothing when the field holds the limit already in
  .wslconfig (in any unit, e.g. 10240MB = 10 GB): no question, no warning, no WSL restart. Save
  is disabled until the computer's RAM is read and while WSL restarts.
- Polski: Zapisz w wierszu limitu RAM WSL nic nie robi, gdy pole ma limit, który już jest w
  .wslconfig (w dowolnej jednostce, np. 10240MB = 10 GB): bez pytania, ostrzeżenia i restartu WSL.
  Zapisz jest nieaktywny, dopóki RAM komputera nie jest odczytany, i w trakcie restartu WSL.

### +18 — Progress bar holds the reported progress

- English: Once a job reports its progress (Constellations → Density floors, Goldbach,
  Records export, Generation), the bottom progress bar shows exactly that fraction; the busy
  animation no longer keeps moving it.
- Polski: Gdy zadanie poda swój postęp (Konstelacje → Gęstość, Goldbach, eksport Rekordów,
  Generowanie), dolny pasek postępu pokazuje dokładnie ten ułamek; animacja zajętości już go
  nie przesuwa.

## 1.4.0 — 2026-11-14

### +1 — Research → Irreducibility: radices, comparison, comb reading, ranges, arithmetic

- English: A new Research sub-tab computes the definitions of the Irreducibility repository
  (Lean 4, Mathlib) on your own input, with buttons that open the repository and its paper.
  Five sub-tabs. Radices and atoms: for the moduli lo..hi each modulus receives the radix
  m / gcd(P, m), P being the product of the radices before it, without forming P (radix > 1
  marked; for 2..N exactly the prime powers), and the atoms of the interval, primes below lo
  included, read from pairs a, a + k with k | a. Comparison: two numbers, each in its own
  layout of blocks D and quotient blocks K, compared from their residues only, digit by digit
  from the most significant, with one dial per block modulus, random neighbours and a test of
  1000 pairs. Comb reading: where modulus a stands on modulus b, read from the sech combs C_a
  and C_b (scale at least 3). Ranges: W of a layout, how W jumps when a parameter moves, and
  layouts fitted to any number, usable for A or B. Arithmetic: ⊕, ⊖ (with overflow and
  underflow), ⊗, ⊘ (exact or modulo W), the address with respect to T, powers and appended
  prime powers on residues, each checked against the integer result, and a test of 450
  random operations. Both tests open a window listing every case: the result read from
  residues next to the integer result, an 'only errors' filter, and the moduli and residues
  of the selected case. The fields are remembered. The mouse wheel no longer switches tabs
  anywhere in the app; over a tab strip it scrolls the page.
- Polski: Nowa podzakładka Badań liczy definicje repozytorium Irreducibility (Lean 4,
  Mathlib) na Twoich danych, z przyciskami otwierającymi repozytorium i jego artykuł. Pięć
  podzakładek. Podstawy i atomy: dla modułów lo..hi każdy moduł dostaje podstawę
  m / nwd(P, m), gdzie P to iloczyn podstaw przed nim, bez tworzenia P (podstawa > 1
  wyróżniona; dla 2..N dokładnie potęgi liczb pierwszych), oraz atomy przedziału, także
  liczby pierwsze poniżej lo, odczytane z par a, a + k z k | a. Porównanie: dwie liczby,
  każda we własnym układzie bloków D i bloków ilorazu K, porównywane wyłącznie z reszt, cyfra
  po cyfrze od najstarszej, z tarczą dla każdego modułu bloku, losowymi sąsiadami i testem
  1000 par. Odczyt z grzebieni: gdzie moduł a stoi na module b, odczytane z grzebieni sech C_a
  i C_b (skala co najmniej 3). Zakresy: W układu, skoki W przy zmianie parametru i układy
  dobrane do dowolnej liczby, do użycia dla A albo B. Arytmetyka: ⊕, ⊖ (z przepełnieniem i
  cofnięciem poniżej zera), ⊗, ⊘ (dokładne albo modulo W), adres względem T, potęgi i
  dołączane potęgi liczb pierwszych na resztach, każde sprawdzone wynikiem na liczbach
  całkowitych, oraz test 450 losowych działań. Oba testy otwierają okno z każdym przypadkiem:
  wynik odczytany z reszt obok wyniku na liczbach całkowitych, filtr „tylko błędy” oraz
  moduły i reszty zaznaczonego przypadku. Pola są zapamiętywane. Kółko myszy nie przełącza
  już kart w całej aplikacji; nad paskiem kart przewija stronę.

## 1.3.0 — 2026-11-14

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

### +57 — pt1 verification: corrected pseudosquares table, squares and cubes rejected

- English: Three entries of the pseudosquares table the P -> D verification uses (L_229,
  L_353, L_359) were not quadratic residues modulo 3 and 7 and are replaced by the correct
  values; the old ones were smaller, so every earlier verdict stays valid and the prime
  counts are unchanged. The verification now also rejects perfect squares and cubes
  explicitly, and a test checks every table entry against its definition.
- Polski: Trzy wpisy tablicy pseudokwadratów używanej przez weryfikację P -> D (L_229,
  L_353, L_359) nie były resztami kwadratowymi modulo 3 i 7; zastąpiono je poprawnymi
  wartościami. Stare były mniejsze, więc każdy wcześniejszy werdykt pozostaje ważny,
  a liczby pierwszych się nie zmieniają. Weryfikacja odrzuca teraz też jawnie kwadraty
  i sześciany, a test sprawdza każdy wpis tablicy z jego definicją.

### +58 — Engine pt1-pss: pt1 with the proof in the same pass

- English: New engine pt1-pss in the engine selector: the pt1 partial sieve with every
  survivor from 3.3e24 on decided by the pseudosquares proof in the same pass instead of
  BPSW. Every window is proven and goes straight to the D store, so no verification P -> D
  is needed. It runs on floors 7..34 (on floors 33 and 34 B is raised to what the proof
  needs) and costs about 9 times BPSW per survivor. The time model calibrates it separately.
- Polski: Nowy silnik pt1-pss w wyborze silnika: sito częściowe pt1, w którym każda ocalała
  liczba od 3,3e24 jest rozstrzygana dowodem pseudokwadratów w tym samym przebiegu zamiast
  BPSW. Każde okno jest dowiedzione i trafia od razu do magazynu D, więc weryfikacja P -> D
  nie jest potrzebna. Działa na piętrach 7..34 (na piętrach 33 i 34 B rośnie do wartości,
  jakiej wymaga dowód) i kosztuje ok. 9 razy tyle co BPSW na ocalałą liczbę. Model czasu
  kalibruje go osobno.

### +59 — Engine proposal: Atlas suggests the engine for the floor and width

- English: Quick generation and the Time simulation window now propose an engine for the run's
  floor and width from the time model. A deterministic engine comes first; pt1 with BPSW is
  proposed only when it is faster by the BPSW offset (advanced field, default 3x) and always
  with a warning that its result is probable, not proven. Use applies the proposal; nothing
  switches by itself. Engines without logged runs are estimated from measured seed values.
  The Pseudosquares program is shown only as a guest line with its measured speed-up, never
  as the proposal. tools/engine_advice.py prints the same proposal.
- Polski: Szybkie generowanie i okno Symulacji czasu proponują teraz silnik dla piętra i
  szerokości przebiegu na podstawie modelu czasu. Najpierw silnik deterministyczny; pt1 z BPSW
  jest proponowany tylko wtedy, gdy jest szybszy o offset BPSW (pole zaawansowane, domyślnie
  3x), i zawsze z ostrzeżeniem, że jego wynik jest prawdopodobny, a nie dowiedziony. Przycisk
  Użyj stosuje propozycję; nic nie przełącza się samo. Silniki bez przebiegów w logu są
  szacowane ze zmierzonych wartości startowych. Program Pseudosquares pojawia się tylko jako
  linia gościnna ze zmierzonym przyspieszeniem, nigdy jako propozycja. tools/engine_advice.py
  wypisuje tę samą propozycję.

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
