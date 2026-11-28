"""Format danych przekazywanych z workera do GUI. Opis: docs/format_danych_gui.md."""

# Stawy, dla których atrapa liczy kąty i SI.
DEFAULT_JOINTS = ["shoulder", "elbow", "hip", "knee"]

def bezpieczny_odczyt(dane, *klucze):
    """Wchodzi w zagnieżdżony słownik i zwraca wartość albo None, gdy klucza brak."""
    biezacy = dane
    for klucz in klucze:
        if not isinstance(biezacy, dict) or klucz not in biezacy:
            return None  # brakuje klucza, więc nie ma czego czytać
        biezacy = biezacy[klucz]
    return biezacy  # może być None, jeśli tak było w danych
