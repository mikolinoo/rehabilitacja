"""Potoki analizy: skąd biorą się wyniki klatek.

Każdy potok ma: analizuj_klatke (wynik jednej klatki) i przelicz_lekkie (średnia SI i zdarzenia).
Wybór potoku: wybierz_potok.
"""

import math
from abc import ABC, abstractmethod
from pathlib import Path

from GUI.adapter_csv import BladCsv, wczytaj_csv_landmarks
from GUI.gui_data_format import DEFAULT_JOINTS
from GUI.kolory import PROG_ALARMU_DOMYSLNY, PROG_OSTRZEZENIA_DOMYSLNY

MIN_CZAS_ZDARZENIA_S = 0.3  # krótsze zdarzenia pomijamy

# Parametry atrapy (wymyślone)
KAT_SRODKOWY = 120.0
AMPLITUDA_L = 40.0
AMPLITUDA_R = 25.0
OKRES_EPIZODU_S = 8.0
POCZATEK_EPIZODU_S = 5.0


class PotokBazowy(ABC):
    """Interfejs potoku: metody, które musi mieć każda wersja analizy."""

    @abstractmethod
    def opis_zrodla(self):
        """Słownik dla paska stanu: typ, nazwa, klatek, ma_katy_i_si."""

    @abstractmethod
    def analizuj_klatke(self, klatka, frame_idx, czas_s):
        """Wynik jednej klatki w formacie GUI (docs/format_danych_gui.md)."""

    @abstractmethod
    def przelicz_lekkie(self, wyniki, ustawienia):
        """Średnia SI i zdarzenia z wyników całego filmu. Zwraca (wyniki, zdarzenia)."""


class PotokCsv(PotokBazowy):
    """Punkty z CSV. Kątów i SI nie ma."""

    def __init__(self, dane, nazwa):
        self._dane = dane  # {numer klatki: wynik}
        self._nazwa = nazwa

    def opis_zrodla(self):
        return {"typ": "csv", "nazwa": self._nazwa, "klatek": len(self._dane), "ma_katy_i_si": False}

    def analizuj_klatke(self, klatka, frame_idx, czas_s):
        wiersz = self._dane.get(frame_idx)
        if wiersz is None:
            return {"frame_idx": frame_idx, "timestamp": round(czas_s, 3), "angles": None, "si": None, "landmarks": None}
        return dict(wiersz)

    def przelicz_lekkie(self, wyniki, ustawienia):
        return list(wyniki), []


class PotokAtrapa(PotokBazowy):
    """Dane zmyślone: sinusoidy kątów, SI i punkty sylwetki. Obrazu nie czyta."""

    def opis_zrodla(self):
        return {"typ": "atrapa", "nazwa": None, "klatek": None, "ma_katy_i_si": True}

    def analizuj_klatke(self, klatka, frame_idx, czas_s):
        katy = self._katy(czas_s, frame_idx)
        si = self._si(katy)
        return {
            "frame_idx": frame_idx,
            "timestamp": round(czas_s, 3),
            "angles": katy,
            "si": si,
            "landmarks": self._landmarks(katy, frame_idx),
        }

    def przelicz_lekkie(self, wyniki, ustawienia):
        stawy = analizowane_stawy(ustawienia)
        warning, alarm = progi(ustawienia)
        przeliczone = []
        for wynik in wyniki:
            si = dict(wynik["si"])
            si["total"] = srednia_si(wynik["si"], stawy)
            przeliczone.append({"frame_idx": wynik["frame_idx"], "timestamp": wynik["timestamp"], "si": si})
        zdarzenia = wykryj_zdarzenia(przeliczone, stawy, warning, alarm)
        return przeliczone, zdarzenia

    def _katy(self, t, numer):
        """Kąty L/P dla każdego stawu (sinusoidy). Co 300 klatek brak kolana na 15 klatek."""
        cykl_t = t % OKRES_EPIZODU_S
        dodatek = 0.0
        if cykl_t >= POCZATEK_EPIZODU_S:
            dlugosc = OKRES_EPIZODU_S - POCZATEK_EPIZODU_S
            dodatek = 30.0 * math.sin(math.pi * (cykl_t - POCZATEK_EPIZODU_S) / dlugosc)

        katy = {}
        for i, staw in enumerate(DEFAULT_JOINTS):
            faza = 2 * math.pi * 0.25 * t + i * 0.7
            if staw == "knee" and (numer % 300) in range(60, 75):
                katy[staw] = None
                continue
            katy[staw] = {
                "L": KAT_SRODKOWY + AMPLITUDA_L * math.sin(faza),
                "R": KAT_SRODKOWY + AMPLITUDA_R * math.sin(faza) - dodatek,
            }
        return katy

    @staticmethod
    def _si(katy):
        """SI = |L−R| / (0.5·(L+R)) · 100 dla każdego stawu; total to średnia."""
        si = {}
        dostepne = []
        for staw in DEFAULT_JOINTS:
            dane = katy.get(staw)
            if dane is None:
                si[staw] = None
                continue
            l, r = dane["L"], dane["R"]
            wartosc = abs(l - r) / (0.5 * (l + r)) * 100.0
            si[staw] = wartosc
            dostepne.append(wartosc)
        si["total"] = sum(dostepne) / len(dostepne) if dostepne else None
        return si

    def _landmarks(self, katy, numer):
        """12 punktów sylwetki w układzie 0–1 (x w prawo, y w dół). None = brak osoby."""
        if (numer % 450) in range(400, 430):
            return None
        widocznosc = 0.95
        punkty = {}
        for strona, znak in (("left", 1.0), ("right", -1.0)):
            x_bark = 0.5 + znak * 0.08
            punkty[f"{strona}_shoulder"] = (x_bark, 0.30, widocznosc)
            punkty[f"{strona}_hip"] = (0.5 + znak * 0.05, 0.55, widocznosc)
            punkty[f"{strona}_knee"] = (0.5 + znak * 0.05, 0.75, widocznosc)
            punkty[f"{strona}_ankle"] = (0.5 + znak * 0.04, 0.93, widocznosc)
            alfa = math.radians(180.0 - self._kat_lokcia(katy, strona))
            punkty[f"{strona}_elbow"] = (x_bark, 0.42, widocznosc)
            punkty[f"{strona}_wrist"] = (
                x_bark + znak * 0.12 * math.sin(alfa),
                0.42 + 0.12 * math.cos(alfa),
                widocznosc,
            )

        # Testy odporności GUI w różnych miejscach cyklu 300 klatek
        w_cyklu = numer % 300
        if w_cyklu in range(120, 135):
            del punkty["left_ankle"]
        if w_cyklu in range(200, 215):
            x, y, _ = punkty["right_wrist"]
            punkty["right_wrist"] = (x, y, 0.3)
        if w_cyklu in range(240, 250):
            _, y, vis = punkty["left_wrist"]
            punkty["left_wrist"] = (1.3, y, vis)
        return punkty

    @staticmethod
    def _kat_lokcia(katy, strona):
        """Kąt łokcia dla strony; bez łokcia – kąt środkowy."""
        dane = katy.get("elbow")
        if dane is None:
            return KAT_SRODKOWY
        return dane["L" if strona == "left" else "R"]


