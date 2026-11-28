"""Worker: odtwarza film i analizuje go w tle. Działa w osobnym wątku (QThread)."""

import time

import cv2
import numpy as np
from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot

from GUI.adapter_csv import BladCsv
from GUI.potok import PotokAtrapa, analizowane_stawy, srednia_si, wybierz_potok

FPS_DOMYSLNY = 30  # gdy plik nie podaje fps albo nie ma pliku
BUDZET_PORCJI_S = 0.02  # ile analiza pracuje naraz, zanim odda pętlę zdarzeń
KROK_POSTEPU = 10  # co ile klatek wysyłamy postęp


class AnalizaWorker(QObject):
    """Odtwarza film i analizuje go. Potok wybiera wybierz_potok."""

    source_opened = Signal(dict)  # fps, liczba klatek, długość
    frame_processed = Signal(np.ndarray, dict)  # klatka BGR i wynik klatki
    analiza_start = Signal(int)  # liczba klatek do analizy
    postep = Signal(int)  # ile klatek już przeanalizowano
    analiza_zakonczona = Signal(bool)  # True: gotowe; False: anulowana albo błąd
    wyniki_calego_filmu = Signal(list)  # lekkie wyniki: frame_idx, timestamp, si
    event_detected = Signal(dict)  # zdarzenie asymetrii
    finished = Signal()  # koniec pliku przy odtwarzaniu
    error = Signal(str)  # komunikat błędu
    dane_zrodla = Signal(dict)  # skąd dane (CSV czy atrapa) i ostrzeżenie

    def __init__(self):
        super().__init__()
        self._cap = None  # plik do odtwarzania; None = tryb bez pliku
        self._cap_analizy = None  # osobny odczyt do analizy
        self._sciezka = None
        self._fps = FPS_DOMYSLNY
        self._liczba_klatek = None
        self._klatka = 0  # kolejna klatka do odtworzenia
        self._ustawienia = {}
        self._potok = PotokAtrapa()
        self._ostrzezenie_csv = None
        self._wyniki_surowe = None  # wyniki całego filmu; None przed końcem analizy
        self._wyniki_w_toku = []
        self._analiza_numer = 0  # numer następnej klatki do analizy

        self._timer = QTimer(self)  # odtwarzanie: co 1/fps
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(max(1, round(1000 / self._fps)))
        self._timer.timeout.connect(self._krok)

        self._timer_analizy = QTimer(self)  # analiza: porcja po porcji
        self._timer_analizy.setInterval(0)
        self._timer_analizy.timeout.connect(self._krok_analizy)

    # Sloty: wywoływane przez GUI sygnałami
    @Slot(str)
    def open_source(self, sciezka):
        """Otwiera plik, wybiera potok i startuje analizę."""
        self._otworz(sciezka)

    @Slot(str)
    def wczytaj_csv(self, sciezka):
        """Ręcznie wybrany CSV: analiza startuje od nowa."""
        if self._cap is None:
            return
        try:
            potok = wybierz_potok(self._sciezka, sciezka)
        except BladCsv as blad:
            self.error.emit(str(blad))
            return
        self._potok = potok
        self._ostrzezenie_csv = None
        self._wyslij_zrodlo()
        self._zacznij_analize()
        self.seek(max(self._klatka - 1, 0))

    @Slot()
    def start(self):
        """Odtwarzanie od bieżącej klatki."""
        self._timer.start()

    @Slot()
    def stop(self):
        """Pauza."""
        self._timer.stop()

    @Slot()
    def anuluj(self):
        """Przerywa analizę i odrzuca wyniki częściowe."""
        if not self._timer_analizy.isActive():
            return
        self._zatrzymaj_analize()
        self.analiza_zakonczona.emit(False)

    @Slot()
    def reset(self):
        """Wraca na pierwszą klatkę i wysyła wyniki ponownie (albo startuje analizę)."""
        if self._cap is None:
            return
        self._timer.stop()
        self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        self._klatka = 0
        if self._wyniki_surowe is not None:
            self._przelicz_i_wyslij()
        else:
            self._zacznij_analize()

    @Slot(int)
    def seek(self, numer_klatki):
        """Przewija do klatki i wysyła jej wynik. Stan odtwarzania się nie zmienia."""
        if self._cap is None:
            return
        if self._liczba_klatek is not None:
            numer_klatki = min(max(numer_klatki, 0), self._liczba_klatek - 1)
        try:
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, numer_klatki)
            ok, ramka = self._cap.read()
            if not ok:
                self.error.emit(f"Nie udało się odczytać klatki {numer_klatki}")
                return
            # OpenCV może przeskoczyć do klatki kluczowej, więc numer bierzemy z pliku
            numer_faktyczny = int(self._cap.get(cv2.CAP_PROP_POS_FRAMES)) - 1
            self._klatka = numer_faktyczny + 1
            self.frame_processed.emit(ramka, self._wynik_klatki(ramka, numer_faktyczny))
        except Exception as blad:
            self.error.emit(f"Przewijanie: {blad}")

    @Slot(dict)
    def set_settings(self, ustawienia):
        """Zapisuje ustawienia i przelicza część lekką, jeśli analiza jest gotowa."""
        self._ustawienia = dict(ustawienia)
        if self._wyniki_surowe is not None:
            self._przelicz_i_wyslij()
            if self._cap is not None:
                self.seek(max(self._klatka - 1, 0))

    @Slot()
    def zamknij(self):
        """Zatrzymuje budziki i zwalnia pliki przed zamknięciem okna."""
        self._timer.stop()
        self._zatrzymaj_analize()
        self._zwolnij_plik()

    # Otwieranie pliku
    def _otworz(self, sciezka):
        self._zatrzymaj_analize()
        self._timer.stop()
        self._zwolnij_plik()
        cap = cv2.VideoCapture(sciezka)
        if not cap.isOpened():
            self._sciezka = None
            self.error.emit(f"Nie udało się otworzyć pliku: {sciezka} (zły format lub brak kodeka)")
            return
        fps = cap.get(cv2.CAP_PROP_FPS)
        fps = fps if fps and fps > 0 else FPS_DOMYSLNY
        liczba_klatek = self._policz_klatki(cap)  # CAP_PROP_FRAME_COUNT bywa błędny
        cap.release()
        if liczba_klatek == 0:
            self._sciezka = None
            self.error.emit(f"Plik nie zawiera klatek: {sciezka}")
            return
        self._cap = cv2.VideoCapture(sciezka)  # ponowne otwarcie: pozycja wraca na początek
        self._sciezka = sciezka
        self._fps = fps
        self._liczba_klatek = liczba_klatek
        self._timer.setInterval(max(1, round(1000 / self._fps)))
        self._klatka = 0
        self._wybierz_potok_dla(sciezka)
        self.source_opened.emit(
            {
                "path": sciezka,
                "fps": self._fps,
                "frame_count": liczba_klatek,
                "duration": liczba_klatek / self._fps,
            }
        )
        self._wyslij_zrodlo()
        self._zacznij_analize()

    def _wybierz_potok_dla(self, sciezka):
        """Wybiera potok; uszkodzony CSV daje atrapę z ostrzeżeniem."""
        self._ostrzezenie_csv = None
        try:
            self._potok = wybierz_potok(sciezka)
        except BladCsv as blad:
            self._potok = PotokAtrapa()
            self._ostrzezenie_csv = str(blad)

    def _wyslij_zrodlo(self):
        """Wysyła GUI informację o źródle danych i ewentualnym ostrzeżeniu."""
        info = self._potok.opis_zrodla()
        ostrzezenie = self._ostrzezenie_csv
        klatek = info.get("klatek")
        if klatek is not None and self._liczba_klatek is not None and abs(self._liczba_klatek - klatek) > 2:
            ostrzezenie = f"liczba klatek nie zgadza się: film {self._liczba_klatek}, CSV {klatek}"
        info["ostrzezenie"] = ostrzezenie
        self.dane_zrodla.emit(info)

    def _zwolnij_plik(self):
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    @staticmethod
    def _policz_klatki(cap):
        """Liczy klatki przez grab(), które nie dekoduje obrazu."""
        liczba = 0
        while cap.grab():
            liczba += 1
        return liczba

    # Analiza całego filmu, porcjami
    def _zacznij_analize(self):
        self._zatrzymaj_analize()
        self._timer.stop()
        self._wyniki_surowe = None
        cap = cv2.VideoCapture(self._sciezka)
        if not cap.isOpened():
            self.error.emit(f"Nie udało się ponownie otworzyć pliku do analizy: {self._sciezka}")
            return
        self._cap_analizy = cap
        self._analiza_numer = 0
        self._wyniki_w_toku = []
        self.analiza_start.emit(self._liczba_klatek)
        self._timer_analizy.start()

    def _krok_analizy(self):
        """Analizuje klatki przez BUDZET_PORCJI_S, potem oddaje pętlę zdarzeń."""
        koniec_porcji = time.perf_counter() + BUDZET_PORCJI_S
        try:
            while time.perf_counter() < koniec_porcji:
                if self._analiza_numer >= self._liczba_klatek:
                    self._zakoncz_analize()
                    return
                ok, ramka = self._cap_analizy.read()
                if not ok:
                    raise RuntimeError(f"nie udało się odczytać klatki {self._analiza_numer}")
                numer = self._analiza_numer
                wynik = self._potok.analizuj_klatke(ramka, numer, numer / self._fps)
                self._wyniki_w_toku.append({"frame_idx": numer, "timestamp": wynik["timestamp"], "si": wynik["si"]})
                self._analiza_numer += 1
                if self._analiza_numer % KROK_POSTEPU == 0:
                    self.postep.emit(self._analiza_numer)
        except Exception as blad:
            self._zatrzymaj_analize()
            self.error.emit(f"Analiza: {blad}")
            self.analiza_zakonczona.emit(False)

    def _zakoncz_analize(self):
        self._timer_analizy.stop()
        self._cap_analizy.release()
        self._cap_analizy = None
        self._wyniki_surowe = self._wyniki_w_toku
        self._wyniki_w_toku = []
        self.postep.emit(self._analiza_numer)
        self._przelicz_i_wyslij()
        self.analiza_zakonczona.emit(True)

    def _zatrzymaj_analize(self):
        """Zatrzymuje analizę i odrzuca wyniki częściowe. Można wywołać, gdy analiza nie trwa."""
        self._timer_analizy.stop()
        if self._cap_analizy is not None:
            self._cap_analizy.release()
            self._cap_analizy = None
        self._wyniki_w_toku = []

    def _przelicz_i_wyslij(self):
        """Część lekka na zapisanych wynikach; wysyła wykres i zdarzenia."""
        try:
            wyniki, zdarzenia = self._potok.przelicz_lekkie(self._wyniki_surowe, self._ustawienia)
        except Exception as blad:
            self.error.emit(f"Przeliczenie wyników: {blad}")
            return
        self.wyniki_calego_filmu.emit(wyniki)
        for zdarzenie in zdarzenia:
            self.event_detected.emit(zdarzenie)

    # Odtwarzanie
    def _krok(self):
        """Wysyła kolejną klatkę (wywoływane przez budzik)."""
        try:
            if self._cap is None:
                ramka = np.zeros((480, 640, 3), dtype=np.uint8)  # czarna klatka bez pliku
            else:
                ok, ramka = self._cap.read()
                if not ok:
                    self._timer.stop()
                    self.finished.emit()
                    return
            self.frame_processed.emit(ramka, self._wynik_klatki(ramka, self._klatka))
            self._klatka += 1
        except Exception as blad:
            self._timer.stop()
            self.error.emit(f"Atrapa potoku: {blad}")

    def _wynik_klatki(self, ramka, numer):
        """Wynik klatki z potoku, ze średnią SI z wybranych stawów."""
        wynik = self._potok.analizuj_klatke(ramka, numer, numer / self._fps)
        if wynik.get("si") is not None:
            wynik["si"]["total"] = srednia_si(wynik["si"], analizowane_stawy(self._ustawienia))
        return wynik
