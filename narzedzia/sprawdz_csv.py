
#Uruchomienie: python sprawdz_csv.py moj_film.mp4 moj_film.csv

import csv
import sys

import cv2

# Nazwy 12 punktów – takie same jak w słowniku STAWY w InzRehb.py
PUNKTY = [
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_hip", "right_hip",
    "left_knee", "right_knee", "left_ankle", "right_ankle",
]

# Połączenia szkieletu zdefiniowane po nazwach (nie po numerach MediaPipe)
POLACZENIA = [
    ("left_shoulder", "right_shoulder"), ("left_hip", "right_hip"),
    ("left_shoulder", "left_hip"), ("right_shoulder", "right_hip"),
    ("left_shoulder", "left_elbow"), ("left_elbow", "left_wrist"),
    ("right_shoulder", "right_elbow"), ("right_elbow", "right_wrist"),
    ("left_hip", "left_knee"), ("left_knee", "left_ankle"),
    ("right_hip", "right_knee"), ("right_knee", "right_ankle"),
]


def wczytaj_csv(sciezka):
    """Zwraca słownik: numer klatki -> {nazwa_punktu: (x, y)} w skali 0–1."""
    dane = {}
    with open(sciezka, newline="", encoding="utf-8") as plik:
        for wiersz in csv.DictReader(plik):
            punkty = {}
            for nazwa in PUNKTY:
                x = wiersz.get(f"{nazwa}_x", "")
                y = wiersz.get(f"{nazwa}_y", "")
                # Pusta komórka = MediaPipe nie znalazł osoby w tej klatce
                if x != "" and y != "":
                    punkty[nazwa] = (float(x), float(y))
            dane[int(wiersz["frame"])] = punkty
    return dane


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return

    sciezka_wideo, sciezka_csv = sys.argv[1], sys.argv[2]
    dane = wczytaj_csv(sciezka_csv)

    cap = cv2.VideoCapture(sciezka_wideo)
    if not cap.isOpened():
        print("Nie można otworzyć filmu:", sciezka_wideo)
        return

    liczba_klatek = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    # CAP_PROP_FRAME_COUNT to tylko szacunek z nagłówka pliku. Przy filmach
    # z telefonu (zmienny fps) bywa zawyżony – prawdziwą liczbę klatek
    # poznajemy dopiero po odczytaniu całego filmu (wypisujemy ją na końcu).
    print(f"Film (wg nagłówka): ~{liczba_klatek} klatek, {fps:.2f} fps | "
          f"CSV: {len(dane)} wierszy")

    nazwa_okna = "Sprawdzenie CSV (spacja = pauza, q = wyjscie)"
    cv2.namedWindow(nazwa_okna, cv2.WINDOW_NORMAL)  # okno można zmniejszyć myszką

    nr_klatki = 0
    pauza = False
    koniec_filmu = False
    while True:
        if not pauza:
            ok, klatka = cap.read()
            if not ok:
                koniec_filmu = True
                break

            # Skalowanie 0–1 -> piksele: mnożymy przez rozmiar TEJ klatki
            wys, szer = klatka.shape[:2]
            punkty_px = {
                nazwa: (int(x * szer), int(y * wys))
                for nazwa, (x, y) in dane.get(nr_klatki, {}).items()
            }

            # Kreski: tylko gdy oba końce istnieją
            for a, b in POLACZENIA:
                if a in punkty_px and b in punkty_px:
                    cv2.line(klatka, punkty_px[a], punkty_px[b], (255, 255, 255), 2)

            # Kółka: kolory w kolejności BGR (OpenCV), nie RGB
            for nazwa, punkt in punkty_px.items():
                kolor = (0, 255, 0) if nazwa.startswith("left") else (0, 0, 255)
                cv2.circle(klatka, punkt, 6, kolor, -1)

            opis = f"klatka {nr_klatki}"
            if not punkty_px:
                opis += "  (brak punktow)"
            cv2.putText(klatka, opis, (10, 30), cv2.FONT_HERSHEY_SIMPLEX,
                        0.8, (0, 255, 255), 2)
            cv2.imshow(nazwa_okna, klatka)
            nr_klatki += 1

        klawisz = cv2.waitKey(int(1000 / fps)) & 0xFF
        if klawisz == ord("q"):
            break
        if klawisz == ord(" "):
            pauza = not pauza

    cap.release()
    cv2.destroyAllWindows()

    # Porównanie z FAKTYCZNIE odczytanymi klatkami (tylko gdy film doszedł do końca)
    if koniec_filmu:
        print(f"Faktycznie odczytano klatek: {nr_klatki} | wierszy CSV: {len(dane)}")
        if nr_klatki == len(dane):
            print("OK: para pasuje klatka w klatkę.")
        else:
            print("UWAGA: liczba klatek i wierszy się różni – "
                  "sprawdź, czy CSV powstał z tego filmu.")


if __name__ == "__main__":
    main()