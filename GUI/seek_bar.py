from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSlider, QWidget


def formatuj_czas(sekundy):
    """Zamienia sekundy na tekst mm:ss.s, np. 65.25 -> '01:05.2'."""
    dziesiate = round(sekundy * 10)  # liczymy w dziesiątych sekundy, żeby nie wyszło „60.0”
    minuty, reszta = divmod(dziesiate, 600)
    return f"{minuty:02d}:{reszta / 10:04.1f}"


class SeekBar(QWidget):
    """Pasek przewijania: suwak po klatkach i etykieta „mm:ss.s / mm:ss.s”.

    Suwak sam nie przewija filmu. Wysyła tylko numer klatki (sygnał przewinieto),
    a przewinięcie robi MainWindow przez workera.
    """

    przewinieto = Signal(int)  # numer klatki, którą wybrał użytkownik

    def __init__(self, parent=None):
        super().__init__(parent)
        self._fps = 1.0
        self._liczba_klatek = 0

        self._suwak = QSlider(Qt.Orientation.Horizontal)
        # Tracking wyłączony: valueChanged przychodzi dopiero po puszczeniu suwaka, a nie przy każdym ruchu.
        # Dzięki temu przewijanie wysyłamy jeden raz, po puszczeniu.
        self._suwak.setTracking(False)
        self._suwak.sliderMoved.connect(self._pokaz_etykiete)  # w trakcie przeciągania: tylko etykieta
        self._suwak.valueChanged.connect(self._uzytkownik_przesunal)  # puszczenie, strzałki, klik na pasku

        self._etykieta = QLabel()
        uklad = QHBoxLayout(self)
        uklad.setContentsMargins(0, 0, 0, 0)
        uklad.addWidget(self._suwak, 1)  # suwak dostaje całą wolną szerokość
        uklad.addWidget(self._etykieta)
        self.ustaw_zakres(None, None)

    # ------------------------------------------------------------------
    # Metody publiczne – wywoływane przez MainWindow
    # ------------------------------------------------------------------
    def ustaw_zakres(self, liczba_klatek, fps):
        """Ustawia zakres suwaka na klatki pliku. None (brak pliku) wyłącza pasek."""
        ma_klatki = bool(liczba_klatek and liczba_klatek > 0)
        self._liczba_klatek = liczba_klatek if ma_klatki else 0
        if ma_klatki:
            self._fps = fps
        self._suwak.blockSignals(True)  # zmiana od programu nie może wysłać przewinieto
        self._suwak.setRange(0, liczba_klatek - 1 if ma_klatki else 0)
        self._suwak.setValue(0)
        self._suwak.blockSignals(False)
        self.setEnabled(ma_klatki)
        self._pokaz_etykiete(0)

    def ustaw_klatke(self, numer):
        """Pokazuje bieżącą klatkę na suwaku. Nie wysyła przewinieto, więc nie tworzy pętli."""
        if self._suwak.isSliderDown():
            return  # użytkownik właśnie ciągnie suwak, nie nadpisujemy jego pozycji
        self._suwak.blockSignals(True)
        self._suwak.setValue(numer)
        self._suwak.blockSignals(False)
        self._pokaz_etykiete(numer)

    # ------------------------------------------------------------------
    # Pomocnicze
    # ------------------------------------------------------------------
    def _uzytkownik_przesunal(self, numer):
        # Ten slot działa tylko przy zmianie od użytkownika (program ma blockSignals)
        self._pokaz_etykiete(numer)
        self.przewinieto.emit(numer)

    def _pokaz_etykiete(self, numer):
        if self._liczba_klatek <= 0:
            self._etykieta.setText("00:00.0 / 00:00.0")
            return
        czas = numer / self._fps  # numer klatki zamieniamy na czas: klatka N to N / fps sekund
        dlugosc = self._liczba_klatek / self._fps
        self._etykieta.setText(f"{formatuj_czas(czas)} / {formatuj_czas(dlugosc)}")
