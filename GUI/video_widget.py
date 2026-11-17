import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QLabel, QSizePolicy


class VideoWidget(QLabel):
    """Panel wideo: pokazuje pojedynczą klatkę.

    Widżet nie wie, skąd pochodzą klatki (plik, kamera, atrapa) – dostaje tylko
    tablicę numpy w formacie BGR (kolejność kolorów używana przez OpenCV).
    """

    def __init__(self):
        super().__init__("Otwórz plik")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background-color: #101010; color: #dddddd; font-size: 14px;")
        self.setMinimumSize(80, 60)  # żeby splitter nie zwinął panelu do zera
        # Ignored: obrazek nie wypycha okna – rozmiar wyznacza splitter, a nie klatka
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self._klatka = None  # ostatnia klatka w pełnym rozmiarze (QPixmap), None = brak filmu

    def show_frame(self, frame):
        """Wyświetla klatkę: BGR (numpy) -> RGB -> QImage -> QPixmap."""
        wysokosc, szerokosc, _ = frame.shape
        # [:, :, ::-1] odwraca kolejność kanałów BGR -> RGB
        # ascontiguousarray układa dane w pamięci jednym ciągłym blokiem (wymagane przez QImage)
        rgb = np.ascontiguousarray(frame[:, :, ::-1])
        # QImage tylko 'patrzy' na dane numpy. .copy() tworzy własną kopię, bo bufor rgb
        # może zostać zwolniony po zakończeniu funkcji – bez kopii obraz byłby śmieciem.
        obraz = QImage(rgb.data, szerokosc, wysokosc, 3 * szerokosc, QImage.Format.Format_RGB888).copy()
        self._klatka = QPixmap.fromImage(obraz)
        self._dopasuj_rozmiar()

    def resizeEvent(self, event):
        # Przy zmianie rozmiaru okna przeskalowujemy ostatnią klatkę, nawet gdy film stoi w pauzie
        super().resizeEvent(event)
        self._dopasuj_rozmiar()

    def _dopasuj_rozmiar(self):
        if self._klatka is None:
            return  # brak klatki – zostaje napis „Otwórz plik”
        self.setPixmap(
            self._klatka.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,  # zachowujemy proporcje obrazu
                Qt.TransformationMode.SmoothTransformation,  # ładniejsze skalowanie
            )
        )
