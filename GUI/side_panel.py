from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QListWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from GUI.gui_data_format import DEFAULT_JOINTS, bezpieczny_odczyt
from GUI.kolory import PROG_ALARMU_DOMYSLNY, PROG_OSTRZEZENIA_DOMYSLNY, ocena_si

# Polskie nazwy stawów do tabeli. Klucze muszą być takie jak w DEFAULT_JOINTS.
NAZWY_STAWOW = {"shoulder": "bark", "elbow": "łokieć", "hip": "biodro", "knee": "kolano"}

NAGLOWKI = ["Staw", "L [°]", "P [°]", "SI [%]", "Status"]
BRAK = "—"  # znak pokazywany zamiast wartości, której nie ma


def formatuj(wartosc, miejsca):
    """Zamienia liczbę na tekst z podaną liczbą miejsc po przecinku. None zamienia na „—”."""
    if wartosc is None:
        return BRAK
    return f"{wartosc:.{miejsca}f}"


class SidePanel(QWidget):
    """Panel boczny: symetria ogólna, tabela kątów i SI oraz lista ostrzeżeń.

    Panel tylko pokazuje gotowe dane z wyniku klatki (angles i si). Nic nie liczy.
    Odświeża go MainWindow timerem, a nie przy każdej klatce.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._warning = PROG_OSTRZEZENIA_DOMYSLNY
        self._alarm = PROG_ALARMU_DOMYSLNY
        self._ostatni_wynik = None  # zapamiętany wynik, żeby po zmianie progów przerysować panel

        # Napis na górze z symetrią ogólną; tło zmienia kolor wg progów
        self._etykieta_total = QLabel(f"Symetria ogólna: {BRAK}")
        self._etykieta_total.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Tabela: wiersze = stawy z DEFAULT_JOINTS, kolumny = NAGLOWKI
        self._tabela = QTableWidget(len(DEFAULT_JOINTS), len(NAGLOWKI))
        self._tabela.setHorizontalHeaderLabels(NAGLOWKI)
        self._tabela.verticalHeader().setVisible(False)  # numerów wierszy nie potrzebujemy
        self._tabela.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)  # tylko do odczytu
        self._tabela.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        # Stała wysokość wiersza i minimalna wysokość tabeli, żeby wszystkie stawy były widoczne bez przewijania
        self._tabela.verticalHeader().setDefaultSectionSize(26)
        self._tabela.setMinimumHeight(36 + 26 * len(DEFAULT_JOINTS))

        # Nazwy stawów wpisujemy raz, bo się nie zmieniają. Wartości idą w pokaz_wynik().
        for wiersz, staw in enumerate(DEFAULT_JOINTS):
            self._tabela.setItem(wiersz, 0, QTableWidgetItem(NAZWY_STAWOW.get(staw, staw)))

        self._lista_ostrzezen = QListWidget()  # na razie pusta, wypełni ją zadanie 8

        uklad = QVBoxLayout(self)  # układ pionowy: elementy jeden pod drugim
        uklad.addWidget(self._etykieta_total)
        uklad.addWidget(self._tabela)
        uklad.addWidget(QLabel("Ostrzeżenia"))
        uklad.addWidget(self._lista_ostrzezen, 1)  # lista dostaje resztę wysokości panelu

        self.wyczysc()

    # ------------------------------------------------------------------
    # Metody publiczne – wywoływane przez MainWindow
    # ------------------------------------------------------------------
    def pokaz_wynik(self, wynik):
        """Wyświetla kąty i SI z wyniku klatki. wynik może być None."""
        self._ostatni_wynik = wynik

        total = bezpieczny_odczyt(wynik, "si", "total")
        _, (tlo, tekst_kolor), _ = ocena_si(total, self._warning, self._alarm)
        self._etykieta_total.setText(f"Symetria ogólna: {formatuj(total, 1)} %")
        self._etykieta_total.setStyleSheet(
            f"background-color: {tlo}; color: {tekst_kolor}; font-size: 18px; font-weight: bold; padding: 8px;"
        )

        for wiersz, staw in enumerate(DEFAULT_JOINTS):
            kat_l = bezpieczny_odczyt(wynik, "angles", staw, "L")
            kat_p = bezpieczny_odczyt(wynik, "angles", staw, "R")
            si = bezpieczny_odczyt(wynik, "si", staw)
            _, (tlo, tekst_kolor), status = ocena_si(si, self._warning, self._alarm)

            self._ustaw_komorke(wiersz, 1, formatuj(kat_l, 0))
            self._ustaw_komorke(wiersz, 2, formatuj(kat_p, 0))
            self._ustaw_komorke(wiersz, 3, formatuj(si, 1), tlo, tekst_kolor)
            self._ustaw_komorke(wiersz, 4, status, tlo, tekst_kolor)

    def ustaw_progi(self, warning, alarm):
        """Zmienia progi. Jeśli panel coś pokazuje, przerysowuje go z nowymi kolorami."""
        self._warning = warning
        self._alarm = alarm
        if self._ostatni_wynik is not None:
            self.pokaz_wynik(self._ostatni_wynik)

    def wyczysc(self):
        """Wszystko na „—” i pusta lista ostrzeżeń. Używamy przy Reset i przy otwarciu nowego pliku."""
        self.pokaz_wynik(None)
        self._lista_ostrzezen.clear()

    # ------------------------------------------------------------------
    # Pomocnicze
    # ------------------------------------------------------------------
    def _ustaw_komorke(self, wiersz, kolumna, tekst, tlo=None, tekst_kolor=None):
        """Wpisuje tekst do jednej komórki tabeli. Kolory są opcjonalne."""
        komorka = QTableWidgetItem(tekst)
        komorka.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        if tlo is not None:
            komorka.setBackground(QColor(tlo))
        if tekst_kolor is not None:
            komorka.setForeground(QColor(tekst_kolor))
        self._tabela.setItem(wiersz, kolumna, komorka)
