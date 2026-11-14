## English

**PrimeAtlas 1.4.0** — a new Research sub-tab, Irreducibility, computes the definitions of the Irreducibility repository (Lean 4, Mathlib) on your own input: radices and atoms, comparison of numbers from residues only, comb reading, ranges and arithmetic on residues, each result checked against ordinary integers.

PrimeAtlas is an application for generating, browsing and researching prime numbers: a prime and prime-constellation archive, research tabs (Goldbach, squares, polynomials, gaps, π(x) approximations, irreducibility) and GPU-rendered visualizations.

### What's new
- **Research → Irreducibility**, five sub-tabs, with buttons that open the repository and its paper:
  - **Radices and atoms:** for the moduli lo..hi each modulus receives the radix m / gcd(P, m) without forming P (for 2..N exactly the prime powers), and the atoms of the interval.
  - **Comparison:** two numbers, each in its own block layout, compared from their residues only, digit by digit from the most significant, with one dial per block modulus.
  - **Comb reading:** where modulus a stands on modulus b, read from the sech combs.
  - **Ranges:** W of a layout, how W jumps when a parameter moves, and layouts fitted to any number.
  - **Arithmetic:** ⊕, ⊖, ⊗, ⊘ (exact or modulo W), the address with respect to T, powers and appended prime powers, all on residues.
- **Self-tests you can watch:** 1000 random comparisons and 450 random operations, each listed in its own window with the result read from residues next to the integer result, an *only errors* filter and the residues of the selected case.
- **Mouse wheel:** it no longer switches tabs anywhere in the app; over a tab strip it scrolls the page.

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

**PrimeAtlas 1.4.0** — nowa podzakładka Badań, Nieredukowalność, liczy definicje repozytorium Irreducibility (Lean 4, Mathlib) na Twoich danych: podstawy i atomy, porównanie liczb wyłącznie z reszt, odczyt z grzebieni, zakresy i arytmetykę na resztach, każdy wynik sprawdzony na zwykłych liczbach całkowitych.

PrimeAtlas to aplikacja do generowania, przeglądania i badania liczb pierwszych: magazyn liczb pierwszych i konstelacji, zakładki badawcze (Goldbach, kwadraty, wielomiany, luki, przybliżenia π(x), nieredukowalność) oraz wizualizacje renderowane na GPU.

### Co nowego
- **Badania → Nieredukowalność**, pięć podzakładek, z przyciskami otwierającymi repozytorium i jego artykuł:
  - **Podstawy i atomy:** dla modułów lo..hi każdy moduł dostaje podstawę m / nwd(P, m) bez tworzenia P (dla 2..N dokładnie potęgi liczb pierwszych) oraz atomy przedziału.
  - **Porównanie:** dwie liczby, każda we własnym układzie bloków, porównywane wyłącznie z reszt, cyfra po cyfrze od najstarszej, z tarczą dla każdego modułu bloku.
  - **Odczyt z grzebieni:** gdzie moduł a stoi na module b, odczytane z grzebieni sech.
  - **Zakresy:** W układu, jak W skacze przy zmianie parametru, oraz układy dopasowane do dowolnej liczby.
  - **Arytmetyka:** ⊕, ⊖, ⊗, ⊘ (dokładne albo modulo W), adres względem T, potęgi i dołączane potęgi liczb pierwszych, wszystko na resztach.
- **Testy, które widać w działaniu:** 1000 losowych porównań i 450 losowych działań, każde wypisane we własnym oknie z wynikiem odczytanym z reszt obok wyniku na liczbach całkowitych, filtrem *tylko błędy* i resztami zaznaczonego przypadku.
- **Kółko myszy:** nie przełącza już kart w całej aplikacji; nad paskiem kart przewija stronę.

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
