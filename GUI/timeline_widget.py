import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor

from GUI.kolory import (
    PROG_ALARMU_DOMYSLNY,
    PROG_OSTRZEZENIA_DOMYSLNY,
    POZIOM_ALARM,
    POZIOM_OK,
    POZIOM_UWAGA,
)
from GUI.gui_data_format import DEFAULT_JOINTS
from GUI.side_panel import NAZWY_STAWOW

# Kolory krzywej SI i linii progów wg poziomu. Są jaskrawe, żeby były widoczne na białym tle.
KOLOR_WYKRESU = {
    POZIOM_OK: "#00c853",  # jaskrawy zielony: SI poniżej progu uwagi
    POZIOM_UWAGA: "#ffc400",  # żółty: SI od uwagi do alarmu
    POZIOM_ALARM: "#ff1744",  # mocny czerwony: SI od alarmu
}

# Przezroczystość (0–255) pasa zdarzenia: zwykły i wyróżniony (po kliknięciu na liście)
PRZEZROCZYSTOSC_PASA = 60
PRZEZROCZYSTOSC_WYROZNIONEGO = 150


def _pedzel(kolor, przezroczystosc):
    """Pędzel (brush) do wypełnienia pasa: kolor z przezroczystością."""
    barwa = QColor(kolor)
    barwa.setAlpha(przezroczystosc)
    return pg.mkBrush(barwa)


def _z_sasiadami(maska):
    """Rozszerza maskę punktów o ich sąsiadów (o jeden punkt w lewo i w prawo).

    Dzięki temu krzywa danego poziomu zawiera też punkt z sąsiedniego poziomu tuż przy granicy.
    Odcinek między nimi się rysuje, więc linia nie urywa się przy zmianie koloru.
    """
    rozszerzona = maska.copy()
    rozszerzona[1:] |= maska[:-1]
    rozszerzona[:-1] |= maska[1:]
    return rozszerzona


def _zakres_y(si, alarm):
    """Zakres osi Y jako (dół, góra). Każda strona liczona osobno, każda z 10 % zapasu, najwyżej ±100 %.

    Góra: najwyższa wartość albo próg alarmu, jeśli jest wyżej. Dół: najniższa wartość, ale zawsze
    trochę pod zerem (co najmniej −2 %), żeby linia 0 % nie leżała na samej krawędzi wykresu.
    Gdy nic nie leży poniżej zera, dół jest tylko takim zapasem, więc połowa wykresu nie jest pusta.
    """
    skonczone = si[np.isfinite(si)]  # NaN (brak danych) pomijamy
    najwyzsza = max(float(skonczone.max()) if skonczone.size else 0.0, alarm, 1.0)
    najnizsza = min(float(skonczone.min()) if skonczone.size else 0.0, 0.0)
    gora = min(100.0, najwyzsza * 1.1)
    dol = max(-100.0, min(najnizsza * 1.1, -2.0))
    return dol, gora


def _klucz_zdarzenia(zdarzenie):
    """Pozwala rozpoznać to samo zdarzenie: staw i czas startu."""
    return zdarzenie.get("joint"), zdarzenie.get("start")


