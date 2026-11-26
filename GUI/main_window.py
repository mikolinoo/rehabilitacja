from pathlib import Path

import numpy as np
from PySide6.QtCore import QMetaObject, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QFileDialog, QLabel, QMainWindow, QSplitter, QToolBar, QVBoxLayout, QWidget

from GUI.gui_data_format import bezpieczny_odczyt
from GUI.mock_worker import MockWorker
from GUI.seek_bar import SeekBar
from GUI.settings_panel import SettingsPanel
from GUI.side_panel import SidePanel
from GUI.timeline_widget import TimelineWidget
from GUI.video_widget import VideoWidget

# Ile wyników trzymamy w pamięci (wykres i zapis przebiegu). To 60 minut przy 30 klatkach/s.
# Zmiana tej jednej liczby wystarczy, żeby zmienić długość zapamiętanego przebiegu.
MAX_PUNKTOW = 30 * 60 * 60

# Domyślny folder okna wyboru pliku: <projekt>/data
DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def czas_na_klatke(czas_s, fps, liczba_klatek):
    """Zamienia czas z wykresu na numer klatki i przycina do zakresu filmu.

    Klatka N ma czas N / fps, więc odwrotnie: numer = czas · fps, zaokrąglony do pełnej klatki.
    """
    numer = round(czas_s * fps)
    return min(max(numer, 0), liczba_klatek - 1)


