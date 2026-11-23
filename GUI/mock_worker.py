import math

import cv2
import numpy as np
from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot

from GUI.gui_data_format import DEFAULT_JOINTS, LICZBA_LANDMARKS

FPS_DOMYSLNY = 30  # tempo bez pliku (czarna klatka) i wtedy, gdy plik nie podaje swojego fps

# Parametry atrapy. Liczby są wymyślone, tak żeby wykres wyglądał czytelnie.
KAT_SRODKOWY = 120.0  # średni kąt w stawie [°]
AMPLITUDA_L = 40.0  # lewa strona rusza się bardziej
AMPLITUDA_R = 25.0  # prawa strona ma mniejszą amplitudę, czyli udaje asymetrię
OKRES_EPIZODU_S = 8.0  # co ile sekund powtarza się epizod z większą asymetrią
POCZATEK_EPIZODU_S = 5.0  # w którym momencie cyklu epizod się zaczyna
PROG_ALARMU_ATRAPY = 20.0  # używany tylko do wyboru poziomu zdarzenia w atrapie


class MockWorker(QObject):
    """Źródło wideo i atrapa potoku zespołu. Działa w osobnym wątku.

    Czyta plik wideo przez OpenCV i dla każdej klatki udaje wynik potoku:
    kąty, SI i landmarks. Wszystkie te wyniki są sztuczne.

    Dziedziczy po QObject, bo tylko obiekty QObject mogą wysyłać sygnały
    i być przenoszone do innego wątku (moveToThread).
    """

    # Sygnały: worker je wysyła ze swojego wątku, a GUI odbiera we własnym.
    source_opened = Signal(dict)  # info o otwartym pliku: fps, liczba klatek, długość
    frame_processed = Signal(np.ndarray, dict)  # klatka obrazu (BGR) i wynik klatki
    event_detected = Signal(dict)  # zdarzenie asymetrii
    finished = Signal()  # koniec pliku wideo
    error = Signal(str)  # komunikat błędu

    def __init__(self):
        super().__init__()
        self._cap = None  # otwarty plik wideo (cv2.VideoCapture); None oznacza tryb bez pliku
        self._sciezka = None  # ścieżka do pliku, potrzebna, żeby Reset mógł otworzyć go od nowa
        self._fps = FPS_DOMYSLNY
        self._klatka = 0  # numer bieżącej klatki
        self._ustawienia = {}  # ustawienia przekazane przez set_settings
        self._epizod = None  # dane trwającego epizodu asymetrii, jeśli taki jest
        self._liczba_klatek = None  # ile klatek ma plik; None, gdy nieznane albo brak pliku

        # QTimer działa jak budzik: co 1/fps sekundy wywołuje _krok().
        # Rodzicem jest self, więc po moveToThread timer przenosi się razem z workerem.
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)  # dokładniejszy budzik na Windows
        self._timer.setInterval(max(1, round(1000 / self._fps)))
        self._timer.timeout.connect(self._krok)

    # ------------------------------------------------------------------
    # Sloty to metody, które GUI wywołuje przez sygnał.
    # ------------------------------------------------------------------
    @Slot(str)
    def open_source(self, sciezka):
        """Otwiera plik wideo i ustawia odtwarzanie na pierwszą klatkę."""
        self._timer.stop()
        if self._cap is not None:
            self._cap.release()  # zwalniamy poprzedni plik, zanim otworzymy nowy
            self._cap = None
        cap = cv2.VideoCapture(sciezka)
        if not cap.isOpened():
            self._sciezka = None  # nieudany plik nie może zostać w pamięci jako ostatni
            self.error.emit(f"Nie udało się otworzyć pliku: {sciezka} (zły format lub brak kodeka)")
            return
        self._cap = cap
        self._sciezka = sciezka
        fps = cap.get(cv2.CAP_PROP_FPS)
        self._fps = fps if fps and fps > 0 else FPS_DOMYSLNY
        liczba_klatek = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self._timer.setInterval(max(1, round(1000 / self._fps)))  # np. 30 fps daje 33 ms
        self._klatka = 0
        self._epizod = None
        self._liczba_klatek = liczba_klatek if liczba_klatek > 0 else None
        # Długość filmu liczymy z liczby klatek i fps. Niektóre pliki nie podają liczby klatek (0 albo -1).
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
        """Odtwarzanie: wznawia od bieżącej klatki (bez pliku pojawia się czarna klatka)."""
        self._timer.start()

    @Slot()
    def stop(self):
        """Pauza: zatrzymuje odtwarzanie, ale zostaje na tej samej klatce."""
        self._timer.stop()

    @Slot()
    def reset(self):
        """Od nowa: wraca na pierwszą klatkę, otwierając plik ponownie."""
        if self._sciezka is not None:
            self.open_source(self._sciezka)
        else:
            self._klatka = 0
            self._epizod = None

    @Slot(int)
    def seek(self, numer_klatki):
        """Przewija do klatki i wysyła jej wynik. Stan odtwarzania (gra/pauza) się nie zmienia.

        Timer nie jest ruszany: jeśli film grał, gra dalej od nowej pozycji, a jeśli stał, dalej stoi.
        """
        if self._cap is None:
            return  # bez pliku nie ma czego przewijać
        if self._liczba_klatek is not None:
            numer_klatki = min(max(numer_klatki, 0), self._liczba_klatek - 1)
        try:
            # Ustawiamy pozycję w pliku i odczytujemy jedną klatkę
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, numer_klatki)
            ok, ramka = self._cap.read()
            if not ok:
                self.error.emit(f"Nie udało się odczytać klatki {numer_klatki}")
                return
            # Niektóre formaty przeskakują do najbliższej klatki kluczowej. Dlatego numer bierzemy
            # z pliku (po odczycie pozycja wskazuje klatkę następną), a nie z żądania.
            numer_faktyczny = int(self._cap.get(cv2.CAP_PROP_POS_FRAMES)) - 1
            self._klatka = numer_faktyczny + 1  # kolejna klatka, którą odczyta odtwarzanie
            self._epizod = None  # epizod z poprzedniej pozycji nie ma sensu po skoku
            self.frame_processed.emit(ramka, self._zbuduj_wynik(numer_faktyczny))
        except Exception as blad:
            self.error.emit(f"Przewijanie: {blad}")

    @Slot()
    def zamknij(self):
        """Wywoływane przed zamknięciem okna: zatrzymuje timer i zwalnia plik."""
        self._timer.stop()
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    @Slot(dict)
    def set_settings(self, ustawienia):
        # Zapamiętujemy ustawienia. Wybrane stawy wpływają na kąty i SI (jak w prawdziwym potoku).
        # Progi i typ ćwiczenia na razie tylko zapamiętujemy.
        self._ustawienia = dict(ustawienia)

    def _analizowane_stawy(self):
        # Bez ustawień analizujemy wszystkie stawy z listy domyślnej
        return self._ustawienia.get("joints", DEFAULT_JOINTS)

    # ------------------------------------------------------------------
    # Praca wewnętrzna, wywoływana przez timer co 1/fps sekundy
    # ------------------------------------------------------------------
    def _krok(self):
        try:
            if self._cap is None:
                # Tryb bez pliku: czarna klatka, bez końca
                ramka = np.zeros((480, 640, 3), dtype=np.uint8)
            else:
                # Czytamy kolejną klatkę. ok=False oznacza koniec pliku.
                ok, ramka = self._cap.read()
                if not ok:
                    self._timer.stop()  # zatrzymujemy się na ostatniej klatce
                    self.finished.emit()
                    return

            wynik = self._zbuduj_wynik(self._klatka)
            self._sledz_epizod(wynik["timestamp"], wynik["si"]["total"])
            self.frame_processed.emit(ramka, wynik)
            self._klatka += 1
        except Exception as blad:  # błąd nie może cicho zabić wątku, więc zgłaszamy go GUI
            self._timer.stop()
            self.error.emit(f"Atrapa potoku: {blad}")

    def _zbuduj_wynik(self, numer):
        """Wynik jednej klatki. Zależy tylko od numeru klatki i fps, a nie od historii odtwarzania.

        Dzięki temu po przewinięciu ta sama klatka zawsze ma te same wartości.
        """
        t = numer / self._fps  # czas liczymy z numeru klatki, nie z zegara ściennego
        katy = self._katy_atrapy(t, numer)
        si = self._si_atrapy(katy)
        return {
            "frame_idx": numer,
            "timestamp": round(t, 3),
            "angles": katy,
            "si": si,
            "landmarks": self._landmarks_atrapy(t, numer),
        }

    def _katy_atrapy(self, t, numer):
        """Kąty L/P dla każdego stawu: sinusoidy o różnych amplitudach."""
        # W czasie epizodu prawa strona dostaje dodatkowe osłabienie, czyli większą asymetrię
        cykl_t = t % OKRES_EPIZODU_S
        dodatek = 0.0
        if cykl_t >= POCZATEK_EPIZODU_S:
            dlugosc = OKRES_EPIZODU_S - POCZATEK_EPIZODU_S  # epizod trwa 3 s
            dodatek = 30.0 * math.sin(math.pi * (cykl_t - POCZATEK_EPIZODU_S) / dlugosc)

        katy = {}
        analizowane = self._analizowane_stawy()
        for i, staw in enumerate(DEFAULT_JOINTS):
            faza = 2 * math.pi * 0.25 * t + i * 0.7  # każdy staw jest trochę przesunięty w czasie
            # Staw spoza wybranych nie jest liczony (None). Co 300 klatek kolano na 15 klatek znika,
            # żeby sprawdzić obsługę braku danych.
            if staw not in analizowane or ((numer % 300) in range(60, 75) and staw == "knee"):
                katy[staw] = None
                continue
            katy[staw] = {
                "L": KAT_SRODKOWY + AMPLITUDA_L * math.sin(faza),
                "R": KAT_SRODKOWY + AMPLITUDA_R * math.sin(faza) - dodatek,
            }
        return katy

    def _si_atrapy(self, katy):
        """SI ze wzoru |L−R| / (0.5·(L+R)) · 100. Tylko dla atrapy potoku."""
        si = {}
        dostepne = []
        for staw in DEFAULT_JOINTS:
            dane = katy.get(staw)
            if dane is None:  # brak stawu, więc brak SI
                si[staw] = None
                continue
            l, r = dane["L"], dane["R"]
            wartosc = abs(l - r) / (0.5 * (l + r)) * 100.0
            si[staw] = wartosc
            dostepne.append(wartosc)
        # total to średnia z dostępnych stawów (albo None, gdy nie ma żadnego)
        si["total"] = sum(dostepne) / len(dostepne) if dostepne else None
        return si

    def _landmarks_atrapy(self, t, numer):
        """33 punkty szkieletu krążące wokół środka kadru. None oznacza 'brak osoby'."""
        if (numer % 450) in range(400, 430):
            return None  # przez chwilę nie ma osoby w kadrze
        punkty = []
        for k in range(LICZBA_LANDMARKS):
            kat = 2 * math.pi * k / LICZBA_LANDMARKS + t
            x = 0.5 + 0.1 * math.cos(kat)  # współrzędne 0–1, tak jak u MediaPipe
            y = 0.5 + 0.3 * math.sin(kat)
            punkty.append((x, y, 0.95))  # 0.95 to pewność, że punkt jest widoczny
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
            # Epizod właśnie się skończył, więc wysyłamy zdarzenie w formacie z gui_data_format
            si_max = self._epizod["si_max"]
            zdarzenie = {
                "start": self._epizod["start"],
                "end": round(t, 3),
                "joint": "elbow",  # atrapa zawsze pokazuje łokieć
                "level": "alarm" if si_max >= PROG_ALARMU_ATRAPY else "warning",
                "si_max": round(si_max, 1),
            }
            self._epizod = None
            self.event_detected.emit(zdarzenie)
