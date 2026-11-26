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
# Progi atrapy wykrywania zdarzeń. Używamy ich, dopóki GUI nie przyśle własnych ustawień.
PROG_OSTRZEZENIA_ATRAPY = 10.0
PROG_ALARMU_ATRAPY = 20.0
MIN_CZAS_ZDARZENIA_S = 0.3  # krótsze „zdarzenia” to szum, więc ich nie zgłaszamy
# True: po wczytaniu pliku (i po zmianie ustawień) cały film liczymy od razu i wykres rysuje się w całości.
# False: wykres rośnie na żywo podczas odtwarzania, jak wcześniej. Przełącznik do szybkiego powrotu.
CALY_FILM_OD_RAZU = True


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
    wyniki_calego_filmu = Signal(list)  # wyniki wszystkich klatek naraz (tryb CALY_FILM_OD_RAZU)
    finished = Signal()  # koniec pliku wideo
    error = Signal(str)  # komunikat błędu

    def __init__(self):
        super().__init__()
        self._cap = None  # otwarty plik wideo (cv2.VideoCapture); None oznacza tryb bez pliku
        self._sciezka = None  # ścieżka do pliku, potrzebna, żeby Reset mógł otworzyć go od nowa
        self._fps = FPS_DOMYSLNY
        self._klatka = 0  # numer bieżącej klatki
        self._ustawienia = {}  # ustawienia przekazane przez set_settings
        # Wykrywanie zdarzeń: zdarzenia w toku dla każdego stawu, czyli {staw: {"start", "si_max"}}
        self._otwarte = {}
        # Stawy, których zdarzenie zaczęło się przed przewinięciem. Nie znamy jego początku, więc je pomijamy
        self._pominiete = set()
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
        self._zacznij_sledzenie(0)
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
        if CALY_FILM_OD_RAZU:
            self._policz_caly_film()

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
            self._zacznij_sledzenie(0)

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
            self._zacznij_sledzenie(numer_faktyczny)  # po skoku zaczynamy wykrywanie od nowa
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
        # Progi wpływają na wykrywanie zdarzeń. Typ ćwiczenia na razie tylko zapamiętujemy.
        self._ustawienia = dict(ustawienia)
        if CALY_FILM_OD_RAZU and self._film_otwarty():
            # Nowe progi albo stawy zmieniają cały przebieg, więc liczymy film od nowa
            self._policz_caly_film()
        else:
            # Nowe progi albo stawy = wykrywanie od czystego stanu, od bieżącej klatki
            self._zacznij_sledzenie(max(self._klatka - 1, 0))

    def _film_otwarty(self):
        """True, gdy plik jest otwarty i znamy jego liczbę klatek (potrzebną do liczenia całości)."""
        return self._cap is not None and self._liczba_klatek is not None

    def _policz_caly_film(self):
        """Liczy wyniki wszystkich klatek naraz i wysyła je do GUI jednym sygnałem.

        Atrapa zależy tylko od numeru klatki i fps, więc nie trzeba czytać wideo ani przewijać.
        Pozycja odtwarzania się nie zmienia. W prawdziwym potoku ten etap będzie działał w tle.
        """
        liczba = self._liczba_klatek
        wyniki = []
        self._zacznij_sledzenie(0)  # liczymy od początku, więc zdarzenia mają znany początek
        try:
            for numer in range(liczba):
                wynik = self._zbuduj_wynik(numer)
                self._sledz_zdarzenia(wynik["timestamp"], wynik["si"])  # zdarzenia lecą do GUI od razu
                # Wykres potrzebuje tylko numeru, czasu i SI. Kąty i landmarks pomijamy, żeby nie trzymać ich w pamięci.
                wyniki.append({"frame_idx": numer, "timestamp": wynik["timestamp"], "si": wynik["si"]})
            self._zamknij_wszystkie(liczba / self._fps)  # zdarzenia w toku kończą się na końcu filmu
        except Exception as blad:
            self.error.emit(f"Atrapa potoku: {blad}")
            return
        finally:
            # Wracamy do stanu wykrywania dla bieżącej pozycji odtwarzania
            self._zacznij_sledzenie(max(self._klatka - 1, 0))
        self.wyniki_calego_filmu.emit(wyniki)

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
                    # Film się skończył, więc zdarzenia w toku kończą się tutaj (przed „finished”)
                    self._zamknij_wszystkie(self._klatka / self._fps)
                    self.finished.emit()
                    return

            wynik = self._zbuduj_wynik(self._klatka)
            self._sledz_zdarzenia(wynik["timestamp"], wynik["si"])
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

    def _progi(self):
        """Progi (uwaga, alarm) z ustawień GUI, a gdy ich brak – wartości domyślne atrapy."""
        progi = self._ustawienia.get("thresholds") or {}
        return progi.get("warning", PROG_OSTRZEZENIA_ATRAPY), progi.get("alarm", PROG_ALARMU_ATRAPY)

    def _zacznij_sledzenie(self, numer):
        """Czyści stan wykrywania i zapamiętuje, które stawy są już w zdarzeniu na tej klatce.

        Jeśli przewijamy do środka zdarzenia, nie znamy jego prawdziwego początku. Gdybyśmy
        zaczęli liczyć od tego miejsca, zgłosilibyśmy zdarzenie z błędnym czasem startu. Dlatego
        takie zdarzenie pomijamy. Pojawi się, gdy odtworzymy film od jego początku.
        """
        self._otwarte = {}
        self._pominiete = set()
        if numer <= 0:
            return  # od początku filmu każde zdarzenie ma znany początek
        wynik = self._zbuduj_wynik(numer)
        warning, _ = self._progi()
        for staw in self._analizowane_stawy():
            si = wynik["si"].get(staw)
            if si is not None and si >= warning:
                self._pominiete.add(staw)

    def _sledz_zdarzenia(self, t, si):
        """Wykrywa zdarzenia w jednej klatce odtwarzania. t – czas klatki, si – słownik SI stawów.

        Zdarzenie zaczyna się, gdy SI stawu wejdzie na poziom uwagi (≥ próg uwagi), a kończy,
        gdy spadnie poniżej. Działa osobno dla każdego stawu.
        """
        warning, _ = self._progi()
        for staw in self._analizowane_stawy():
            wartosc = si.get(staw)
            if wartosc is None:
                continue  # brak stawu w tej klatce, więc stan zostaje bez zmian
            if staw in self._pominiete:
                if wartosc < warning:
                    self._pominiete.discard(staw)  # to zdarzenie się skończyło, od następnego liczymy
                continue
            if staw in self._otwarte:
                zdarzenie = self._otwarte[staw]
                zdarzenie["si_max"] = max(zdarzenie["si_max"], wartosc)
                if wartosc < warning:
                    del self._otwarte[staw]
                    self._zamknij(staw, zdarzenie, t)
            elif wartosc >= warning:
                self._otwarte[staw] = {"start": t, "si_max": wartosc}

    def _zamknij(self, staw, zdarzenie, koniec):
        """Wysyła zdarzenie, jeśli trwało dość długo. Poziom zależy od najwyższego SI w zdarzeniu."""
        if koniec - zdarzenie["start"] < MIN_CZAS_ZDARZENIA_S:
            return  # za krótkie, pomijamy
        _, alarm = self._progi()
        self.event_detected.emit(
            {
                "start": round(zdarzenie["start"], 3),
                "end": round(koniec, 3),
                "joint": staw,
                "level": "alarm" if zdarzenie["si_max"] >= alarm else "warning",
                "si_max": round(zdarzenie["si_max"], 1),
            }
        )

    def _zamknij_wszystkie(self, koniec):
        """Kończy zdarzenia, które były w toku, gdy film się skończył."""
        for staw, zdarzenie in list(self._otwarte.items()):
            self._zamknij(staw, zdarzenie, koniec)
        self._otwarte = {}
