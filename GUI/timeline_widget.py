import numpy as np
import pyqtgraph as pg


class TimelineWidget(pg.PlotWidget):
    """Wykres surowych wartości SI (wskaźnika symetrii) w czasie nagrania.

    PlotWidget to gotowy 'arkusz do rysowania' z biblioteki pyqtgraph:
    zawiera osie, siatkę i obszar rysowania. Dziedziczymy po nim, żeby
    nasza klasa 'była' wykresem i miała dodatkowe metody (set_data).
    """

    def __init__(self, parent=None):
        super().__init__(parent)  # konstruktor PlotWidget – bez tego wykres się nie zbuduje
        self.setMinimumSize(80, 60)  # żeby splitter nie zwinął panelu do zera

        # Wygląd: białe tło, siatka, opisy osi.
        # Zakres osi Y nie jest ustawiony na sztywno – pyqtgraph dopasowuje go do danych,
        # więc wartości ujemne też będą widoczne.
        self.setBackground("w")
        self.showGrid(x=True, y=True, alpha=0.3)
        self.setLabel("bottom", "Czas", units="s")
        self.setLabel("left", "Wskaźnik symetrii SI", units="%")

        # Linia zerowa: 0 % = pełna symetria. To punkt odniesienia, nie limit.
        # Dzięki niej od razu widać, które wartości są dodatnie, a które ujemne.
        self.addItem(pg.InfiniteLine(angle=0, movable=False, pen=pg.mkPen(color="#555555", width=1)))

        # Krzywa SI – początkowo pusta; dane wpadną przez set_data()
        self._krzywa = self.plot(pen=pg.mkPen(color="#1f4e9c", width=2))

    # ------------------------------------------------------------------
    # Metoda publiczna – to z niej później skorzysta worker (wątek z danymi)
    # ------------------------------------------------------------------
    def set_data(self, times, si_values):
        """Ustawia dane krzywej SI.

        times     – lista/tablica czasów w sekundach (oś X)
        si_values – lista/tablica wartości SI w procentach (oś Y), mogą być ujemne
        """
        # setData zastępuje poprzednią krzywą nową; nie dopisuje do starej.
        # connect="finite": punkty NaN (brak danych) tworzą przerwę w linii, a nie prostą do zera.
        self._krzywa.setData(times, si_values, connect="finite")

    def ustaw_zakres_czasu(self, dlugosc_s):
        """Oś X od 0 do długości filmu [s]. None = wróć do automatycznego zakresu."""
        if dlugosc_s is None:
            self.enableAutoRange(axis=pg.ViewBox.XAxis)
        else:
            self.setXRange(0, dlugosc_s, padding=0)
