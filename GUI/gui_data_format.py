"""Format danych przekazywanych z workera do GUI. Opis: docs/format_danych_gui.md."""

# Stawy, dla których atrapa liczy kąty i SI.
DEFAULT_JOINTS = ["shoulder", "elbow", "hip", "knee"]

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
            return None  # brakuje klucza, więc nie ma czego czytać
        biezacy = biezacy[klucz]
    return biezacy  # może być None, jeśli tak było w danych
