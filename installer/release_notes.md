## English

**PrimeAtlas 1.6.0** — Atlas now fits small screens and remembers its layout, writes numbers in the notation of your language, ties every benchmark result to the computer it ran on, and verifies P windows in a width you choose. One thread control caps every thread count at the CPUs WSL has, and About sets both WSL limits, RAM and processors.

PrimeAtlas is an application for generating, browsing and researching prime numbers: a prime and prime-constellation archive, research tabs (Goldbach, squares, polynomials, gaps, π(x) approximations, irreducibility) and GPU-rendered visualizations.

### What's new
- **Small screens and layout**
  - **Every tab down to 800 px wide**, in English and Polish at font size 100 % and 125 %: rows of fields and buttons wrap whole groups onto the next line, descriptions wrap to the width they have, and a narrow window never cuts a control off.
  - **Height grips** under every terminal, list, table, multi-line field and chart. Grip heights, the window's size and position, and terminals shown or hidden are remembered; Settings → General → Default layout brings the default back.
  - **Font size** stays the same after Windows reports a display change (a monitor woken from sleep, a new resolution).
- **Numbers in your language's notation:** every number the app shows is written as 1 234 567,89 in Polish and 1,234,567.89 in English; Settings → General → Number format picks another notation. Number field tips say what the field is for and its range.
- **One thread control:** the pipeline workers, Section D's Threads, Pseudosquares' Threads and the engines' write threads share one list from 1 to the CPU count WSL reports, with Max showing that count, e.g. "Max (8)"; a larger number becomes Max.
- **Generation**
  - **Section D** verifies the floor's first island of P files in windows of a width you choose, with Split into windows, Verify now and Auto (the fewest windows the RAM allows for the v7.3 sieve). Run is greyed out while the floor has no P windows.
  - **Quick-gen** fills the gaps of a range instead of reporting it as already in storage, and its window counts read the store the selected engine writes into.
  - **Target planner:** an Insert example button, the file form described in its how-to, and an optional engine per target line.
- **Benchmark → computers:** each run is tied to the computer it ran on (CPU and RAM read from Windows without admin rights, plus values you type in About → This computer → Fill in details, such as turbo clock and RAM CL). The table's Computer cell opens that computer's details; Filter, the HTML page, the PDF and the CSV export carry it.
- **About → This computer:** the WSL processor limit sits next to the RAM limit, both saved to `.wslconfig` with one Save (only what changed, one backup, one restart question); the WSL swap is shown with its source.
- **Fix:** after Run or Generate the mouse wheel scrolls the page under the pointer at once.

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

**PrimeAtlas 1.6.0** — Atlas mieści się na małych ekranach i pamięta swój układ, zapisuje liczby w notacji Twojego języka, wiąże każdy wynik benchmarku z komputerem, na którym powstał, i weryfikuje okna P w wybranej przez Ciebie szerokości. Jedna kontrolka wątków ogranicza każdą liczbę wątków do procesorów widocznych w WSL, a O programie ustawia oba limity WSL: RAM i procesory.

PrimeAtlas to aplikacja do generowania, przeglądania i badania liczb pierwszych: magazyn liczb pierwszych i konstelacji, zakładki badawcze (Goldbach, kwadraty, wielomiany, luki, przybliżenia π(x), nieredukowalność) oraz wizualizacje renderowane na GPU.

### Co nowego
- **Małe ekrany i układ**
  - **Każda karta działa już od 800 px szerokości**, po angielsku i po polsku, przy rozmiarze czcionki 100 % i 125 %: wiersze pól i przycisków przenoszą całe grupy do następnej linii, opisy zawijają się do dostępnej szerokości, a wąskie okno nigdy nie ucina kontrolki.
  - **Uchwyty wysokości** pod każdym terminalem, listą, tabelą, polem wielowierszowym i wykresem. Wysokości uchwytów, rozmiar i położenie okna oraz pokazane lub ukryte terminale są zapamiętywane; Ustawienia → Ogólne → Domyślny układ przywraca układ domyślny.
  - **Rozmiar czcionki** zostaje taki sam, gdy Windows zgłosi zmianę ekranu (monitor wybudzony z uśpienia, nowa rozdzielczość).
- **Liczby w notacji Twojego języka:** każda liczba pokazywana w aplikacji ma postać 1 234 567,89 po polsku i 1,234,567.89 po angielsku; Ustawienia → Ogólne → Format liczb pozwala wybrać inną notację. Podpowiedzi pól liczbowych mówią, do czego służy pole, i podają jego zakres.
- **Jedna kontrolka wątków:** workery pipeline, Wątki w Sekcji D, Wątki Pseudosquares i wątki zapisu silników mają wspólną listę od 1 do liczby procesorów zgłaszanej przez WSL, a Max pokazuje tę liczbę, np. „Max (8)”; większa liczba staje się Max.
- **Generowanie**
  - **Sekcja D** weryfikuje pierwszą wyspę plików P piętra w oknach wybranej szerokości, z polami Podział na okna, Weryfikuj teraz i przyciskiem Auto (najmniej okien, na ile pozwala RAM, dla sita v7.3). Uruchom jest wyszarzony, dopóki piętro nie ma okien P.
  - **Quick-gen** uzupełnia luki zakresu zamiast zgłaszać go jako już zapisany, a liczniki okien czytają magazyn, do którego zapisuje wybrany silnik.
  - **Planer celów:** przycisk Wstaw przykład, opis postaci pliku w instrukcji i opcjonalny silnik w każdej linii celu.
- **Benchmark → komputery:** każdy przebieg jest powiązany z komputerem, na którym działał (CPU i RAM odczytane z Windows bez uprawnień administratora oraz wartości wpisane w O programie → Ten komputer → Uzupełnij dane, np. zegar turbo i CL pamięci). Komórka Komputer w tabeli otwiera dane tego komputera; uwzględniają go Filtr, strona HTML, PDF i eksport CSV.
- **O programie → Ten komputer:** limit procesorów WSL stoi obok limitu RAM, oba zapisywane do `.wslconfig` jednym przyciskiem Zapisz (tylko to, co się zmieniło, jedna kopia zapasowa, jedno pytanie o restart); widać też swap WSL i jego źródło.
- **Poprawka:** po Uruchom lub Generuj kółko myszy od razu przewija stronę pod wskaźnikiem.

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