# Część lekka: funkcje wspólne
def analizowane_stawy(ustawienia):
    """Wybrane stawy; bez ustawień wszystkie."""
    return list(ustawienia.get("joints", DEFAULT_JOINTS))


def progi(ustawienia):
    """(uwaga, alarm) z ustawień albo wartości domyślne."""
    wartosci = ustawienia.get("thresholds") or {}
    return wartosci.get("warning", PROG_OSTRZEZENIA_DOMYSLNY), wartosci.get("alarm", PROG_ALARMU_DOMYSLNY)


def srednia_si(si, stawy):
    """Średnia SI z wybranych stawów, które mają wartość; None gdy żaden."""
    si = si or {}
    wartosci = [si[staw] for staw in DEFAULT_JOINTS if staw in stawy and si.get(staw) is not None]
    return sum(wartosci) / len(wartosci) if wartosci else None


def wykryj_zdarzenia(wyniki, stawy, warning, alarm):
    """Zdarzenia dla każdego stawu: start przy progu uwagi, koniec pod progiem."""
    zdarzenia = []
    otwarte = {}  # staw → zdarzenie, które trwa
    ostatni_czas = None
    for wynik in wyniki:
        czas = wynik["timestamp"]
        ostatni_czas = czas
        si = wynik["si"] or {}
        for staw in stawy:
            wartosc = si.get(staw)
            if wartosc is None:
                continue
            if staw in otwarte:
                zdarzenie = otwarte[staw]
                zdarzenie["si_max"] = max(zdarzenie["si_max"], wartosc)
                if wartosc < warning:
                    del otwarte[staw]
                    _dodaj_jesli_dlugie(zdarzenia, staw, zdarzenie, czas, alarm)
            elif wartosc >= warning:
                otwarte[staw] = {"start": czas, "si_max": wartosc}
    for staw, zdarzenie in otwarte.items():  # zdarzenia trwające do końca filmu
        _dodaj_jesli_dlugie(zdarzenia, staw, zdarzenie, ostatni_czas, alarm)
    return zdarzenia


def _dodaj_jesli_dlugie(zdarzenia, staw, zdarzenie, koniec, alarm):
    """Dopisuje zdarzenie, jeśli trwało dość długo."""
    if koniec - zdarzenie["start"] < MIN_CZAS_ZDARZENIA_S:
        return
    zdarzenia.append(
        {
            "start": round(zdarzenie["start"], 3),
            "end": round(koniec, 3),
            "joint": staw,
            "level": "alarm" if zdarzenie["si_max"] >= alarm else "warning",
            "si_max": round(zdarzenie["si_max"], 1),
        }
    )


def wybierz_potok(sciezka_filmu, sciezka_csv=None):
    """Wybiera potok: CSV obok filmu (lub podany) → PotokCsv, brak → PotokAtrapa."""
    if sciezka_csv is None:
        kandydat = Path(sciezka_filmu).with_suffix(".csv")
        if not kandydat.is_file():
            return PotokAtrapa()
        sciezka_csv = kandydat
    nazwa = Path(sciezka_csv).name
    try:
        dane = wczytaj_csv_landmarks(sciezka_csv)
    except BladCsv as blad:
        raise BladCsv(f"nie wczytano {nazwa}: {blad}") from blad
    return PotokCsv(dane, nazwa)
