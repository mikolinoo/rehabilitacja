import numpy as np
import pyqtgraph as pg


class TimelineWidget(pg.PlotWidget):
    """Wykres surowych wartości SI (wskaźnika symetrii) w czasie nagrania.

    PlotWidget to gotowy widżet wykresu z biblioteki pyqtgraph, z osiami, siatką
    i obszarem do rysowania. Dziedziczymy po nim, żeby nasza klasa sama była
    wykresem i miała dodatkowe metody (np. set_data).
    """

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

        # Krzywa SI jest na początku pusta. Dane dostaje przez set_data().
        self._krzywa = self.plot(pen=pg.mkPen(color="#1f4e9c", width=2))

    # ------------------------------------------------------------------
    # Metoda publiczna, wywoływana przez MainWindow przy każdym odświeżeniu
    # ------------------------------------------------------------------
    def set_data(self, times, si_values):
        """Ustawia dane krzywej SI.

        times     – lista lub tablica czasów w sekundach (oś X)
        si_values – lista lub tablica wartości SI w procentach (oś Y), mogą być ujemne
        """
        # setData zastępuje poprzednią krzywą nową, a nie dopisuje do starej.
        # connect="finite": punkty NaN (brak danych) robią przerwę w linii, zamiast rysować prostą do zera.
        self._krzywa.setData(times, si_values, connect="finite")

    def ustaw_zakres_czasu(self, dlugosc_s):
        """Ustawia oś X od 0 do długości filmu w sekundach. None przywraca automatyczny zakres."""
        if dlugosc_s is None:
            self.enableAutoRange(axis=pg.ViewBox.XAxis)
        else:
            self.setXRange(0, dlugosc_s, padding=0)