class MainWindow(QMainWindow):
    """Główne okno aplikacji.

    QMainWindow ma gotowe miejsca na pasek narzędzi, pasek stanu
    i jeden widżet centralny.
    """

    # Sygnały z GUI do workera. Okno wysyła sygnał, a worker odbiera go w swoim wątku.
    sygnal_otworz = Signal(str)  # ścieżka do pliku wideo
    sygnal_start = Signal()  # odtwarzanie (wznowienie)
    sygnal_stop = Signal()  # pauza
    sygnal_reset = Signal()  # od nowa, na pierwszą klatkę
    sygnal_przewin = Signal(int)  # numer klatki, do której przewijamy
    sygnal_ustawienia = Signal(dict)  # progi, typ ćwiczenia i stawy (format z format_danych_gui.md)

    def __init__(self):
        super().__init__()  # konstruktor QMainWindow; bez tego okno się nie zbuduje
        self.setWindowTitle("Analiza symetrii – rehabilitacja")
        self.resize(1100, 700)

        # Wyniki klatek w słowniku {numer klatki: wynik}. Ponowne odczytanie tej samej klatki
        # nadpisuje jej wpis zamiast dodawać duplikat. Słownik pamięta kolejność dodawania,
        # więc pierwszy wpis to najstarszy (tego używamy przy usuwaniu nadmiaru).
        self._wyniki = {}
        # Zdarzenia asymetrii w jednym miejscu: {(staw, czas startu): zdarzenie}. Klucz zapobiega duplikatom,
        # bo po przewinięciu do tyłu i ponownym odtworzeniu worker wysyła to samo zdarzenie jeszcze raz.
        self._zdarzenia = {}
        self._ostatnie_stawy = None  # stawy, z których liczona była krzywa w buforze
        self._wyniki_zmienione = False  # czy wykres trzeba przerysować przy najbliższym odświeżeniu
        self._biezaca_klatka = 0  # numer klatki, którą właśnie pokazujemy
        self._ostatni_czas = 0.0
        self._na_koncu = False  # True, gdy odtwarzanie dobiegło końca

        # Informacje o otwartym pliku. Ustawiamy je, gdy worker potwierdzi otwarcie.
        self._nazwa_pliku = None
        self._fps = None
        self._dlugosc = None  # w sekundach; None, gdy nieznana albo brak pliku
        self._liczba_klatek = None  # None, gdy nieznana albo brak pliku

        self._utworz_pasek_narzedzi()
        self.setCentralWidget(self._utworz_uklad())
        self._utworz_pasek_stanu()
        self._utworz_watek()
        self._utworz_odswiezanie()
        # Start aplikacji: worker i wykres dostają ustawienia z panelu, zanim ktokolwiek je zmieni
        self._na_ustawienia(self._panel_ustawien.pobierz_ustawienia())
        self.statusBar().showMessage("Gotowe – otwórz plik wideo")

    # Pasek narzędzi----------
    def _utworz_pasek_narzedzi(self):
        pasek = QToolBar("Narzędzia")
        self.addToolBar(pasek)

        akcja_otworz = QAction("Otwórz plik", self)
        akcja_otworz.triggered.connect(self._otworz_plik)
        pasek.addAction(akcja_otworz)

        pasek.addAction(QAction("Kamera", self))  # jeszcze bez działania

        # Start/Stop działa jak przełącznik odtwarzania: wciśnięty oznacza grę, zwolniony pauzę.
        # Napis zmienia się razem ze stanem: „Start”, gdy stoi, i „Stop”, gdy gra.
        self._akcja_start = QAction("Start", self)
        self._akcja_start.setCheckable(True)
        self._akcja_start.toggled.connect(self._przelacz_start_stop)
        # Dopóki nie ma załadowanego filmu, nie ma czego odtwarzać. Odblokowuje go _na_zrodlo.
        self._akcja_start.setEnabled(False)
        self._akcja_start.setToolTip("Najpierw otwórz plik wideo")
        pasek.addAction(self._akcja_start)

        # Reset wraca na pierwszą klatkę i czyści wyniki
        akcja_reset = QAction("Reset", self)
        akcja_reset.triggered.connect(self._reset)
        pasek.addAction(akcja_reset)

        pasek.addAction(QAction("Eksport", self))  # jeszcze bez działania

    # Układ: trzy QSplitter zagnieżdżone w sobie--------------------
    def _utworz_uklad(self):
        # Poziomy splitter: [wideo z suwakiem | panel boczny]
        gorna = QSplitter(Qt.Orientation.Horizontal)
        # Bez tego przeciągnięcie granicy do końca chowa panel do zera i jego zawartość znika
        gorna.setChildrenCollapsible(False)
        gorna.addWidget(self._utworz_panel_wideo())
        gorna.addWidget(self._utworz_panel_boczny())
        gorna.setStretchFactor(0, 3)  # przy zmianie rozmiaru okna wideo rośnie szybciej
        gorna.setStretchFactor(1, 1)

        # Pionowy splitter: [górna część | timeline]
        calosc = QSplitter(Qt.Orientation.Vertical)
        calosc.setChildrenCollapsible(False)  # jak wyżej: wykres i górna część nie mogą zniknąć
        calosc.addWidget(gorna)
        calosc.addWidget(self._utworz_panel_timeline())
        calosc.setStretchFactor(0, 4)
        calosc.setStretchFactor(1, 1)
        calosc.setSizes([500, 150])  # początkowa wysokość w pikselach
        return calosc

    def _utworz_panel_boczny(self):
        # Pionowy splitter: [kąty i ostrzeżenia | ustawienia]
        boczny = QSplitter(Qt.Orientation.Vertical)
        boczny.setChildrenCollapsible(False)  # ostrzeżenia i ustawienia nie mogą zniknąć
        boczny.addWidget(self._utworz_panel_katow())
        boczny.addWidget(self._utworz_panel_ustawien())
        # Ustawienia startują w najmniejszym rozmiarze, w jakim się jeszcze mieszczą (minimum panelu).
        # Dzięki temu lista ostrzeżeń ma najwięcej miejsca. Przy zmianie rozmiaru okna rośnie góra.
        boczny.setStretchFactor(0, 1)
        boczny.setStretchFactor(1, 0)
        boczny.setSizes([300, self._panel_ustawien.minimumSizeHint().height()])
        return boczny

    # Panele: wideo, wykres i zaślepki-------------------------------
    def _utworz_panel_wideo(self):
        # Wideo i pasek przewijania w jednej kolumnie: suwak jest pod obrazem
        self._wideo = VideoWidget()
        self._suwak = SeekBar()
        self._suwak.przewinieto.connect(self._przewin_do_klatki)
        panel = QWidget()
        uklad = QVBoxLayout(panel)
        uklad.setContentsMargins(0, 0, 0, 0)
        uklad.addWidget(self._wideo, 1)  # obraz dostaje całą wolną wysokość
        uklad.addWidget(self._suwak)
        return panel

    def _utworz_panel_katow(self):
        # Panel z kątami, SI i ostrzeżeniami. Odświeżamy go przy każdej klatce.
        self._panel = SidePanel()
        self._panel.wybrano_zdarzenie.connect(self._na_klik_ostrzezenie)
        return self._panel

    def _utworz_panel_ustawien(self):
        # Zapamiętujemy panel w self, żeby przy starcie pobrać z niego ustawienia początkowe
        self._panel_ustawien = SettingsPanel()
        self._panel_ustawien.ustawienia_zmienione.connect(self._na_ustawienia)
        return self._panel_ustawien

    def _utworz_panel_timeline(self):
        # Prawdziwy wykres. Zapamiętujemy go w self, żeby odświeżać go z bufora.
        self._timeline = TimelineWidget()
        self._timeline.kliknieto_czas.connect(self._na_klik_wykres)
        return self._timeline

    def _zaslepka(self, tekst, kolor):
        """Zwraca QLabel z napisem i kolorem tła. To tymczasowy placeholder."""
        etykieta = QLabel(tekst)
        etykieta.setAlignment(Qt.AlignmentFlag.AlignCenter)
        etykieta.setStyleSheet(f"background-color: {kolor}; color: black; font-size: 14px;")
        etykieta.setMinimumSize(80, 60)  # żeby splitter nie zwinął panelu do zera
        return etykieta

    # ------------------------------------------------------------------
    # Pasek stanu: po lewej komunikaty, po prawej stały licznik (nazwa, fps, czas)
    def _utworz_pasek_stanu(self):
        self._etykieta_czasu = QLabel("Czas: 0.0 s")
        # 'permanent' oznacza, że widżet nie znika razem z komunikatem
        self.statusBar().addPermanentWidget(self._etykieta_czasu)

    def _aktualizuj_etykiete(self):
        czas = f"{self._ostatni_czas:.1f}"
        if self._dlugosc is None:
            tekst = f"Czas: {czas} s"
        else:
            tekst = f"{self._nazwa_pliku} | {self._fps:.0f} fps | {czas} / {self._dlugosc:.1f} s"
        self._etykieta_czasu.setText(tekst)

    # Wątek workera-------------------------------------------------
    def _utworz_watek(self):
        # QThread to osobny wątek, czyli równoległa ścieżka programu. Przenosimy do niego
        # workera, żeby odczyt i przetwarzanie wideo nie zamrażały okna.
        self._watek = QThread()
        self._worker = MockWorker()
        self._worker.moveToThread(self._watek)  # od tej chwili sloty workera działają w _watek
        self._watek.start()  # uruchamia pętlę zdarzeń wątku, która czeka na polecenia

        # GUI -> worker. Połączenia między wątkami działają kolejkowo, więc są bezpieczne.
        self.sygnal_otworz.connect(self._worker.open_source)
        self.sygnal_start.connect(self._worker.start)
        self.sygnal_stop.connect(self._worker.stop)
        self.sygnal_reset.connect(self._worker.reset)
        self.sygnal_przewin.connect(self._worker.seek)
        self.sygnal_ustawienia.connect(self._worker.set_settings)

        # worker -> GUI
        self._worker.source_opened.connect(self._na_zrodlo)
        self._worker.frame_processed.connect(self._na_klatke)
        self._worker.event_detected.connect(self._na_zdarzenie)
        self._worker.wyniki_calego_filmu.connect(self._na_caly_film)  # tryb CALY_FILM_OD_RAZU
        self._worker.error.connect(self._na_blad)
        self._worker.finished.connect(self._na_koniec)

    # Akcje przycisków i przewijanie---------------------------
    def _otworz_plik(self):
        # Jeśli folderu data/ nie ma, dialog otworzy się w bieżącym folderze
        folder = str(DATA_DIR) if DATA_DIR.is_dir() else ""
        sciezka, _ = QFileDialog.getOpenFileName(
            self, "Wybierz plik wideo", folder, "Pliki wideo (*.mp4 *.avi *.mov);;Wszystkie pliki (*)"
        )
        if not sciezka:  # użytkownik kliknął Anuluj
            return
        self._akcja_start.setChecked(False)  # nowy film zaczyna się w pauzie
        # Blokujemy Start do potwierdzenia otwarcia. Gdyby plik się nie otworzył, nie odtworzymy pustego źródła.
        self._akcja_start.setEnabled(False)
        self._suwak.ustaw_zakres(None, None)  # suwak nieaktywny do potwierdzenia otwarcia
        self._wyczysc_wyniki()
        self.sygnal_otworz.emit(sciezka)
        self.statusBar().showMessage(f"Otwieranie: {Path(sciezka).name}")

    def _przelacz_start_stop(self, wlaczony):
        self._akcja_start.setText("Stop" if wlaczony else "Start")  # napis zgodny ze stanem
        if wlaczony:
            if self._na_ostatniej_klatce():  # na końcu filmu Start zaczyna od początku
                self._reset_workera()
            self.sygnal_start.emit()
            self.statusBar().showMessage("Odtwarzanie")
        else:
            self.sygnal_stop.emit()
            self.statusBar().showMessage("Pauza")

    def _na_ostatniej_klatce(self):
        """True, gdy odtwarzanie dobiegło końca albo stoimy na ostatniej klatce."""
        if self._na_koncu:
            return True
        return self._liczba_klatek is not None and self._biezaca_klatka >= self._liczba_klatek - 1

    def _przewin_do_klatki(self, numer):
        # Ręczne przewinięcie kasuje znacznik „koniec”, więc Start gra od wybranego miejsca
        self._na_koncu = False
        self.sygnal_przewin.emit(numer)

    def _na_klik_ostrzezenie(self, zdarzenie):
        # Kliknięcie wpisu na liście: wyróżniamy pas na wykresie i przewijamy film do początku zdarzenia
        self._timeline.wyroznij_zdarzenie(zdarzenie)
        start = bezpieczny_odczyt(zdarzenie, "start")
        if start is None or not self._liczba_klatek or not self._fps:
            return
        self._przewin_do_klatki(czas_na_klatke(start, self._fps, self._liczba_klatek))

    def _na_klik_wykres(self, czas):
        # Kliknięcie na wykresie: czas -> numer klatki -> przewinięcie. Bez filmu nie ma dokąd przewijać.
        if not self._liczba_klatek or not self._fps:
            return
        self._przewin_do_klatki(czas_na_klatke(czas, self._fps, self._liczba_klatek))

    def _reset(self):
        self._akcja_start.setChecked(False)  # najpierw pauza
        self._reset_workera()
        self.statusBar().showMessage("Od nowa – naciśnij Start, aby odtworzyć")

    def _reset_workera(self):
        self._wyczysc_wyniki()
        self._na_koncu = False
        self.sygnal_reset.emit()

    def _wyczysc_wyniki(self):
        self._wyniki.clear()
        self._wyniki_zmienione = False
        self._biezaca_klatka = 0
        self._ostatni_czas = 0.0
        self._timeline.set_data(np.array([]), np.array([]))
        self._timeline.ustaw_kursor(0.0)
        self._suwak.ustaw_klatke(0)
        self._wyczysc_zdarzenia()
        self._panel.wyczysc()
        self._aktualizuj_etykiete()

    def _wyczysc_zdarzenia(self):
        # Zdarzenia znikają z bufora, wykresu i listy naraz (Reset, nowy plik, zmiana ustawień)
        self._zdarzenia.clear()
        self._timeline.wyczysc_zdarzenia()
        self._panel.wyczysc_zdarzenia()

    # Sloty GUI: uruchamiane w wątku okna, gdy worker wyśle sygnał-----------
    def _na_zrodlo(self, info):
        # Worker potwierdził otwarcie pliku. Zapamiętujemy dane i ustawiamy oś X na długość filmu.
        self._nazwa_pliku = Path(info["path"]).name
        self._fps = info["fps"]
        self._dlugosc = info["duration"]
        self._liczba_klatek = info["frame_count"]
        self._timeline.ustaw_zakres_czasu(self._dlugosc)
        self._suwak.ustaw_zakres(self._liczba_klatek, self._fps)
        self._akcja_start.setEnabled(True)  # film jest, więc można odtwarzać
        self._akcja_start.setToolTip("")
        self._aktualizuj_etykiete()

    def _na_klatke(self, ramka, wynik):
        self._wideo.show_frame(ramka)
        numer = bezpieczny_odczyt(wynik, "frame_idx")
        if numer is not None:
            self._zapisz_wynik(numer, wynik)
            self._biezaca_klatka = numer
        czas = bezpieczny_odczyt(wynik, "timestamp")
        if czas is not None:
            self._ostatni_czas = czas
        # Panel boczny pokazuje kąty tej klatki od razu, także po przewinięciu w pauzie
        self._panel.pokaz_wynik(wynik)
        self._odswiez_pozycje()

    def _na_caly_film(self, wyniki):
        # Worker policzył cały film naraz. Wpisujemy wyniki do bufora tak jak klatki na żywo,
        # a wykres przerysuje się w najbliższym odświeżeniu (co 100 ms).
        for wynik in wyniki:
            numer = bezpieczny_odczyt(wynik, "frame_idx")
            if numer is not None:
                self._zapisz_wynik(numer, wynik)
        self._wyniki_zmienione = True

    def _zapisz_wynik(self, numer, wynik):
        self._wyniki[numer] = wynik  # nadpisuje wpis, jeśli ta klatka już była
        self._wyniki_zmienione = True
        if len(self._wyniki) > MAX_PUNKTOW:
            # Usuwamy najstarszy wpis (pierwszy w kolejności dodawania), żeby pamięć nie rosła bez końca
            del self._wyniki[next(iter(self._wyniki))]

    def _odswiez_pozycje(self):
        # Kursor na wykresie, suwak i licznik czasu idą za bieżącą klatką
        self._timeline.ustaw_kursor(self._ostatni_czas)
        self._suwak.ustaw_klatke(self._biezaca_klatka)
        self._aktualizuj_etykiete()

    def _na_ustawienia(self, ustawienia):
        # Jedno miejsce na zmianę ustawień: wykres, panel boczny i worker dostają to samo.
        # Zdarzenia z poprzednich progów przestają być prawdziwe, więc je kasujemy.
        self._wyczysc_zdarzenia()
        progi = ustawienia["thresholds"]
        self._timeline.set_thresholds(progi["warning"], progi["alarm"])
        self._panel.ustaw_progi(progi["warning"], progi["alarm"])
        stawy = list(ustawienia["joints"])
        self._timeline.ustaw_opis_stawow(stawy)
        # Krzywa SI to średnia z wybranych stawów, więc zmiana wyboru unieważnia bufor.
        # Zmiana samych progów tego nie robi (zmieniają tylko kolory).
        if stawy != self._ostatnie_stawy:
            self._ostatnie_stawy = stawy
            self._wyniki.clear()
            self._wyniki_zmienione = True  # wykres zostanie przerysowany w najbliższym odświeżeniu
        self._panel.ustaw_stawy(stawy)
        self.sygnal_ustawienia.emit(ustawienia)

    def _na_zdarzenie(self, zdarzenie):
        staw = bezpieczny_odczyt(zdarzenie, "joint")
        start = bezpieczny_odczyt(zdarzenie, "start")
        if start is None:
            return  # bez czasu startu nie ma gdzie narysować pasa
        # Zaokrąglamy start, żeby ten sam czas z kolejnych przebiegów dał ten sam klucz
        klucz = (staw, round(start, 3))
        if klucz in self._zdarzenia:
            return  # to samo zdarzenie już mamy, np. po przewinięciu do tyłu i ponownym odtworzeniu
        self._zdarzenia[klucz] = zdarzenie
        self._timeline.dodaj_zdarzenie(zdarzenie)
        self._panel.dodaj_zdarzenie(zdarzenie)
        self.statusBar().showMessage(f"Zdarzenie: {staw} ({bezpieczny_odczyt(zdarzenie, 'level')})")

    def _na_blad(self, tekst):
        self._akcja_start.setChecked(False)  # zatrzymujemy odtwarzanie; ustawia to też komunikat „Pauza”
        self.statusBar().showMessage(f"Błąd: {tekst}")  # komunikat błędu wysyłamy na końcu, żeby go nie nadpisało

    def _na_koniec(self):
        # Film dobiegł końca: zostajemy na ostatniej klatce, a przycisk wraca do „Start”
        self._na_koncu = True
        self._akcja_start.setChecked(False)
        self.statusBar().showMessage("Koniec nagrania – Start odtworzy od początku")

    # Odświeżanie wykresu: QTimer co 100 ms, a nie przy każdej klatce------------------
    def _utworz_odswiezanie(self):
        self._odswiezanie = QTimer(self)  # rodzicem jest okno, więc timer działa w wątku GUI
        self._odswiezanie.setInterval(100)  # 10 razy na sekundę
        self._odswiezanie.timeout.connect(self._odswiez_timeline)
        self._odswiezanie.start()

    def _odswiez_timeline(self):
        # Przerysowujemy wykres tylko wtedy, gdy doszły nowe wyniki (nie co 100 ms bez powodu)
        if self._wyniki_zmienione:
            self._wyniki_zmienione = False
            czasy, si = self._dane_wykresu()
            self._timeline.set_data(czasy, si)
        self._aktualizuj_etykiete()

    def _dane_wykresu(self):
        """Zamienia słownik wyników na dwie tablice (czas, SI) w kolejności numerów klatek.

        Gdy między dwoma kolejnymi wynikami brakuje klatek (np. po przewinięciu do przodu),
        wstawiamy pusty punkt (NaN). Wykres wtedy urywa linię zamiast łączyć dwa odległe
        miejsca prostą. Dane w buforze nie są kasowane, więc po powrocie linia się uzupełnia.
        """
        czasy = []
        si_wartosci = []
        poprzedni_numer = None
        # Sortujemy po numerze klatki, a nie po kolejności dodania do słownika (po przewinięciu się różnią)
        for numer in sorted(self._wyniki):
            wynik = self._wyniki[numer]
            czas = bezpieczny_odczyt(wynik, "timestamp")
            if czas is None:
                continue  # bez czasu nie ma gdzie wstawić punktu na wykresie
            if poprzedni_numer is not None and numer - poprzedni_numer > 1:
                # Brakuje klatek między poprzednim a tym punktem: przerwa w linii
                czasy.append(czas)
                si_wartosci.append(np.nan)
            si = bezpieczny_odczyt(wynik, "si", "total")
            czasy.append(czas)
            si_wartosci.append(np.nan if si is None else si)  # NaN też zostawia lukę w wykresie
            poprzedni_numer = numer
        return np.array(czasy, dtype=float), np.array(si_wartosci, dtype=float)

    # Zamykanie okna------------------------------------------------
    def closeEvent(self, event):
        # 1) zwalniamy plik wideo w wątku workera i czekamy, aż to zrobi
        QMetaObject.invokeMethod(self._worker, "zamknij", Qt.ConnectionType.BlockingQueuedConnection)
        # 2) kończymy pętlę zdarzeń wątku i czekamy, aż wątek naprawdę się zakończy
        self._watek.quit()
        self._watek.wait()
        super().closeEvent(event)
