"""Rysowanie szkieletu na klatce wideo. Tylko prezentacja: dostaje gotowe punkty i poziomy SI.

Punkty są w układzie obrazu 0–1 (ułamek szerokości i wysokości). Tu zamieniamy je na piksele i rysujemy.
Nazwy punktów: docs/format_danych_gui.md.
"""

import cv2

from GUI.gui_data_format import DEFAULT_JOINTS
from GUI.kolory import POZIOM_ALARM, POZIOM_BRAK, POZIOM_OK, POZIOM_UWAGA, ocena_si

# Kolory poziomów w zapisie hex (#rrggbb), takie same jak krzywa SI na wykresie
KOLORY_HEX = {
    POZIOM_OK: "#00c853",
    POZIOM_UWAGA: "#ffc400",
    POZIOM_ALARM: "#ff1744",
    POZIOM_BRAK: "#9e9e9e",  # szary: staw nieanalizowany albo brak danych
}


def hex_na_bgr(kolor):
    """Zamienia '#rrggbb' na krotkę (niebieski, zielony, czerwony), czyli kolejność BGR.

    OpenCV zapisuje kolory jako BGR, a nie RGB. Gdybyśmy podali RGB, czerwony byłby niebieski.
    """
    czerwony = int(kolor[1:3], 16)
    zielony = int(kolor[3:5], 16)
    niebieski = int(kolor[5:7], 16)
    return (niebieski, zielony, czerwony)


KOLORY_POZIOMOW_BGR = {poziom: hex_na_bgr(kolor) for poziom, kolor in KOLORY_HEX.items()}
KOLOR_KRESEK = (255, 255, 255)  # jeden neutralny kolor wszystkich kresek (BGR: biały)
KOLOR_KONCOWKI = KOLORY_POZIOMOW_BGR[POZIOM_BRAK]  # nadgarstki i kostki bez oceny: szare kropki

# Który staw z angles/si rysujemy jako kółka, i jakie punkty to są (lewa i prawa strona)
MAPA_STAWOW_NA_PUNKTY = {
    "shoulder": ("left_shoulder", "right_shoulder"),
    "elbow": ("left_elbow", "right_elbow"),
    "hip": ("left_hip", "right_hip"),
    "knee": ("left_knee", "right_knee"),
}

# Połączenia kresek. Każde to para nazw punktów, nie numerów z MediaPipe, więc czytelne i odporne na zmianę numeracji
POLACZENIA = [
    ("left_shoulder", "right_shoulder"),  # barki
    ("left_shoulder", "left_elbow"),  # ramię lewe
    ("left_elbow", "left_wrist"),  # przedramię lewe
    ("right_shoulder", "right_elbow"),  # ramię prawe
    ("right_elbow", "right_wrist"),  # przedramię prawe
    ("left_shoulder", "left_hip"),  # tułów lewą stroną
    ("right_shoulder", "right_hip"),  # tułów prawą stroną
    ("left_hip", "right_hip"),  # biodra
    ("left_hip", "left_knee"),  # udo lewe
    ("left_knee", "left_ankle"),  # podudzie lewe
    ("right_hip", "right_knee"),  # udo prawe
    ("right_knee", "right_ankle"),  # podudzie prawe
]

# Końcówki kończyn: rysujemy je jako małe szare kropki, bez kółka w ocenie
PUNKTY_KONCOWE = ("left_wrist", "right_wrist", "left_ankle", "right_ankle")

MIN_WIDOCZNOSC = 0.5  # punkty pewniejsze od tego są rysowane, a słabsze pomijamy
MARGINES_KADRU = 0.1  # punkt do 10 % poza krawędzią jeszcze rysujemy; dalej to błąd, więc pomijamy


