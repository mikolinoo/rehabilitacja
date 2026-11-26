from bisect import bisect_right

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from GUI.gui_data_format import DEFAULT_JOINTS, bezpieczny_odczyt
from GUI.kolory import (
    KOLORY,
    POZIOM_ALARM,
    POZIOM_BRAK,
    PROG_ALARMU_DOMYSLNY,
    PROG_OSTRZEZENIA_DOMYSLNY,
    TEKST_STATUSU,
    ocena_si,
)

# Polskie nazwy stawów do tabeli. Klucze muszą być takie jak w DEFAULT_JOINTS.
NAZWY_STAWOW = {"shoulder": "bark", "elbow": "łokieć", "hip": "biodro", "knee": "kolano"}

NAGLOWKI = ["Staw", "L [°]", "P [°]", "SI [%]", "Status"]
BRAK = "—"  # znak pokazywany zamiast wartości, której nie ma
KOLOR_WYSZARZONY = "#9e9e9e"  # wartość L/P/SI stawu, który nie jest analizowany
TLO_NAZW_STAWOW = "#37474f"  # ciemne tło kolumny „Staw”, żeby biały napis był widoczny
KOLOR_NAZWY = "#ffffff"  # napis nazwy analizowanego stawu
KOLOR_NAZWY_WYSZARZONEJ = "#b0bec5"  # napis nazwy stawu nieanalizowanego (jaśniejszy szary)
KOLOR_KATOW = "#eceff1"  # napis wartości kątów L/P analizowanego stawu (jasny, na ciemnym tle)


def formatuj(wartosc, miejsca):
    """Zamienia liczbę na tekst z podaną liczbą miejsc po przecinku. None zamienia na „—”."""
    if wartosc is None:
        return BRAK
    return f"{wartosc:.{miejsca}f}"


def formatuj_czas_ostrzezenia(sekundy):
    """Czas w formacie mm:ss.s do listy ostrzeżeń. None zamienia na „—”."""
    if sekundy is None:
        return BRAK
    minuty, reszta = divmod(sekundy, 60)
    return f"{int(minuty):02d}:{reszta:04.1f}"


