from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from GUI.gui_data_format import DEFAULT_JOINTS
from GUI.kolory import PROG_ALARMU_DOMYSLNY, PROG_OSTRZEZENIA_DOMYSLNY
from GUI.side_panel import NAZWY_STAWOW

KROK_PROGU = 0.5  # krok strzałek i minimalny odstęp między progami [%]

# (opis widoczny dla użytkownika, wartość wysyłana do workera)
TYPY_CWICZEN = [
    ("Obie strony jednocześnie", "simultaneous"),
    ("Naprzemiennie", "alternating"),
]


class SettingsPanel(QWidget):
    """Panel ustawień: progi SI, typ ćwiczenia, stawy. Wysyła wybory sygnałem."""

    # Wysyłany po każdej zmianie. Słownik ma format z docs/format_danych_gui.md.
    ustawienia_zmienione = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)

        # Wartości ustawiamy przed podłączeniem sygnałów, żeby start nie wysłał zmiany
        self._uwaga = self._utworz_prog(PROG_OSTRZEZENIA_DOMYSLNY)
        self._alarm = self._utworz_prog(PROG_ALARMU_DOMYSLNY)
        self._uwaga.valueChanged.connect(self._zmieniono_uwage)
        self._alarm.valueChanged.connect(self._zmieniono_alarm)

        # Sekcja: progi
        grupa_progi = QGroupBox("Progi SI")
        formularz = QFormLayout(grupa_progi)
        formularz.addRow("Uwaga od:", self._uwaga)
        formularz.addRow("Alarm od:", self._alarm)

        # Sekcja: typ ćwiczenia. Użytkownik widzi opis po polsku, a worker dostaje wartość z TYPY_CWICZEN.
        grupa_typ = QGroupBox("Typ ćwiczenia")
        uklad_typ = QVBoxLayout(grupa_typ)
        self._typ = QComboBox()
        for opis, wartosc in TYPY_CWICZEN:
            self._typ.addItem(opis, wartosc)  # opis to tekst, wartosc to dane ukryte pod tekstem
        self._typ.currentIndexChanged.connect(self._emituj)
        uklad_typ.addWidget(self._typ)

        # Sekcja: stawy. Jeden pole wyboru na każdy staw z listy domyślnej.
        grupa_stawy = QGroupBox("Analizowane stawy")
        uklad_stawy = QVBoxLayout(grupa_stawy)
        self._stawy = {}  # {nazwa stawu: QCheckBox}
        for staw in DEFAULT_JOINTS:
            pole = QCheckBox(NAZWY_STAWOW.get(staw, staw))
            pole.setChecked(True)
            pole.toggled.connect(self._zmieniono_stawy)
            self._stawy[staw] = pole
            uklad_stawy.addWidget(pole)

        przycisk = QPushButton("Przywróć domyślne")
        przycisk.clicked.connect(self._przywroc_domyslne)

        # Trzy sekcje obok siebie, żeby panel był niski
        kolumny = QHBoxLayout()
        kolumny.addWidget(grupa_stawy)
        kolumny.addWidget(grupa_typ)
        kolumny.addWidget(grupa_progi)

        uklad = QVBoxLayout(self)
        uklad.addLayout(kolumny)
        uklad.addWidget(przycisk)

        self._odswiez_blokady()

    # ------------------------------------------------------------------
    # Metody publiczne
    # ------------------------------------------------------------------
    def pobierz_ustawienia(self):
        """Zwraca aktualne ustawienia w formacie, który rozumie worker."""
        return {
            "thresholds": {"warning": self._uwaga.value(), "alarm": self._alarm.value()},
            "exercise_type": self._typ.currentData(),
            "joints": [staw for staw in DEFAULT_JOINTS if self._stawy[staw].isChecked()],
        }

    # ------------------------------------------------------------------
    # Progi: pilnowanie warning < alarm
    # ------------------------------------------------------------------
    def _utworz_prog(self, wartosc):
        pole = QDoubleSpinBox()
        pole.setRange(0.0, 100.0)
        pole.setDecimals(1)
        pole.setSingleStep(KROK_PROGU)
        pole.setSuffix(" %")
        pole.setValue(wartosc)
        # Tracking wyłączony: wartość idzie dalej po Enter albo po wyjściu z pola, a nie po każdej wpisanej cyfrze.
        pole.setKeyboardTracking(False)
        return pole

    def _zmieniono_uwage(self):
        if self._uwaga.value() >= self._alarm.value():
            # Uwaga dogoniła alarm, więc przesuwamy alarm w górę (bez wysyłania jego sygnału)
            self._ustaw_bez_sygnalow(self._alarm, min(100.0, self._uwaga.value() + KROK_PROGU))
            if self._uwaga.value() >= self._alarm.value():
                # Alarm jest już na 100 %, więc to uwaga musi ustąpić
                self._ustaw_bez_sygnalow(self._uwaga, self._alarm.value() - KROK_PROGU)
        self._emituj()

    def _zmieniono_alarm(self):
        if self._alarm.value() <= self._uwaga.value():
            # Alarm spadł pod uwagę, więc przesuwamy uwagę w dół (bez wysyłania jej sygnału)
            self._ustaw_bez_sygnalow(self._uwaga, max(0.0, self._alarm.value() - KROK_PROGU))
            if self._alarm.value() <= self._uwaga.value():
                # Uwaga jest już na 0 %, więc to alarm musi wzrosnąć
                self._ustaw_bez_sygnalow(self._alarm, self._uwaga.value() + KROK_PROGU)
        self._emituj()

    # ------------------------------------------------------------------
    # Stawy: co najmniej jeden musi zostać zaznaczony
    # ------------------------------------------------------------------
    def _zmieniono_stawy(self, *_):
        self._odswiez_blokady()
        self._emituj()

    def _odswiez_blokady(self):
        zaznaczone = [pole for pole in self._stawy.values() if pole.isChecked()]
        for pole in self._stawy.values():
            # Jeśli zaznaczony jest tylko jeden staw, jego pole blokujemy: nie da się go odznaczyć
            ostatni = len(zaznaczone) == 1 and pole.isChecked()
            pole.setEnabled(not ostatni)
            pole.setToolTip("Zaznacz inny staw, żeby odznaczyć ten" if ostatni else "")

    # ------------------------------------------------------------------
    # Przywracanie domyślnych
    # ------------------------------------------------------------------
    def _przywroc_domyslne(self):
        widzety = [self._uwaga, self._alarm, self._typ, *self._stawy.values()]
        for widzet in widzety:
            widzet.blockSignals(True)  # ustawiamy wszystko naraz, a wysyłamy raz na końcu
        self._uwaga.setValue(PROG_OSTRZEZENIA_DOMYSLNY)
        self._alarm.setValue(PROG_ALARMU_DOMYSLNY)
        self._typ.setCurrentIndex(0)  # pierwsza pozycja to "simultaneous"
        for pole in self._stawy.values():
            pole.setChecked(True)
        for widzet in widzety:
            widzet.blockSignals(False)
        self._odswiez_blokady()
        self._emituj()

    # ------------------------------------------------------------------
    # Pomocnicze
    # ------------------------------------------------------------------
    def _ustaw_bez_sygnalow(self, pole, wartosc):
        # Poprawka wartości zrobiona przez nas samych nie może wywołać kolejnej poprawki (pętla sygnałów)
        pole.blockSignals(True)
        pole.setValue(wartosc)
        pole.blockSignals(False)

    def _emituj(self, *_):
        self.ustawienia_zmienione.emit(self.pobierz_ustawienia())
