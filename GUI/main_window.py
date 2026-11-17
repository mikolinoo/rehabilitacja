from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QLabel, QMainWindow, QSplitter, QToolBar


class MainWindow(QMainWindow):
    """Główne okno aplikacji.

    QMainWindow ma gotowe miejsca na pasek narzędzi, pasek stanu
    i jeden widżet centralny (cały 'środek' okna).
    """

    def __init__(self):
        super().__init__()  # konstruktor QMainWindow – bez tego okno się nie zbuduje
        self.setWindowTitle("Analiza symetrii – rehabilitacja")
        self.resize(1100, 700)

        self._utworz_pasek_narzedzi()
        self.setCentralWidget(self._utworz_uklad())
        self.statusBar().showMessage("Gotowe")

    # ------------------------------------------------------------------
    # Pasek narzędzi – na razie przyciski nic nie robią (brak connect)
    # ------------------------------------------------------------------
    def _utworz_pasek_narzedzi(self):
        pasek = QToolBar("Narzędzia")
        self.addToolBar(pasek)
        for nazwa in ["Otwórz plik", "Kamera", "Start/Stop", "Eksport"]:
            # QAction = 'akcja' – opis polecenia, który może być na pasku i w menu
            pasek.addAction(QAction(nazwa, self))

    # ------------------------------------------------------------------
    # Układ – trzy QSplitter zagnieżdżone w siebie
    # ------------------------------------------------------------------
    def _utworz_uklad(self):
        # Poziomy splitter: [wideo | panel boczny]
        gorna = QSplitter(Qt.Orientation.Horizontal)
        gorna.addWidget(self._utworz_panel_wideo())
        gorna.addWidget(self._utworz_panel_boczny())
        gorna.setStretchFactor(0, 3)  # przy zmianie rozmiaru okna wideo rośnie szybciej
        gorna.setStretchFactor(1, 1)

        # Pionowy splitter: [górna część | timeline]
        calosc = QSplitter(Qt.Orientation.Vertical)
        calosc.addWidget(gorna)
        calosc.addWidget(self._utworz_panel_timeline())
        calosc.setStretchFactor(0, 4)
        calosc.setStretchFactor(1, 1)
        calosc.setSizes([500, 150])  # początkowa wysokość w pikselach
        return calosc

    def _utworz_panel_boczny(self):
        # Pionowy splitter: [kąty/ostrzeżenia | ustawienia]
        boczny = QSplitter(Qt.Orientation.Vertical)
        boczny.addWidget(self._utworz_panel_katow())
        boczny.addWidget(self._utworz_panel_ustawien())
        boczny.setSizes([300, 150])
        return boczny

    # ------------------------------------------------------------------
    # Panele-zaślepki: każda metoda zwraca widżet.
    # Gdy zrobisz prawdziwy panel, zmień tylko ciało jednej z tych metod.
    # ------------------------------------------------------------------
    def _utworz_panel_wideo(self):
        return self._zaslepka("WIDEO Z POZĄ I SZKIELETEM", "#cfe8ff")

    def _utworz_panel_katow(self):
        return self._zaslepka("KĄTY / OSTRZEŻENIA", "#d8f5d0")

    def _utworz_panel_ustawien(self):
        return self._zaslepka("USTAWIENIA", "#fff3c4")

    def _utworz_panel_timeline(self):
        return self._zaslepka("TIMELINE", "#f5d0e6")

    def _zaslepka(self, tekst, kolor):
        """Zwraca QLabel z napisem i kolorem tła – tymczasowy 'placeholder'."""
        etykieta = QLabel(tekst)
        etykieta.setAlignment(Qt.AlignmentFlag.AlignCenter)
        etykieta.setStyleSheet(f"background-color: {kolor}; color: black; font-size: 14px;")
        etykieta.setMinimumSize(80, 60)  # żeby splitter nie zwinął panelu do zera
        return etykieta