class TimelineWidget(pg.PlotWidget):
    """Wykres SI w czasie: krzywa, progi, kursor i pasy zdarzeń (na bazie pyqtgraph PlotWidget)."""

    # Sygnał wysyłany po kliknięciu w wykres: czas w sekundach (float)
    kliknieto_czas = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)  # konstruktor PlotWidget; bez tego wykres się nie zbuduje
        self.setMinimumSize(80, 60)  # żeby splitter nie zwinął panelu do zera

        self.setBackground("w")
        self.showGrid(x=True, y=True, alpha=0.3)
        self.setLabel("bottom", "Czas", units="s")
        self.setLabel("left", "Wskaźnik symetrii SI", units="%")

        # Linia zerowa = 0 % (pełna symetria)
        self.addItem(pg.InfiniteLine(angle=0, movable=False, pen=pg.mkPen(color="#555555", width=1)))

        # Kursor czasu (przesuwa go ustaw_kursor)
        self._kursor = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen(color="#d62728", width=2))
        self.addItem(self._kursor)

        # Poziome linie progów: „Uwaga” i „Alarm”. Przesuwamy je metodą set_thresholds.
        self._linia_uwagi = self._utworz_linie_progu("Uwaga", KOLOR_WYKRESU[POZIOM_UWAGA])
        self._linia_alarmu = self._utworz_linie_progu("Alarm", KOLOR_WYKRESU[POZIOM_ALARM])

        # Osobna krzywa na każdy poziom; punkty spoza poziomu są NaN
        self._krzywe = {
            POZIOM_OK: self.plot(pen=pg.mkPen(color=KOLOR_WYKRESU[POZIOM_OK], width=2)),
            POZIOM_UWAGA: self.plot(pen=pg.mkPen(color=KOLOR_WYKRESU[POZIOM_UWAGA], width=2)),
            POZIOM_ALARM: self.plot(pen=pg.mkPen(color=KOLOR_WYKRESU[POZIOM_ALARM], width=2)),
        }
        self._progi = (PROG_OSTRZEZENIA_DOMYSLNY, PROG_ALARMU_DOMYSLNY)  # (uwaga, alarm) w procentach
        self._ostatnie_dane = (np.array([]), np.array([]))  # pamiętamy, żeby przerysować po zmianie progów

        # Pasy zdarzeń: lista wpisów {"zdarzenie", "kolor", "pas", "podpis"}
        self._pasy = []

        # Kliknięcia na całej scenie (wykres i osie). Odfiltrowujemy je w _klikniecie.
        self.scene().sigMouseClicked.connect(self._klikniecie)
        # Podpisy zdarzeń mają stać u góry wykresu, więc przesuwamy je, gdy zmienia się zakres Y
        self.plotItem.vb.sigYRangeChanged.connect(lambda *_: self._przesun_podpisy())

    # ------------------------------------------------------------------
    # Metody publiczne, wywoływane przez MainWindow
    # ------------------------------------------------------------------
    def set_data(self, times, si_values):
        """Ustawia dane krzywej SI.

        times     – lista lub tablica czasów w sekundach (oś X)
        si_values – lista lub tablica wartości SI w procentach (oś Y), mogą być ujemne
        """
        self._ostatnie_dane = (np.asarray(times, dtype=float), np.asarray(si_values, dtype=float))
        self._rysuj()

    def _rysuj(self):
        """Rysuje krzywą w kolorach poziomów wg progów (te same reguły co kolory.ocena_si)."""
        times, si = self._ostatnie_dane
        warning, alarm = self._progi
        poziomy = {
            POZIOM_ALARM: si >= alarm,
            POZIOM_UWAGA: (si >= warning) & (si < alarm),
            POZIOM_OK: si < warning,
        }
        for poziom, krzywa in self._krzywe.items():
            wartosci = np.where(_z_sasiadami(poziomy[poziom]), si, np.nan)
            krzywa.setData(times, wartosci, connect="finite")
        dol, gora = _zakres_y(si, alarm)
        self.setYRange(dol, gora, padding=0)

    def ustaw_zakres_czasu(self, dlugosc_s):
        """Ustawia oś X od 0 do długości filmu w sekundach. None przywraca automatyczny zakres."""
        if dlugosc_s is None:
            self.enableAutoRange(axis=pg.ViewBox.XAxis)
        else:
            self.setXRange(0, dlugosc_s, padding=0)

    def ustaw_kursor(self, czas_s):
        """Przesuwa pionową linię kursora na podany czas w sekundach."""
        self._kursor.setPos(czas_s)

    def set_thresholds(self, warning, alarm):
        """Przesuwa linie progów na podane wartości SI w procentach."""
        self._linia_uwagi.setPos(warning)
        self._linia_alarmu.setPos(alarm)
        self._progi = (warning, alarm)
        self._rysuj()  # kolor krzywej zależy od progów, więc przerysowujemy od razu, także w pauzie

    def ustaw_opis_stawow(self, stawy):
        """Tytuł wykresu mówi, z jakich stawów liczona jest krzywa SI (wybór w panelu ustawień)."""
        if not stawy:
            opis = "brak wybranych stawów"
        elif len(stawy) == len(DEFAULT_JOINTS):
            opis = "średnia ze wszystkich stawów"
        elif len(stawy) == 1:
            opis = f"tylko: {NAZWY_STAWOW.get(stawy[0], stawy[0])}"
        else:
            opis = "średnia z: " + ", ".join(NAZWY_STAWOW.get(s, s) for s in stawy)
        self.setTitle(f"Krzywa SI – {opis}")

    def dodaj_zdarzenie(self, zdarzenie):
        """Pas od początku do końca zdarzenia z podpisem stawu."""
        kolor = KOLOR_WYKRESU.get(zdarzenie.get("level"), KOLOR_WYKRESU[POZIOM_UWAGA])
        pas = pg.LinearRegionItem(
            values=(zdarzenie["start"], zdarzenie["end"]),
            brush=_pedzel(kolor, PRZEZROCZYSTOSC_PASA),
            hoverBrush=_pedzel(kolor, PRZEZROCZYSTOSC_PASA),  # bez zmiany koloru po najechaniu myszą
            pen=pg.mkPen(color=kolor, width=1),
            movable=False,
        )
        pas.setZValue(-5)  # pas idzie pod krzywą SI, żeby jej nie zasłaniał

        podpis = pg.TextItem(NAZWY_STAWOW.get(zdarzenie["joint"], zdarzenie["joint"]), color=kolor, anchor=(0, 0))
        # ignoreBounds=True: pas i podpis nie zmieniają zakresu osi Y (inaczej krzywa się spłaszcza)
        self.addItem(pas, ignoreBounds=True)
        self.addItem(podpis, ignoreBounds=True)
        self._pasy.append({"zdarzenie": zdarzenie, "kolor": kolor, "pas": pas, "podpis": podpis})
        self._przesun_podpisy()

    def wyroznij_zdarzenie(self, zdarzenie):
        """Pogrubia pas wybranego zdarzenia (po kliknięciu na liście). None zdejmuje wyróżnienie."""
        klucz = _klucz_zdarzenia(zdarzenie) if zdarzenie is not None else None
        for wpis in self._pasy:
            wyrozniony = klucz is not None and _klucz_zdarzenia(wpis["zdarzenie"]) == klucz
            przezroczystosc = PRZEZROCZYSTOSC_WYROZNIONEGO if wyrozniony else PRZEZROCZYSTOSC_PASA
            wpis["pas"].setBrush(_pedzel(wpis["kolor"], przezroczystosc))

    def wyczysc_zdarzenia(self):
        """Usuwa wszystkie pasy i podpisy z wykresu."""
        for wpis in self._pasy:
            self.removeItem(wpis["pas"])
            self.removeItem(wpis["podpis"])
        self._pasy = []

    # ------------------------------------------------------------------
    # Pomocnicze
    # ------------------------------------------------------------------
    def _przesun_podpisy(self):
        # Podpisy zdarzeń trzymamy u góry widocznego obszaru (wartość Y zmienia się z zakresem)
        gora = self.plotItem.vb.viewRange()[1][1]
        for wpis in self._pasy:
            wpis["podpis"].setPos(wpis["zdarzenie"]["start"], gora)

    def _utworz_linie_progu(self, podpis, kolor):
        # Przerywana pozioma linia z podpisem po lewej stronie wykresu
        linia = pg.InfiniteLine(
            angle=0,
            movable=False,
            pen=pg.mkPen(color=kolor, width=1.5, style=Qt.PenStyle.DashLine),
            label=podpis,
            labelOpts={"position": 0.02, "color": kolor},
        )
        self.addItem(linia)
        return linia

    def _klikniecie(self, zdarzenie):
        # Reagujemy tylko na lewy przycisk i tylko na kliknięcie w obszar wykresu (nie w osie)
        if zdarzenie.button() != Qt.MouseButton.LeftButton:
            return
        vb = self.plotItem.vb  # ViewBox to obszar, w którym rysuje się krzywa
        if not vb.sceneBoundingRect().contains(zdarzenie.scenePos()):
            return
        # Zamieniamy położenie myszy (piksele) na współrzędne wykresu (sekundy)
        punkt = vb.mapSceneToView(zdarzenie.scenePos())
        self.kliknieto_czas.emit(float(punkt.x()))