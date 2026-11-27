import os

os.environ["GLOG_minloglevel"] = "2"
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "2"

import csv
import time
import urllib.request
from pathlib import Path
import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

FOLDER_SKRYPTU = Path(__file__).parent
MODEL_PATH = FOLDER_SKRYPTU / "pose_landmarker_lite.task"
MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task"
)

STAWY = {
    "left_shoulder": 11,
    "right_shoulder": 12,
    "left_elbow": 13,
    "right_elbow": 14,
    "left_wrist": 15,
    "right_wrist": 16,
    "left_hip": 23,
    "right_hip": 24,
    "left_knee": 25,
    "right_knee": 26,
    "left_ankle": 27,
    "right_ankle": 28,
}


def pobierz_model():
    if not MODEL_PATH.exists():
        print("Pobieranie lekkiego modelu MediaPipe Pose...")
        urllib.request.urlretrieve(MODEL_URL, str(MODEL_PATH))


def wideo_do_csv(zrodlo: str | int, nazwa_csv: str = "dane_klatki.csv"):
    pobierz_model()

    if isinstance(zrodlo, str):
        sciezka_wideo = Path(zrodlo)
        if not sciezka_wideo.is_absolute():
            sciezka_wideo = FOLDER_SKRYPTU / sciezka_wideo
        if not sciezka_wideo.exists():
            raise FileNotFoundError(f"Nie znaleziono pliku: {sciezka_wideo}")
        cap = cv2.VideoCapture(str(sciezka_wideo))
        tryb_kamerki = False
    else:
        cap = cv2.VideoCapture(zrodlo, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap = cv2.VideoCapture(zrodlo)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        tryb_kamerki = True

    if not cap.isOpened():
        raise RuntimeError(f"Nie można uruchomić źródła wideo: {zrodlo}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    sciezka_csv = FOLDER_SKRYPTU / nazwa_csv

    # Nagłówki wyłącznie dla x oraz y
    naglowki = ["frame", "time_s"]
    for nazwa in STAWY:
        naglowki.extend([f"{nazwa}_x", f"{nazwa}_y"])

    opcje = vision.PoseLandmarkerOptions(
        base_options=python.BaseOptions(model_asset_path=str(MODEL_PATH)),
        running_mode=vision.RunningMode.VIDEO,
        num_poses=1,
        min_pose_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    )

    nazwa_okna = "Analiza ruchu - wcisnij Q aby zapisac i wyjsc"
    if tryb_kamerki:
        cv2.namedWindow(nazwa_okna, cv2.WINDOW_NORMAL)
        cv2.setWindowProperty(nazwa_okna, cv2.WND_PROP_TOPMOST, 1)

    print("Start przetwarzania klatek...")

    with (
        open(sciezka_csv, mode="w", newline="", encoding="utf-8") as plik_csv,
        vision.PoseLandmarker.create_from_options(opcje) as landmarker,
    ):
        writer = csv.writer(plik_csv)
        writer.writerow(naglowki)

        nr_klatki = 0
        start_time = time.perf_counter()
        ostatni_czas_ms = -1

        while cap.isOpened():
            ret, klatka = cap.read()
            if not ret:
                break

            if tryb_kamerki:
                czas_ms = int((time.perf_counter() - start_time) * 1000)
                if czas_ms <= ostatni_czas_ms:
                    czas_ms = ostatni_czas_ms + 1
                ostatni_czas_ms = czas_ms
                czas_s = round(czas_ms / 1000.0, 3)
            else:
                czas_ms = int((nr_klatki / fps) * 1000)
                czas_s = round(nr_klatki / fps, 3)

            klatka_rgb = cv2.cvtColor(klatka, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=klatka_rgb)
            wynik = landmarker.detect_for_video(mp_image, czas_ms)

            wiersz = [nr_klatki, czas_s]
            h, w, _ = klatka.shape

            if wynik.pose_landmarks:
                punkty = wynik.pose_landmarks[0]
                for idx in STAWY.values():
                    p = punkty[idx]
                    wiersz.extend([round(p.x, 4), round(p.y, 4)])
                    if tryb_kamerki:
                        cv2.circle(klatka, (int(p.x * w), int(p.y * h)), 5, (0, 255, 0), -1)
            else:
                wiersz.extend([""] * (len(STAWY) * 2))

            writer.writerow(wiersz)
            nr_klatki += 1

            if nr_klatki % 30 == 0:
                plik_csv.flush()
                print(f"Przetworzono klatek: {nr_klatki}")

            if tryb_kamerki:
                cv2.putText(
                    klatka,
                    f"Klatka: {nr_klatki} | Q = zakoncz",
                    (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (0, 255, 0),
                    2,
                )
                cv2.imshow(nazwa_okna, klatka)

                if cv2.waitKey(1) & 0xFF in (ord("q"), ord("Q")):
                    break

    cap.release()
    cv2.destroyAllWindows()
    print(f"Zakończono! Zapisano {nr_klatki} klatek do: {sciezka_csv}")


if __name__ == "__main__":
    wideo_do_csv(0, "dane_klatki.csv")