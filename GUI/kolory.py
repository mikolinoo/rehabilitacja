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
    POZIOM_OK: ("#a5f5a5", "#0b4d0b"),  # jasny zielony tło, ciemny tekst
    POZIOM_UWAGA: ("#fff59d", "#4a3900"),  # jasny żółty
    POZIOM_ALARM: ("#ff8a80", "#7a0000"),  # jasny czerwony
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