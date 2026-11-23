"""Kolory i poziomy oceny SI. Tylko prezentacja, bez obliczeń."""

# Domyślne progi SI w procentach
PROG_OSTRZEZENIA_DOMYSLNY = 10.0
PROG_ALARMU_DOMYSLNY = 20.0

POZIOM_OK = "ok"
POZIOM_UWAGA = "warning"
POZIOM_ALARM = "alarm"
POZIOM_BRAK = "brak"

# (kolor tła, kolor tekstu)
KOLORY = {
    POZIOM_OK: ("#c8e6c9", "#1b5e20"),
    POZIOM_UWAGA: ("#ffe082", "#6d4c00"),
    POZIOM_ALARM: ("#ef9a9a", "#7f0000"),
    POZIOM_BRAK: ("#e0e0e0", "#555555"),
}

TEKST_STATUSU = {
    POZIOM_OK: "OK",
    POZIOM_UWAGA: "Uwaga",
    POZIOM_ALARM: "Alarm",
    POZIOM_BRAK: "—",
}


def ocena_si(si, warning=PROG_OSTRZEZENIA_DOMYSLNY, alarm=PROG_ALARMU_DOMYSLNY):
    """Zwraca (poziom, (kolor_tla, kolor_tekstu), tekst_statusu) dla wartości SI.

    Alarm sprawdzamy pierwszy, więc wartość równa progowi trafia do wyższego poziomu.
    """
    if si is None:
        poziom = POZIOM_BRAK
    elif si >= alarm:
        poziom = POZIOM_ALARM
    elif si >= warning:
        poziom = POZIOM_UWAGA
    else:
        poziom = POZIOM_OK
    return poziom, KOLORY[poziom], TEKST_STATUSU[poziom]
