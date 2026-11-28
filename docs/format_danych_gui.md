# Format danych dla GUI

GUI pokazuje wyniki klatka po klatce. Ten dokument opisuje, co kod analizy ma zwracać, żeby okno działało.

Format jest wewnętrzny dla naszego programu. Zespół go nie musi znać: jego kod zwraca wyniki, a `PotokAnaliza` (w `GUI/potok.py`) tłumaczy je na ten format.

## Co jest wymagane

Żeby okno działało, kod analizy musi dostarczać dla każdej klatki słownik z tymi kluczami:

| Klucz | Typ | Po co | Wymagane? |
|---|---|---|---|
| `frame_idx` | liczba całkowita | numer klatki, od 0 | tak |
| `timestamp` | liczba (sekundy) | czas klatki w nagraniu | tak |
| `si` | słownik | symetria: `total` i wartości dla stawów | tak, dla wykresu |
| `angles` | słownik albo `None` | kąty L/P w stawach, do tabeli | nie (zostanie `—`) |
| `landmarks` | słownik albo `None` | punkty ciała, do szkieletu | nie (brak szkieletu) |

Brakujące pola nie wywracają programu: GUI pokazuje wtedy `—` albo nic nie rysuje. Ale wykres i zdarzenia działają tylko wtedy, gdy `si` jest podane.

Dodatkowo, dla całego filmu, `przelicz_lekkie` musi zwrócić listę zdarzeń (może być pusta).

## Przykład wyniku jednej klatki

```python
{
    "frame_idx": 123,                     # numer klatki, od 0
    "timestamp": 4.10,                    # czas w sekundach z nagrania
    "angles": {                           # kąty w stopniach, None gdy brak
        "shoulder": {"L": 98.0, "R": 95.5},
        "elbow": {"L": 145.2, "R": 120.8},
        "hip": None,
        "knee": {"L": 170.1, "R": 168.9},
    },
    "si": {                               # symetria w %, 0 = pełna symetria
        "shoulder": 2.5,
        "elbow": 18.3,
        "hip": None,
        "knee": 0.7,
        "total": 7.0,                     # średnia z wybranych stawów
    },
    "landmarks": {                        # punkty ciała, patrz niżej
        "left_shoulder": (0.42, 0.30, 0.95),
        # ... pozostałe 11 punktów
    },
}
```

Stawy to: `shoulder`, `elbow`, `hip`, `knee`. Strony to `L` i `R`.

## Punkty ciała (`landmarks`)

Słownik: nazwa punktu → `(x, y, visibility)`. Potrzebne nazwy (12 punktów):

`left_shoulder`, `right_shoulder`, `left_elbow`, `right_elbow`, `left_wrist`, `right_wrist`, `left_hip`, `right_hip`, `left_knee`, `right_knee`, `left_ankle`, `right_ankle`

- `x` i `y`: położenie na obrazie, jako ułamek szerokości i wysokości. `(0, 0)` to lewy górny róg, `(1, 1)` prawy dolny. Wartości mogą wyjść poza 0–1, gdy punkt jest poza kadrem.
- `visibility`: pewność od 0 do 1, albo `None`, gdy nieznana. GUI nie rysuje punktów z pewnością poniżej 0,5.
- `left` i `right` to strony **osoby**, nie obrazu. Osoba stojąca twarzą do kamery ma lewą rękę po prawej stronie obrazu.
- Brak punktu: klucz nie występuje albo ma wartość `None`. Brak całej osoby w kadrze: `landmarks` = `None`.

## Zdarzenie asymetrii

Zdarzenie to słownik, który zwraca `przelicz_lekkie` razem z wynikami:

```python
{"start": 3.2, "end": 4.9, "joint": "elbow", "level": "warning", "si_max": 24.1}
```

- Osobne zdarzenie dla każdego stawu.
- Zaczyna się, gdy SI stawu osiągnie próg uwagi, a kończy pierwszą klatką poniżej progu.
- `level` to `"alarm"`, gdy największe SI w zdarzeniu osiągnęło próg alarmu, w przeciwnym razie `"warning"`.
- Zdarzenia krótsze niż 0,3 s pomijamy.

## Ustawienia

Okno przekazuje do potoku słownik `ustawienia`:

```python
{
    "thresholds": {"warning": 10.0, "alarm": 20.0},   # progi SI w %
    "exercise_type": "simultaneous",                  # albo "alternating"
    "joints": ["shoulder", "elbow", "hip", "knee"],   # wybrane stawy
}
```

Zmiana progów lub stawów nie uruchamia analizy od nowa. Kod analizy dostaje tylko wyniki zapisane wcześniej i nowe ustawienia (patrz `przelicz_lekkie`).

## Dane z pliku CSV

Program może wczytać CSV z punktami zamiast liczyć je z obrazu. Plik musi mieć kolumny:

- `frame`: numer klatki, od 0,
- `time_s`: czas w sekundach (z zegara nagrania, nie `numer / fps`, bo odstępy mogą być nierówne),
- `{nazwa}_x` i `{nazwa}_y` dla każdego z 12 punktów, np. `left_shoulder_x`, `left_shoulder_y`.

Pusta para `x`/`y` oznacza brak punktu w tej klatce. Program nie zna kątów ani SI w CSV, więc są puste (`None`) i nie ma zdarzeń.

CSV o tej samej nazwie co film (np. `film.csv` obok `film.MP4`) wczytuje się automatycznie. Inny plik można wybrać przyciskiem „Wczytaj CSV…”.

## Ograniczenia

- Numery klatek zaczynają się od 0 i rosną bez przerw. Brakujące klatki widać na wykresie jako przerwę, ale lepiej ich nie zostawiać.
- Czasy (`timestamp`) muszą rosnąć.
- `si.total` i zdarzenia liczy kod analizy; okno tylko je pokazuje.
