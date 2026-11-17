import math

import cv2
import numpy as np
from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot

from GUI.gui_data_format import DEFAULT_JOINTS, LICZBA_LANDMARKS

FPS_DOMYSLNY = 30  # tempo bez pliku (czarna klatka) i gdy plik nie podaje swojego fps
# Parametry atrapy – te liczby są wymyślone, żeby wykres był czytelny
KAT_SRODKOWY = 120.0  # średni kąt w stawie [°]
AMPLITUDA_L = 40.0  # lewa strona rusza się bardziej
AMPLITUDA_R = 25.0  # prawa strona – mniejsza amplituda = asymetria
OKRES_EPIZODU_S = 8.0  # co ile sekund pojawia się 'epizod' większej asymetrii
POCZATEK_EPIZODU_S = 5.0  # w którym momencie cyklu epizod się zaczyna
PROG_ALARMU_ATRAPY = 20.0  # tylko do wyboru poziomu zdarzenia w atrapie


class MockWorker(QObject):
    """Źródło wideo i atrapa potoku zespołu. Działa w osobnym wątku.

    Czyta plik wideo (OpenCV), a dla każdej klatki udaje wynik potoku:
    kąty, SI, landmarks. Nic z tego nie jest prawdziwą analizą.
    Odczyt wideo jest tymczasowy – docelowo dostarczy go moduł capture zespołu.

    Dziedziczy po QObject, bo tylko obiekty QObject mogą wysyłać sygnały
    i być przenoszone do innego wątku (moveToThread).
    """

    # Sygnały: worker 'krzyczy' je w swoim wątku, a GUI odbiera w swoim.
    source_opened = Signal(dict)  # info o otwartym pliku: fps, liczba klatek, długość
    frame_processed = Signal(np.ndarray, dict)  # klatka obrazu (BGR) + wynik klatki
    event_detected = Signal(dict)  # zdarzenie asymetrii
    finished = Signal()  # koniec pliku wideo
    error = Signal(str)  # komunikat błędu

    def __init__(self):
        super().__init__()
        self._cap = None  # otwarty plik wideo (cv2.VideoCapture) albo None = tryb bez pliku
        self._sciezka = None  # ścieżka do pliku – potrzebna, żeby Reset mógł otworzyć go od nowa
        self._fps = FPS_DOMYSLNY
        self._klatka = 0  # numer aktualnej klatki
        self._ustawienia = {}  # na razie tylko zapamiętujemy (użyjemy w zadaniu 7)
        self._epizod = None  # dane bieżącego epizodu asymetrii, jeśli trwa

        # QTimer = 'budzik', który wywołuje _krok() co 1/fps sekundy.
        # Rodzic = self, więc po moveToThread timer przenosi się razem z workerem.
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)  # dokładniejszy budzik na Windows
        self._timer.setInterval(max(1, round(1000 / self._fps)))
        self._timer.timeout.connect(self._krok)

    # ------------------------------------------------------------------
    # Sloty – metody, które GUI wywołuje przez sygnał.
    # ------------------------------------------------------------------
    @Slot(str)
    def open_source(self, sciezka):
        """Otwiera plik wideo i ustawia odtwarzanie na pierwszą klatkę."""
        self._timer.stop()
        if self._cap is not None:
            self._cap.release()  # zwalniamy poprzedni plik
            self._cap = None
        cap = cv2.VideoCapture(sciezka)
        if not cap.isOpened():
            self._sciezka = None  # nieudany plik nie może zostać w pamięci jako 'ostatni'
            self.error.emit(f"Nie udało się otworzyć pliku: {sciezka} (zły format lub brak kodeka)")
            return
        self._cap = cap
        self._sciezka = sciezka
        fps = cap.get(cv2.CAP_PROP_FPS)
        self._fps = fps if fps and fps > 0 else FPS_DOMYSLNY
        liczba_klatek = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self._timer.setInterval(max(1, round(1000 / self._fps)))  # np. 30 fps -> 33 ms
        self._klatka = 0
        self._epizod = None
        # Długość filmu liczymy z liczby klatek i fps. Niektóre pliki nie podają liczby klatek (0 lub -1).
        dlugosc = liczba_klatek / self._fps if liczba_klatek > 0 else None
        self.source_opened.emit(
            {
                "path": sciezka,
                "fps": self._fps,
                "frame_count": liczba_klatek if liczba_klatek > 0 else None,
                "duration": dlugosc,
            }
        )

    @Slot()
    def start(self):
        """Odtwarzanie: wznawia od bieżącej klatki (bez pliku: czarna klatka)."""
        self._timer.start()

    @Slot()
    def stop(self):
        """Pauza: zatrzymuje odtwarzanie, ale zostaje na tej samej klatce."""
        self._timer.stop()

    @Slot()
    def reset(self):
        """Od nowa: wraca na pierwszą klatkę (ponownie otwiera plik)."""
        if self._sciezka is not None:
            self.open_source(self._sciezka)
        else:
            self._klatka = 0
            self._epizod = None

    @Slot()
    def zamknij(self):
        """Przed zamknięciem okna: zatrzymuje timer i zwalnia plik."""
        self._timer.stop()
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    @Slot(dict)
    def set_settings(self, ustawienia):
        # Na razie tylko zapamiętujemy. Prawdziwe użycie (progi, stawy) dojdzie w zadaniu 7.
        self._ustawienia = dict(ustawienia)

    # ------------------------------------------------------------------
    # Wewnętrzna praca – wywoływana przez timer co 1/fps sekundy
    # ------------------------------------------------------------------
    def _krok(self):
        try:
            if self._cap is None:
                # Tryb bez pliku: czarna klatka, bez końca
                ramka = np.zeros((480, 640, 3), dtype=np.uint8)
            else:
                # Odczyt następnej klatki z pliku. ok=False oznacza koniec pliku.
                ok, ramka = self._cap.read()
                if not ok:
                    self._timer.stop()  # zatrzymujemy na ostatniej klatce
                    self.finished.emit()
                    return

            t = self._klatka / self._fps  # czas z numeru klatki, nie z zegara ściennego
            katy = self._katy_atrapy(t)
            si = self._si_atrapy(katy)
            landmarks = self._landmarks_atrapy(t)
            self._sledz_epizod(t, si["total"])

            wynik = {
                "frame_idx": self._klatka,
                "timestamp": round(t, 3),
                "angles": katy,
                "si": si,
                "landmarks": landmarks,
            }
            self.frame_processed.emit(ramka, wynik)
            self._klatka += 1
        except Exception as blad:  # błąd nie może zabić wątku po cichu – zgłaszamy go GUI
            self._timer.stop()
            self.error.emit(f"Atrapa potoku: {blad}")

    def _katy_atrapy(self, t):
        """Kąty L/P dla każdego stawu: sinusoidy z różnymi amplitudami."""
        # Gdy trwa epizod, prawa strona dostaje dodatkowe 'osłabienie' (większą asymetrię)
        cykl_t = t % OKRES_EPIZODU_S
        dodatek = 0.0
        if cykl_t >= POCZATEK_EPIZODU_S:
            dlugosc = OKRES_EPIZODU_S - POCZATEK_EPIZODU_S  # 3 s trwania epizodu
            dodatek = 30.0 * math.sin(math.pi * (cykl_t - POCZATEK_EPIZODU_S) / dlugosc)

        katy = {}
        for i, staw in enumerate(DEFAULT_JOINTS):
            faza = 2 * math.pi * 0.25 * t + i * 0.7  # każdy staw trochę przesunięty w czasie
            # Co jakiś czas jeden staw 'znika' – sprawdzamy, czy GUI to wytrzyma
            if (self._klatka % 300) in range(60, 75) and staw == "knee":
                katy[staw] = None
                continue
            katy[staw] = {
                "L": KAT_SRODKOWY + AMPLITUDA_L * math.sin(faza),
                "R": KAT_SRODKOWY + AMPLITUDA_R * math.sin(faza) - dodatek,
            }
        return katy

    def _si_atrapy(self, katy):
        """SI ze wzoru |L−R| / (0.5·(L+R)) · 100 – tylko dla atrapy potoku."""
        si = {}
        dostepne = []
        for staw in DEFAULT_JOINTS:
            dane = katy.get(staw)
            if dane is None:  # brak stawu -> brak SI
                si[staw] = None
                continue
            l, r = dane["L"], dane["R"]
            wartosc = abs(l - r) / (0.5 * (l + r)) * 100.0
            si[staw] = wartosc
            dostepne.append(wartosc)
        # total = średnia z dostępnych stawów (albo None, gdy nie ma żadnego)
        si["total"] = sum(dostepne) / len(dostepne) if dostepne else None
        return si

    def _landmarks_atrapy(self, t):
        """33 punkty szkieletu krążące wokół środka kadru; None, gdy 'brak osoby'."""
        if (self._klatka % 450) in range(400, 430):
            return None  # przez chwilę nie ma osoby w kadrze
        punkty = []
        for k in range(LICZBA_LANDMARKS):
            kat = 2 * math.pi * k / LICZBA_LANDMARKS + t
            x = 0.5 + 0.1 * math.cos(kat)  # współrzędne 0–1, jak u MediaPipe
            y = 0.5 + 0.3 * math.sin(kat)
            punkty.append((x, y, 0.95))  # 0.95 = pewność, że punkt jest widoczny
        return punkty

    def _sledz_epizod(self, t, si_total):
        """Pamięta epizod asymetrii i po jego zakończeniu wysyła zdarzenie."""
        w_epizodzie = (t % OKRES_EPIZODU_S) >= POCZATEK_EPIZODU_S
        if w_epizodzie:
            if self._epizod is None:
                self._epizod = {"start": round(t, 3), "si_max": 0.0}
            if si_total is not None:
                self._epizod["si_max"] = max(self._epizod["si_max"], si_total)
        elif self._epizod is not None:
            # epizod właśnie się skończył -> wysyłamy zdarzenie w formacie z gui_data_format
            si_max = self._epizod["si_max"]
            zdarzenie = {
                "start": self._epizod["start"],
                "end": round(t, 3),
                "joint": "elbow",  # atrapa – zawsze łokieć
                "level": "alarm" if si_max >= PROG_ALARMU_ATRAPY else "warning",
                "si_max": round(si_max, 1),
            }
            self._epizod = None
            self.event_detected.emit(zdarzenie)
