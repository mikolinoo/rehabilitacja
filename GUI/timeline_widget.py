import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal

from GUI.kolory import (
    PROG_ALARMU_DOMYSLNY,
    PROG_OSTRZEZENIA_DOMYSLNY,
    POZIOM_ALARM,
    POZIOM_OK,
    POZIOM_UWAGA,
)

# Kolory krzywej SI i linii progów wg poziomu. Są jaskrawe, żeby były widoczne na białym tle.
KOLOR_WYKRESU = {
    POZIOM_OK: "#00c853",  # jaskrawy zielony: SI poniżej progu uwagi
    POZIOM_UWAGA: "#ffc400",  # żółty: SI od uwagi do alarmu
    POZIOM_ALARM: "#ff1744",  # mocny czerwony: SI od alarmu
}


class TimelineWidget(pg.PlotWidget):
    """Wykres surowych wartości SI (wskaźnika symetrii) w czasie nagrania.

    PlotWidget to gotowy widżet wykresu z biblioteki pyqtgraph, z osiami, siatką
    i obszarem do rysowania. Dziedziczymy po nim, żeby nasza klasa sama była
    wykresem i miała dodatkowe metody (np. set_data).
    """

    # Sygnał wysyłany po kliknięciu w wykres: czas w sekundach (float)
    kliknieto_czas = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)  # konstruktor PlotWidget; bez tego wykres się nie zbuduje
        self.setMinimumSize(80, 60)  # żeby splitter nie zwinął panelu do zera

        # Wygląd: białe tło, siatka i opisy osi.
        # Zakresu osi Y nie ustawiamy na sztywno. pyqtgraph dopasowuje go do danych,
        # więc wartości ujemne też będą widoczne.
        self.setBackground("w")
        self.showGrid(x=True, y=True, alpha=0.3)
        self.setLabel("bottom", "Czas", units="s")
        self.setLabel("left", "Wskaźnik symetrii SI", units="%")

        # Linia zerowa oznacza 0 %, czyli pełną symetrię. To punkt odniesienia, a nie limit.
        # Dzięki niej od razu widać, które wartości są dodatnie, a które ujemne.
        self.addItem(pg.InfiniteLine(angle=0, movable=False, pen=pg.mkPen(color="#555555", width=1)))

        # Pionowa linia kursora pokazuje, w którym miejscu nagrania jest odtwarzanie.
        # Nie da się jej przeciągnąć myszą, przesuwamy ją metodą ustaw_kursor.
        self._kursor = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen(color="#d62728", width=2))
        self.addItem(self._kursor)

        # Poziome linie progów: „Uwaga” i „Alarm”. Przesuwamy je metodą set_thresholds.
        self._linia_uwagi = self._utworz_linie_progu("Uwaga", KOLOR_WYKRESU[POZIOM_UWAGA])
        self._linia_alarmu = self._utworz_linie_progu("Alarm", KOLOR_WYKRESU[POZIOM_ALARM])

        # Krzywa SI jest na początku pusta. Dane dostaje przez set_data().
        # Kolor zależy od poziomu: każdy poziom to osobna krzywa, a punkty spoza poziomu są NaN (niewidoczne).
        self._krzywe = {
            POZIOM_OK: self.plot(pen=pg.mkPen(color=KOLOR_WYKRESU[POZIOM_OK], width=2)),
            POZIOM_UWAGA: self.plot(pen=pg.mkPen(color=KOLOR_WYKRESU[POZIOM_UWAGA], width=2)),
            POZIOM_ALARM: self.plot(pen=pg.mkPen(color=KOLOR_WYKRESU[POZIOM_ALARM], width=2)),
        }
        self._progi = (PROG_OSTRZEZENIA_DOMYSLNY, PROG_ALARMU_DOMYSLNY)  # (uwaga, alarm) w procentach
        self._ostatnie_dane = (np.array([]), np.array([]))  # pamiętamy, żeby przerysować po zmianie progów

        # Kliknięcia na całej scenie (wykres i osie). Odfiltrowujemy je w _klikniecie.
        self.scene().sigMouseClicked.connect(self._klikniecie)

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
        """Rysuje krzywą w kolorach poziomów wg aktualnych progów."""
        times, si = self._ostatnie_dane
        warning, alarm = self._progi
        # Te same reguły co w kolory.ocena_si: alarm ma pierwszeństwo.
        # NaN (brak danych) nie spełnia żadnego porównania, więc zostaje przerwa w linii.
        poziomy = {
            POZIOM_ALARM: si >= alarm,
            POZIOM_UWAGA: (si >= warning) & (si < alarm),
            POZIOM_OK: si < warning,
        }
        for poziom, krzywa in self._krzywe.items():
            wartosci = np.where(poziomy[poziom], si, np.nan)  # poza swoim poziomem punkt znika
            # setData zastępuje poprzednią krzywą; connect="finite" robi przerwy zamiast prostych do zera
            krzywa.setData(times, wartosci, connect="finite")

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

    # ------------------------------------------------------------------
    # Pomocnicze
    # ------------------------------------------------------------------
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
