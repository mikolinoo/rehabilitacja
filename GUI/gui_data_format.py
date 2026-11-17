"""Tymczasowy format danych GUI.

UWAGA: format TYMCZASOWY, do dostosowania przy integracji przez ADAPTER.
To NIE jest uzgodniony kontrakt zespołu. Adapter to mała funkcja, która
tłumaczy prawdziwy wynik potoku zespołu na ten format. Widżety GUI się
wtedy nie zmieniają.

Format jest LUŹNY: każde pole może być None albo nieobecne. Widżety muszą
sobie z tym poradzić (np. brak osoby w kadrze, brak jednego stawu).

Przykład wyniku jednej klatki (słownik = dict w Pythonie):

    {
        "frame_idx": 123,                     # numer klatki
        "timestamp": 4.10,                    # czas w sekundach
        "angles": {                           # kąty w stopniach, None gdy brak stawu
            "elbow": {"L": 145.2, "R": 120.8},
            "shoulder": None,
        },
        "si": {                               # wskaźnik symetrii w %, 0 = pełna symetria
            "elbow": 18.3,
            "shoulder": None,
            "total": 7.0,
        },
        "landmarks": [(x, y, visibility), ...],  # 33 punkty, x i y w zakresie 0–1
    }                                         # albo None, gdy brak osoby w kadrze

Przykład zdarzenia (asymetrii):

    {"start": 3.2, "end": 4.9, "joint": "elbow", "level": "warning", "si_max": 24.1}
"""

# Domyślna konfiguracja stawów. To tylko punkt startowy, nie twarda reguła.
DEFAULT_JOINTS = ["shoulder", "elbow", "hip", "knee"]

# Liczba punktów szkieletu w MediaPipe Pose (stała z biblioteki, nie wymysł GUI).
LICZBA_LANDMARKS = 33

# Dozwolone poziomy zdarzenia.
POZIOMY_ZDARZEN = ("warning", "alarm")


def empty_frame_result():
    """Zwraca pusty wynik klatki: wszystkie pola ustawione na None.

    Używamy go, gdy nie ma jeszcze żadnych danych, żeby widżety nie
    dostawały czegoś nieoczekiwanego.
    """
    return {
        "frame_idx": None,
        "timestamp": None,
        "angles": None,
        "si": None,
        "landmarks": None,
    }


def bezpieczny_odczyt(dane, *klucze):
    """Bezpiecznie wchodzi w zagnieżdżony słownik i zwraca wartość albo None.

    Przykład: bezpieczny_odczyt(wynik, "si", "elbow") zwraca wartość SI
    łokcia, a None, jeśli któregokolwiek klucza brakuje albo jest None.

    Dlaczego tak: bez tego każdy widżet musiałby sprawdzać każdy poziom
    osobno (`wynik["si"]["elbow"]`), a brak klucza wywracałby program.
    """
    biezacy = dane
    for klucz in klucze:
        if not isinstance(biezacy, dict) or klucz not in biezacy:
            return None  # brakuje klucza -> nie ma czego czytać
        biezacy = biezacy[klucz]
    return biezacy  # może być None, jeśli tak było w danych
