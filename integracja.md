# Podłączenie kodu analizy

## Jak to działa teraz

1. Użytkownik otwiera film. Program czyta go klatka po klatce.
2. Każdą klatkę przekazuje do 'potoku' (fragmentu kodu, który liczy wynik). Potok to atrapa (zmyślone liczby) albo odczyt z pliku CSV.
3. Gdy cały film jest policzony, program liczy średnią symetrii i zdarzenia. To robi się szybko, więc zmiana progu działa od razu, bez ponownego liczenia klatek.
4. Okno tylko wyświetla gotowe wyniki.

Potok wybiera funkcja `wybierz_potok` w pliku `GUI/potok.py`. Obecnie: jeśli obok filmu leży CSV o tej samej nazwie, bierze CSV, a jeśli nie, atrapę.

## Co brakuje

Funkcję, która dla **jednej klatki** obrazu zwraca:
- położenie punktów ciała (12 punktów, jak w `olaf/InzRehb.py`),
- kąty w stawach lewej i prawej strony,
- symetrię (SI) dla każdego stawu.

Funkcja nie musi zapisywać CSV ani pokazywać okna z kamerą. Ma zwrócić wynik jako słownik w formacie opisanym w `docs/format_danych_gui.md`.

## Co zrobić w programie (krok po kroku)

1. Wklej kod analizy do nowego pliku `GUI/potok_analiza.py`.
2. W `GUI/potok.py` dopisz klasę `PotokAnaliza`. Dziedziczy po `PotokBazowy`, więc musi mieć trzy metody:
   - `opis_zrodla` – krótka informacja dla paska stanu (typ, nazwa),
   - `analizuj_klatke` – weź klatkę, wywołaj funkcję z kodu analizy i zwróć wynik w formacie GUI,
   - `przelicz_lekkie` – zwróć średnią SI i zdarzenia z wyników całego filmu (liczy je kod analizy).
3. Wczytaj model rozpoznawania (MediaPipe) **raz**, w konstruktorze klasy, nie przy każdej klatce. Inaczej program będzie bardzo wolny.
4. W funkcji `wybierz_potok` dodaj warunek, kiedy używać `PotokAnaliza`.
5. Uruchom program na krótkim filmie i sprawdź, czy punkty pojawiają się na obrazie, a wykres i zdarzenia mają sens.

Po udanym podłączeniu usuń atrapę (`PotokAtrapa` i jej funkcje w `potok.py`). Odczyt CSV usuń, jeśli nie będzie już potrzebny.

## Do ustalenia

- Kto czyta film: program (OpenCV) czy kod analizy? Wystarczy, że dostanie klatki jako obraz.
- Czy zapamiętywać kąty i punkty wszystkich klatek? Dziś przy odtwarzaniu klatka jest liczona ponownie, przy MediaPipe to podwójna praca
- Jak zapisać sesję: film, dane i ustawienia pod jedną nazwą?
