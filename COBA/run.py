# import time
# from movement import Movement


# def main():
#     movement = Movement()
#     time.sleep(2)

#     # Setup awal: bypass check → arm → ALT_HOLD → kalibrasi Bar30 → yaw lock → dive 60cm
#     movement.start(target_depth_cm=60, tolerance_cm=5, dive_timeout=30)

#     # Maju: surge manual, depth ditahan ALT_HOLD, yaw dikunci ke depan
#     print("Maju...")
#     movement.bai(duration=100, surge=200, sway=0)

#     # Scan kiri-kanan ±30°, depth tetap ditahan ALT_HOLD
#     print("Scanning...")
#     movement.scan_yaw(angle=30)

#     print("SELESAI")
#     movement.disarm()


# if __name__ == "__main__":
#     main()

import time
from movement import Movement


def main():
    # =========================================================
    # KONFIGURASI — ubah nilai di sini sesuai kebutuhan
    # =========================================================
    TARGET_DEPTH_CM = 10    # kedalaman target (cm)
    SURGE_SPEED     = 50   # kecepatan maju (-1000 s/d 1000)
    DURATION        = 100   # durasi maju (detik)
    # =========================================================

    movement = Movement()
    time.sleep(2)

    # Setup awal: bypass check → arm → ALT_HOLD → kalibrasi Bar30 → yaw lock
    # TIDAK nunggu depth tercapai — langsung set target saja
    movement.start(target_depth_cm=TARGET_DEPTH_CM)

    # Maju langsung — depth dikejar bersamaan dengan surge/sway
    # heave dikontrol otomatis tiap loop oleh depth_hold_control()
    print("Maju")
    movement.bai(
        duration=DURATION,
        surge=SURGE_SPEED,
        sway=0
    )

    # Scan kiri-kanan ±30°, depth tetap di-hold selama rotate
    print("Scanning...")
    movement.scan_yaw(angle=30)

    print("SELESAI")
    movement.disarm()


if __name__ == "__main__":
    main()