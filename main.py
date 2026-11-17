import sys

from PySide6.QtWidgets import QApplication

from GUI.main_window import MainWindow

if __name__ == "__main__":
    app = QApplication(sys.argv)  # "silnik" GUI – musi powstać jako pierwszy
    okno = MainWindow()
    okno.show()
    sys.exit(app.exec())  # start pętli zdarzeń – program czeka na kliknięcia itd.