class SidePanel(QWidget):
    """Panel boczny: symetria ogólna, tabela kątów i SI oraz lista ostrzeżeń.

    Panel pokazuje gotowe dane z wyniku klatki (angles i si) oraz listę zdarzeń.
    Nic nie liczy. Odświeża go MainWindow przy każdej klatce z workera.
    """

    # Sygnał po kliknięciu wpisu na liście: słownik zdarzenia (format z gui_data_format)
    wybrano_zdarzenie = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._warning = PROG_OSTRZEZENIA_DOMYSLNY
        self._alarm = PROG_ALARMU_DOMYSLNY
        self._ostatni_wynik = None  # zapamiętany wynik, żeby po zmianie progów przerysować panel
        self._analizowane = set(DEFAULT_JOINTS)  # stawy, które użytkownik wybrał do analizy

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
        # Stała wysokość (nagłówek + wiersze). Bez tego tabela rośnie i zabiera miejsce liście ostrzeżeń.
        self._tabela.setFixedHeight(36 + 26 * len(DEFAULT_JOINTS) + 4)

        # Nazwy stawów wpisujemy raz, bo się nie zmieniają. Wartości idą w pokaz_wynik().
        for wiersz, staw in enumerate(DEFAULT_JOINTS):
            self._tabela.setItem(wiersz, 0, QTableWidgetItem(NAZWY_STAWOW.get(staw, staw)))
            self._ustaw_nazwe(wiersz, staw)

        # Lista zdarzeń posortowana po czasie startu. Trzymamy ją też jako zwykłą listę Pythona,
        # żeby wiedzieć, która pozycja odpowiada któremu wpisowi po kliknięciu.
        self._zdarzenia = []
        self._lista_ostrzezen = QListWidget()
        self._lista_ostrzezen.itemClicked.connect(self._klikniecie_wpisu)
        self._etykieta_ostrzezen = QLabel()  # licznik, tekst ustawia _odswiez_licznik

        uklad = QVBoxLayout(self)  # układ pionowy: elementy jeden pod drugim
        uklad.addWidget(self._etykieta_total)
        uklad.addWidget(self._tabela)
        uklad.addWidget(self._etykieta_ostrzezen)
        uklad.addWidget(self._lista_ostrzezen, 1)  # lista dostaje resztę wysokości panelu
        szerokosc_paska = self._lista_ostrzezen.verticalScrollBar().sizeHint().width()
        self._lista_ostrzezen.setStyleSheet(f"QScrollBar:vertical {{ width: {2 * szerokosc_paska}px; }}")

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
            # Kąty L/P: tło jak kolumna „Staw”, jasny napis. Staw nieanalizowany: napis szary.
            kolor_kata = KOLOR_KATOW if staw in self._analizowane else KOLOR_WYSZARZONY
            # Staw nieanalizowany: tekst SI i Status szary, tło zostaje z oceny (zwykle „—”)
            if staw not in self._analizowane:
                tekst_kolor = KOLOR_WYSZARZONY

            self._ustaw_komorke(wiersz, 1, formatuj(kat_l, 0), TLO_NAZW_STAWOW, kolor_kata)
            self._ustaw_komorke(wiersz, 2, formatuj(kat_p, 0), TLO_NAZW_STAWOW, kolor_kata)
            self._ustaw_komorke(wiersz, 3, formatuj(si, 1), tlo, tekst_kolor)
            self._ustaw_komorke(wiersz, 4, status, tlo, tekst_kolor)

    def ustaw_stawy(self, analizowane):
        """Zaznacza, które stawy są analizowane. Pozostałe wiersze są wyszarzone."""
        self._analizowane = set(analizowane)
        for wiersz, staw in enumerate(DEFAULT_JOINTS):
            self._ustaw_nazwe(wiersz, staw)
        if self._ostatni_wynik is not None:
            self.pokaz_wynik(self._ostatni_wynik)  # przerysowujemy, żeby kolory były od razu poprawne

    def ustaw_progi(self, warning, alarm):
        """Zmienia progi. Jeśli panel coś pokazuje, przerysowuje go z nowymi kolorami."""
        self._warning = warning
        self._alarm = alarm
        if self._ostatni_wynik is not None:
            self.pokaz_wynik(self._ostatni_wynik)

    def wyczysc(self):
        """Wszystko na „—” i pusta lista ostrzeżeń. Używamy przy Reset i przy otwarciu nowego pliku."""
        self.pokaz_wynik(None)
        self.wyczysc_zdarzenia()

    def dodaj_zdarzenie(self, zdarzenie):
        """Dodaje wpis na listę we właściwym miejscu, według czasu startu.

        Wstawiamy jeden wpis zamiast przebudowywać całą listę, więc reszta się nie przeładowuje.
        """
        starty = [z.get("start") or 0.0 for z in self._zdarzenia]
        pozycja = bisect_right(starty, zdarzenie.get("start") or 0.0)
        self._zdarzenia.insert(pozycja, zdarzenie)
        self._lista_ostrzezen.insertItem(pozycja, self._tworz_wpis(zdarzenie))
        self._odswiez_licznik()

    def wyczysc_zdarzenia(self):
        """Pusta lista ostrzeżeń i licznik na zero."""
        self._zdarzenia = []
        self._lista_ostrzezen.clear()
        self._odswiez_licznik()

    # ------------------------------------------------------------------
    # Pomocnicze
    # ------------------------------------------------------------------
    def _tworz_wpis(self, zdarzenie):
        """Tekst wpisu, np. „00:03.0–00:05.2  łokieć  Uwaga (max 14.5 %)” w kolorze poziomu."""
        poziom = zdarzenie.get("level")
        tlo, tekst_kolor = KOLORY.get(poziom, KOLORY[POZIOM_BRAK])
        tekst = (
            f"{formatuj_czas_ostrzezenia(zdarzenie.get('start'))}–{formatuj_czas_ostrzezenia(zdarzenie.get('end'))}"
            f"  {NAZWY_STAWOW.get(zdarzenie.get('joint'), zdarzenie.get('joint'))}"
            f"  {TEKST_STATUSU.get(poziom, BRAK)} (max {formatuj(zdarzenie.get('si_max'), 1)} %)"
        )
        wpis = QListWidgetItem(tekst)
        wpis.setBackground(QColor(tlo))
        wpis.setForeground(QColor(tekst_kolor))
        return wpis

    def _odswiez_licznik(self):
        alarmy = sum(1 for z in self._zdarzenia if z.get("level") == POZIOM_ALARM)
        self._etykieta_ostrzezen.setText(f"Ostrzeżenia: {len(self._zdarzenia)} (alarmy: {alarmy})")

    def _klikniecie_wpisu(self, wpis):
        # Pozycja wpisu na liście = pozycja w _zdarzenia (oba są posortowane tak samo)
        self.wybrano_zdarzenie.emit(self._zdarzenia[self._lista_ostrzezen.row(wpis)])

    def _ustaw_nazwe(self, wiersz, staw):
        """Kolumna „Staw”: ciemne tło, a napis biały (analizowany) albo jasnoszary (nieanalizowany)."""
        nazwa = self._tabela.item(wiersz, 0)
        nazwa.setBackground(QColor(TLO_NAZW_STAWOW))
        kolor = KOLOR_NAZWY if staw in self._analizowane else KOLOR_NAZWY_WYSZARZONEJ
        nazwa.setForeground(QColor(kolor))

    def _ustaw_komorke(self, wiersz, kolumna, tekst, tlo=None, tekst_kolor=None):
        """Wpisuje tekst do jednej komórki tabeli. Kolory są opcjonalne."""
        komorka = QTableWidgetItem(tekst)
        komorka.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        if tlo is not None:
            komorka.setBackground(QColor(tlo))
        if tekst_kolor is not None:
            komorka.setForeground(QColor(tekst_kolor))
        self._tabela.setItem(wiersz, kolumna, komorka)
