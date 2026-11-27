"""Adapter: plik CSV z punktami szkieletu → wynik klatki w formacie GUI.

Adapter tylko tłumaczy zapis. Kątów ani SI nie liczy, bo to zadanie zespołu.
Opis kolumn: docs/dane_csv.md. Format GUI: docs/format_danych_gui.md.
"""

import csv

# Nazwy punktów jak w docs/format_danych_gui.md. W CSV są jako kolumny {nazwa}_x i {nazwa}_y.
NAZWY_PUNKTOW = (
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
)
KOLUMNY_WYMAGANE = ("frame", "time_s") + tuple(f"{nazwa}_{os}" for nazwa in NAZWY_PUNKTOW for os in ("x", "y"))


class BladCsv(ValueError):
    """Plik CSV nie pasuje do oczekiwanego formatu. Komunikat trafia do paska stanu."""


def wczytaj_csv_landmarks(sciezka):
    """Czyta CSV i zwraca słownik {numer klatki: wynik klatki w formacie GUI}.

    Pusta para x/y to brak punktu w tej klatce. Wiersz bez żadnej wartości jest pomijany.
    Błędy zgłaszamy jako BladCsv z numerem wiersza, żeby dało się go znaleźć w pliku.
    """
    try:
        plik = open(sciezka, newline="", encoding="utf-8-sig")  # utf-8-sig zjada ewentualny znacznik BOM
    except OSError as blad:
        raise BladCsv(f"nie można otworzyć pliku: {blad}") from blad

    wyniki = {}
    with plik:
        czytnik = csv.DictReader(plik)  # każdy wiersz to słownik: nazwa kolumny → tekst komórki
        naglowki = czytnik.fieldnames or []
        brak = [kolumna for kolumna in KOLUMNY_WYMAGANE if kolumna not in naglowki]
        if brak:
            raise BladCsv(f"w pliku brakuje kolumn: {', '.join(brak)}")

        for wiersz in czytnik:
            # line_num to numer fizycznej linii w pliku (pusta linia też się liczy), więc komunikat wskaże właściwe miejsce
            numer_wiersza = czytnik.line_num
            # DictReader wrzuca wartości ponad nagłówek pod klucz None (jako listę), a brakujące daje None
            nadmiar = wiersz.pop(None, None) or []
            if all(_pusta(tekst) for tekst in [*wiersz.values(), *nadmiar]):
                continue  # pusty wiersz (same przecinki albo pusta linia) nic nie wnosi
            if nadmiar or any(tekst is None for tekst in wiersz.values()):
                raise BladCsv(f"wiersz {numer_wiersza} ma inną liczbę kolumn niż nagłówek")
            wynik = _wiersz_na_wynik(wiersz, numer_wiersza)
            numer = wynik["frame_idx"]
            if numer in wyniki:
                raise BladCsv(f"wiersz {numer_wiersza}: numer klatki {numer} powtarza się")
            wyniki[numer] = wynik

    if not wyniki:
        raise BladCsv("plik nie zawiera żadnych wierszy z danymi")
    return wyniki


def _wiersz_na_wynik(wiersz, numer_wiersza):
    """Zamienia jeden wiersz CSV na wynik klatki. Kąty i SI zostają None."""
    numer = int(_liczba(wiersz["frame"], "frame", numer_wiersza))
    czas = _liczba(wiersz["time_s"], "time_s", numer_wiersza)

    landmarks = {}
    for nazwa in NAZWY_PUNKTOW:
        x = _komorka(wiersz[f"{nazwa}_x"])
        y = _komorka(wiersz[f"{nazwa}_y"])
        if x is None and y is None:
            continue  # punktu nie ma w tej klatce
        if x is None or y is None:
            # Połowa pary to uszkodzenie, a nie brak punktu, więc zgłaszamy błąd
            raise BladCsv(f"wiersz {numer_wiersza}: punkt {nazwa} ma tylko jedną współrzędną")
        # Trzeci element to visibility. Zapis zespołu go nie ma, więc None (GUI rysuje wtedy punkt)
        landmarks[nazwa] = (
            _liczba(x, f"{nazwa}_x", numer_wiersza),
            _liczba(y, f"{nazwa}_y", numer_wiersza),
            None,
        )

    return {
        "frame_idx": numer,
        "timestamp": czas,  # czas z zegara kamery, nie z numeru klatki (odstępy są nierówne)
        "angles": None,
        "si": None,
        "landmarks": landmarks or None,  # cały wiersz bez punktów = brak osoby w kadrze
    }


def _pusta(tekst):
    """True dla komórki pustej albo brakującej (None)."""
    return tekst is None or tekst.strip() == ""


def _komorka(tekst):
    """Tekst komórki bez spacji. Pusta komórka daje None."""
    tekst = tekst.strip()
    return tekst if tekst else None


def _liczba(tekst, kolumna, numer_wiersza):
    """Zamienia tekst na liczbę. Pusta albo nieliczbowa komórka to czytelny BladCsv."""
    wartosc = _komorka(tekst)
    if wartosc is None:
        raise BladCsv(f"wiersz {numer_wiersza}: kolumna {kolumna} jest pusta")
    try:
        return float(wartosc)
    except ValueError:
        raise BladCsv(f"wiersz {numer_wiersza}: kolumna {kolumna} nie jest liczbą ({wartosc!r})") from None
