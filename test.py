import sys
import numpy as np
import cv2
import pyqtgraph as pg
from PySide6.QtWidgets import QApplication, QMainWindow


class OknoTestowe(QMainWindow):

    def __init__(self):
        super().__init__()                      # uruchom konstruktor QMainWindow
        self.setWindowTitle("Test środowiska – analiza symetrii")
        self.resize(800, 500)

        # Wykres pyqtgraph z dwiema sztucznymi krzywymi "kąta"
        wykres = pg.PlotWidget(title="Kąt w łokciu – dane testowe")
        wykres.addLegend()
        t = np.linspace(0, 10, 500)             # 500 punktów czasu od 0 do 10 s
        wykres.plot(t, 90 + 40 * np.sin(t), pen="g", name="lewa")
        wykres.plot(t, 90 + 30 * np.sin(t), pen="r", name="prawa")
        wykres.setLabel("bottom", "czas [s]")
        wykres.setLabel("left", "kąt [°]")

        self.setCentralWidget(wykres)           # wykres wypełnia całe okno


if __name__ == "__main__":
    print("OpenCV:", cv2.__version__)
    app = QApplication(sys.argv)    # "silnik" GUI – musi powstać jako pierwszy
    okno = OknoTestowe()
    okno.show()
    sys.exit(app.exec())            # start pętli zdarzeń (patrz wyjaśnienie niżej)