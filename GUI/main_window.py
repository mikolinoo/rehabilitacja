from collections import deque
from pathlib import Path

import numpy as np
from PySide6.QtCore import QMetaObject, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QFileDialog, QLabel, QMainWindow, QSplitter, QToolBar

from GUI.gui_data_format import bezpieczny_odczyt
from GUI.mock_worker import MockWorker
from GUI.timeline_widget import TimelineWidget
from GUI.video_widget import VideoWidget

# Ile wyników trzymamy w pamięci (wykres i zapis przebiegu). 60 minut przy 30 klatkach/s.
# Zmiana tej jednej liczby wystarczy, żeby dostosować długość zapamiętanego przebiegu.
MAX_PUNKTOW = 30 * 60 * 60

# Domyślny folder okna wyboru pliku: <projekt>/data
DATA_DIR = Path(__file__).resolve().parent.parent / "data"


class MainWindow(QMainWindow):
    """Główne okno aplikacji.

    QMainWindow ma gotowe miejsca na pasek narzędzi, pasek stanu
    i jeden widżet centralny (cały 'środek' okna).
    """

    # Sygnały GUI -> worker. Okno 'krzyczy' sygnałem, a worker odbiera w swoim wątku.
    sygnal_otworz = Signal(str)  # ścieżka do pliku wideo
    sygnal_start = Signal()  # odtwarzanie (wznowienie)
    sygnal_stop = Signal()  # pauza
    sygnal_reset = Signal()  # od nowa, na pierwszą klatkę

    def __init__(self):
        super().__init__()  # konstruktor QMainWindow – bez tego okno się nie zbuduje
        self.setWindowTitle("Analiza symetrii – rehabilitacja")
        self.resize(1100, 700)

        # Bufor: wyniki kolejnych klatek (czas i SI), z których rysujemy wykres.
        # deque z maxlen sam wyrzuca najstarsze wpisy, gdy zabraknie miejsca.
        self._bufor_czas = deque(maxlen=MAX_PUNKTOW)
        self._bufor_si = deque(maxlen=MAX_PUNKTOW)
        self._ostatni_czas = 0.0
        self._na_koncu = False  # True, gdy film dobiegł końca

        # Informacje o otwartym pliku (ustawiane, gdy worker potwierdzi otwarcie)
        self._nazwa_pliku = None
        self._fps = None
        self._dlugosc = None  # [s], None gdy nieznana albo brak pliku

        self._utworz_pasek_narzedzi()
        self.setCentralWidget(self._utworz_uklad())
        self._utworz_pasek_stanu()
        self._utworz_watek()
        self._utworz_odswiezanie()
        self.statusBar().showMessage("Gotowe – otwórz plik wideo")

    # ------------------------------------------------------------------
    # Pasek narzędzi
    # ------------------------------------------------------------------
    def _utworz_pasek_narzedzi(self):
        pasek = QToolBar("Narzędzia")
        self.addToolBar(pasek)

        akcja_otworz = QAction("Otwórz plik", self)
        akcja_otworz.triggered.connect(self._otworz_plik)
        pasek.addAction(akcja_otworz)

        pasek.addAction(QAction("Kamera", self))  # jeszcze bez działania (zadanie 12)

        # Start/Stop to przełącznik odtwarzania: wciśnięty = gra, zwolniony = pauza.
        # Napis zmienia się razem ze stanem: „Start” gdy stoi, „Stop” gdy gra.
        self._akcja_start = QAction("Start", self)
        self._akcja_start.setCheckable(True)
        self._akcja_start.toggled.connect(self._przelacz_start_stop)
        pasek.addAction(self._akcja_start)

        # Reset wraca na pierwszą klatkę i czyści wyniki
        akcja_reset = QAction("Reset", self)
        akcja_reset.triggered.connect(self._reset)
        pasek.addAction(akcja_reset)

        pasek.addAction(QAction("Eksport", self))  # jeszcze bez działania (zadanie 13)

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
    # Panele: wideo, wykres i zaślepki
    # ------------------------------------------------------------------
    def _utworz_panel_wideo(self):
        # Zapamiętujemy w self, żeby wyświetlać w nim klatki z workera
        self._wideo = VideoWidget()
        return self._wideo

    def _utworz_panel_katow(self):
        return self._zaslepka("KĄTY / OSTRZEŻENIA", "#d8f5d0")

    def _utworz_panel_ustawien(self):
        return self._zaslepka("USTAWIENIA", "#fff3c4")

    def _utworz_panel_timeline(self):
        # Prawdziwy wykres. Zapamiętujemy go w self, żeby odświeżać go z bufora.
        self._timeline = TimelineWidget()
        return self._timeline

    def _zaslepka(self, tekst, kolor):
        """Zwraca QLabel z napisem i kolorem tła – tymczasowy 'placeholder'."""
        etykieta = QLabel(tekst)
        etykieta.setAlignment(Qt.AlignmentFlag.AlignCenter)
        etykieta.setStyleSheet(f"background-color: {kolor}; color: black; font-size: 14px;")
        etykieta.setMinimumSize(80, 60)  # żeby splitter nie zwinął panelu do zera
        return etykieta

    # ------------------------------------------------------------------
    # Pasek stanu: po lewej komunikaty, po prawej stały licznik (nazwa, fps, czas)
    # ------------------------------------------------------------------
    def _utworz_pasek_stanu(self):
        self._etykieta_czasu = QLabel("Czas: 0.0 s")
        self.statusBar().addPermanentWidget(self._etykieta_czasu)  # 'permanent' = nie znika po komunikacie

    def _aktualizuj_etykiete(self):
        czas = f"{self._ostatni_czas:.1f}"
        if self._dlugosc is None:
            tekst = f"Czas: {czas} s"
        else:
            tekst = f"{self._nazwa_pliku} | {self._fps:.0f} fps | {czas} / {self._dlugosc:.1f} s"
        self._etykieta_czasu.setText(tekst)

    # ------------------------------------------------------------------
    # Wątek workera
    # ------------------------------------------------------------------
    def _utworz_watek(self):
        # QThread = osobny 'wątek' (równoległa ścieżka programu). Worker przenosimy do niego,
        # żeby odczyt i przetwarzanie wideo nie zamrażały okna.
        self._watek = QThread()
        self._worker = MockWorker()
        self._worker.moveToThread(self._watek)  # od tej chwili slot workera wykonuje się w _watek
        self._watek.start()  # uruchamia pętlę zdarzeń wątku – czeka na polecenia

        # GUI -> worker (połączenia między wątkami działają w kolejce, bezpiecznie)
        self.sygnal_otworz.connect(self._worker.open_source)
        self.sygnal_start.connect(self._worker.start)
        self.sygnal_stop.connect(self._worker.stop)
        self.sygnal_reset.connect(self._worker.reset)

        # worker -> GUI
        self._worker.source_opened.connect(self._na_zrodlo)
        self._worker.frame_processed.connect(self._na_klatke)
        self._worker.event_detected.connect(self._na_zdarzenie)
        self._worker.error.connect(self._na_blad)
        self._worker.finished.connect(self._na_koniec)

    # ------------------------------------------------------------------
    # Akcje przycisków
    # ------------------------------------------------------------------
    def _otworz_plik(self):
        folder = str(DATA_DIR) if DATA_DIR.is_dir() else ""  # bez folderu data/ dialog otworzy się w bieżącym
        sciezka, _ = QFileDialog.getOpenFileName(
            self, "Wybierz plik wideo", folder, "Pliki wideo (*.mp4 *.avi *.mov);;Wszystkie pliki (*)"
        )
        if not sciezka:  # użytkownik kliknął Anuluj
            return
        self._akcja_start.setChecked(False)  # nowy film zaczyna się w pauzie
        self._wyczysc_wyniki()
        self.sygnal_otworz.emit(sciezka)
        self.statusBar().showMessage(f"Otwieranie: {Path(sciezka).name}")

    def _przelacz_start_stop(self, wlaczony):
        self._akcja_start.setText("Stop" if wlaczony else "Start")  # napis zgodny ze stanem
        if wlaczony:
            if self._na_koncu:  # film skończył się -> Start zaczyna od początku
                self._reset_workera()
            self.sygnal_start.emit()
            self.statusBar().showMessage("Odtwarzanie")
        else:
            self.sygnal_stop.emit()
            self.statusBar().showMessage("Pauza")

    def _reset(self):
        self._akcja_start.setChecked(False)  # najpierw pauza
        self._reset_workera()
        self.statusBar().showMessage("Od nowa – naciśnij Start, aby odtworzyć")

    def _reset_workera(self):
        self._wyczysc_wyniki()
        self._na_koncu = False
        self.sygnal_reset.emit()

    def _wyczysc_wyniki(self):
        self._bufor_czas.clear()
        self._bufor_si.clear()
        self._ostatni_czas = 0.0
        self._timeline.set_data(np.array([]), np.array([]))
        self._aktualizuj_etykiete()

    # ------------------------------------------------------------------
    # Sloty GUI – uruchamiane w wątku okna, gdy worker wyśle sygnał
    # ------------------------------------------------------------------
    def _na_zrodlo(self, info):
        # Worker potwierdził otwarcie pliku: zapamiętujemy dane i ustawiamy oś X na długość filmu
        self._nazwa_pliku = Path(info["path"]).name
        self._fps = info["fps"]
        self._dlugosc = info["duration"]
        self._timeline.ustaw_zakres_czasu(self._dlugosc)
        self._aktualizuj_etykiete()

    def _na_klatke(self, ramka, wynik):
        self._wideo.show_frame(ramka)
        czas = bezpieczny_odczyt(wynik, "timestamp")
        if czas is None:
            return  # brak czasu -> nie ma gdzie wstawić punktu
        si_total = bezpieczny_odczyt(wynik, "si", "total")
        self._bufor_czas.append(czas)
        self._bufor_si.append(np.nan if si_total is None else si_total)  # NaN = luka w wykresie
        self._ostatni_czas = czas

    def _na_zdarzenie(self, zdarzenie):
        # Zaznaczanie zdarzeń na wykresie to zadanie 8; na razie tylko komunikat
        self.statusBar().showMessage(f"Zdarzenie: {zdarzenie.get('joint')} ({zdarzenie.get('level')})")

    def _na_blad(self, tekst):
        self._akcja_start.setChecked(False)  # zatrzymujemy odtwarzanie (ustawia też komunikat „Pauza”)
        self.statusBar().showMessage(f"Błąd: {tekst}")  # komunikat błędu na końcu, żeby go nie nadpisało

    def _na_koniec(self):
        # Film dobiegł końca: zostajemy na ostatniej klatce, przycisk wraca do „Start”
        self._na_koncu = True
        self._akcja_start.setChecked(False)
        self.statusBar().showMessage("Koniec nagrania – Start odtworzy od początku")

    # ------------------------------------------------------------------
    # Odświeżanie wykresu – QTimer co 100 ms, nie przy każdej klatce
    # ------------------------------------------------------------------
    def _utworz_odswiezanie(self):
        self._odswiezanie = QTimer(self)  # rodzic = okno, więc działa w wątku GUI
        self._odswiezanie.setInterval(100)  # 10 razy na sekundę
        self._odswiezanie.timeout.connect(self._odswiez_timeline)
        self._odswiezanie.start()

    def _odswiez_timeline(self):
        if self._bufor_czas:
            self._timeline.set_data(np.array(self._bufor_czas), np.array(self._bufor_si, dtype=float))
        self._aktualizuj_etykiete()

    # ------------------------------------------------------------------
    # Zamykanie okna
    # ------------------------------------------------------------------
    def closeEvent(self, event):
        # 1) zwalniamy plik wideo w wątku workera i czekamy, aż to zrobi
        QMetaObject.invokeMethod(self._worker, "zamknij", Qt.ConnectionType.BlockingQueuedConnection)
        # 2) kończymy pętlę zdarzeń wątku i czekamy, aż wątek naprawdę się zakończy
        self._watek.quit()
        self._watek.wait()
        super().closeEvent(event)