def kolory_stawow(si, analizowane, warning, alarm):
    """Kolor kółka dla każdego stawu (BGR). Poziom liczy ocena_si wg aktualnych progów.

    si         – słownik SI z wyniku klatki (albo None)
    analizowane – stawy wybrane w ustawieniach; pozostałe są szare
    """
    kolory = {}
    for staw in DEFAULT_JOINTS:
        wartosc = (si or {}).get(staw)
        if staw not in analizowane:
            poziom = POZIOM_BRAK  # staw odznaczony w ustawieniach
        else:
            poziom, _, _ = ocena_si(wartosc, warning, alarm)  # None (brak stawu) też da POZIOM_BRAK
        kolory[staw] = KOLORY_POZIOMOW_BGR[poziom]
    return kolory


def rysuj_szkielet(klatka, landmarks, kolory):
    """Zwraca NOWĄ klatkę z narysowanym szkieletem. Oryginał (klatka) zostaje bez zmian.

    klatka     – obraz BGR (numpy, wysokość × szerokość × 3)
    landmarks  – słownik nazwa → (x, y, visibility) albo None, gdy nie ma osoby
    kolory     – słownik staw → kolor BGR (z kolory_stawow)
    """
    obraz = klatka.copy()  # rysujemy na kopii, żeby kolejna klatka nie dostała kresek z poprzedniej
    if not landmarks:
        return obraz  # brak osoby w kadrze: wracamy z samą klatką

    wysokosc, szerokosc = obraz.shape[:2]
    # Grubości zależą od rozmiaru obrazu, żeby na małym i dużym oknie szkielet wyglądał podobnie
    krawedz = min(wysokosc, szerokosc)
    grubosc = max(1, round(krawedz / 200))
    promien = max(3, round(krawedz / 80))

    # Zamieniamy punkty 0–1 na piksele. Punkty bez pewności albo poza kadrem dostają None.
    piksele = {}
    for nazwa, punkt in landmarks.items():
        px = _na_piksele(punkt, szerokosc, wysokosc)
        if px is not None:
            piksele[nazwa] = px

    # Najpierw kreski, potem kółka, żeby kółka leżały na wierzchu
    for a, b in POLACZENIA:
        if a in piksele and b in piksele:  # kreskę rysujemy tylko, gdy oba końce istnieją
            cv2.line(obraz, piksele[a], piksele[b], KOLOR_KRESEK, grubosc, cv2.LINE_AA)

    for staw, nazwy in MAPA_STAWOW_NA_PUNKTY.items():
        kolor = kolory.get(staw, KOLOR_KRESEK)
        for nazwa in nazwy:
            if nazwa in piksele:
                _kolko(obraz, piksele[nazwa], promien, kolor)

    for nazwa in PUNKTY_KONCOWE:
        if nazwa in piksele:
            _kolko(obraz, piksele[nazwa], max(2, promien // 2), KOLOR_KONCOWKI)

    return obraz


def _na_piksele(punkt, szerokosc, wysokosc):
    """(x, y) w pikselach albo None, gdy punkt nie istnieje, jest słaby albo daleko poza kadrem."""
    if punkt is None:
        return None
    x, y, widocznosc = punkt
    if widocznosc is not None and widocznosc < MIN_WIDOCZNOSC:
        return None  # MediaPipe nie jest pewny tego punktu
    if not (-MARGINES_KADRU <= x <= 1 + MARGINES_KADRU and -MARGINES_KADRU <= y <= 1 + MARGINES_KADRU):
        return None  # punkt poza kadrem (błąd albo osoba wyszła z kadru)
    # x to ułamek szerokości, więc mnożymy przez szerokość (nie wysokość!)
    return round(x * szerokosc), round(y * wysokosc)


def _kolko(obraz, srodek, promien, kolor):
    """Wypełnione kółko z cienkim czarnym obrysem, żeby kolor było widać na jasnym tle."""
    cv2.circle(obraz, srodek, promien, kolor, -1, cv2.LINE_AA)
    cv2.circle(obraz, srodek, promien, (0, 0, 0), 1, cv2.LINE_AA)
