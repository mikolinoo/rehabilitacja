import sys

from PySide6.QtWidgets import QApplication

from GUI.main_window import MainWindow

if __name__ == "__main__":
    app = QApplication(sys.argv)
    okno = MainWindow()
    okno.show()
    sys.exit(app.exec())  # uruchamia pętlę zdarzeń: program czeka na kliknięcia i inne zdarzenia
