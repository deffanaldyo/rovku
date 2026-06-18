# import time
# import math
# import signal
# import sys
# from pymavlink import mavutil


# class Movement:
#     def __init__(self, port_list=["/dev/ttyACM0", "/dev/ttyACM1"], baud=115200):
#         print("Connecting to Pixhawk...")

#         self.master = None

#         for port in port_list:
#             try:
#                 print(f"Coba {port}")
#                 master = mavutil.mavlink_connection(port, baud=baud)
#                 master.wait_heartbeat(timeout=3)

#                 print(f"Connected di {port}")
#                 self.master = master
#                 break

#             except:
#                 print(f"Gagal di {port}")

#         if self.master is None:
#             raise Exception("Tidak bisa connect ke Pixhawk!")

#         # sensor
#         self.roll = 0
#         self.pitch = 0
#         self.yaw = 0
#         self.depth = 0  # dalam meter (dari press_abs * 0.01)

#         # yaw lock
#         self.yaw_target = None

#         # watchdog
#         self.last_command_time = time.time()

#         # CTRL+C handler
#         signal.signal(signal.SIGINT, self._signal_handler)

#         # Minta data stream ATTITUDE & SCALED_PRESSURE2
#         self.setup_data_streams()

#     # =========================
#     # 🔥 SAFETY
#     # =========================
#     def _signal_handler(self, sig, frame):
#         print("\nCTRL+C terdeteksi!")
#         self.cleanup()

#     def cleanup(self):
#         print("STOP semua motor...")
#         self.stop_all()
#         time.sleep(1)
#         self.disarm()
#         sys.exit(0)

#     # =========================
#     # 🔥 DATA STREAM SETUP
#     # =========================
#     def request_message_interval(self, message_id, frequency_hz):
#         self.master.mav.command_long_send(
#             self.master.target_system,
#             self.master.target_component,
#             mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL,
#             0,
#             message_id,
#             int(1e6 / frequency_hz),
#             0, 0, 0, 0, 0
#         )

#     def setup_data_streams(self):
#         print("Request data stream ATTITUDE & SCALED_PRESSURE2...")
#         self.request_message_interval(mavutil.mavlink.MAVLINK_MSG_ID_ATTITUDE, 10)
#         self.request_message_interval(mavutil.mavlink.MAVLINK_MSG_ID_SCALED_PRESSURE2, 5)

#     # =========================
#     # 🔥 ARM / DISARM
#     # =========================
#     def check_statustext(self, duration=2):
#         start = time.time()
#         while time.time() - start < duration:
#             msg = self.master.recv_match(type='STATUSTEXT', blocking=False)
#             if msg:
#                 print(f"STATUSTEXT: {msg.text}")
#             time.sleep(0.05)

#     def arm(self, timeout=5):
#         print("Arming...")
#         self.master.arducopter_arm()

#         start = time.time()
#         while time.time() - start < timeout:
#             self.update_sensor()
#             if self.master.motors_armed():
#                 print("ARMED!")
#                 return True
#             time.sleep(0.2)

#         print("GAGAL ARM! Cek alasan pre-arm check di bawah:")
#         self.check_statustext()
#         return False

#     def disarm(self):
#         print("Disarming...")
#         self.master.arducopter_disarm()

#     # =========================
#     # 🔥 SET MODE
#     # =========================
#     def set_mode(self, mode_name="ALT_HOLD", timeout=5):
#         try:
#             mode_id = self.master.mode_mapping()[mode_name]
#         except (KeyError, TypeError):
#             # Fallback mode ID untuk ArduSub
#             fallback = {"MANUAL": 19, "ALT_HOLD": 2, "STABILIZE": 0}
#             mode_id = fallback.get(mode_name, 19)
#             print(f"Mode '{mode_name}' tidak ada di mode_mapping, pakai fallback id {mode_id}")

#         self.master.set_mode(mode_id)

#         start = time.time()
#         while time.time() - start < timeout:
#             ack = self.master.recv_match(type='HEARTBEAT', blocking=True, timeout=1)
#             if ack and ack.custom_mode == mode_id:
#                 print(f"Mode berhasil diset ke {mode_name}")
#                 return True

#         print(f"WARNING: belum dapat konfirmasi mode {mode_name}, lanjut saja")
#         return False

#     # =========================
#     # 🔥 SENSOR UPDATE
#     # =========================
#     def update_sensor(self):
#         msg = self.master.recv_match(blocking=False)

#         if not msg:
#             return

#         if msg.get_type() == 'ATTITUDE':
#             self.roll = math.degrees(msg.roll)
#             self.pitch = math.degrees(msg.pitch)
#             self.yaw = math.degrees(msg.yaw)

#         if msg.get_type() == 'SCALED_PRESSURE2':
#             # press_abs dalam hPa → kedalaman meter
#             # 1 hPa ≈ 0.01 m air (freshwater), pakai 1010 hPa sebagai tekanan permukaan
#             pressure_surface = 1010.0  # hPa, tekanan atmosfer permukaan
#             self.depth = (msg.press_abs - pressure_surface) * 0.01  # meter, positif = dalam air

#     # =========================
#     # 🔥 MONITOR
#     # =========================
#     def print_status(self, surge, sway, heave, yaw_cmd):
#         depth_cm = self.depth * 100
#         print(
#             f"[MONITOR] "
#             f"x:{surge} | y:{sway} | z:{heave} | "
#             f"Yaw_cmd:{yaw_cmd:.2f} | "
#             f"Yaw:{self.yaw:.2f} | "
#             f"Roll:{self.roll:.2f} | Pitch:{self.pitch:.2f} | "
#             f"Depth:{depth_cm:.1f} cm"
#         )

#     # =========================
#     # 🔥 CONTROL DASAR
#     # =========================
#     def send_control(self, surge, sway, heave, yaw):
#         self.master.mav.manual_control_send(
#             self.master.target_system,
#             int(surge),
#             int(sway),
#             int(heave),
#             int(yaw),
#             0
#         )
#         self.last_command_time = time.time()

#     def stop_all(self):
#         self.master.mav.manual_control_send(
#             self.master.target_system,
#             0, 0, 500, 0, 0
#         )
#         print("MOTOR STOP")

#     def watchdog_check(self):
#         if time.time() - self.last_command_time > 1.0:
#             print("Watchdog STOP")
#             self.stop_all()

#     # =========================
#     # 🔥 YAW LOCK
#     # =========================
#     def set_yaw_lock(self, timeout=5):
#         print("Lock yaw")
#         start = time.time()

#         while time.time() - start < timeout:
#             self.update_sensor()
#             if self.yaw != 0:
#                 self.yaw_target = self.yaw
#                 print(f"Yaw dikunci: {self.yaw_target:.2f}")
#                 return True

#         print("WARNING: timeout nunggu data ATTITUDE, yaw lock dilewati (yaw_target=0)")
#         self.yaw_target = 0
#         return False

#     def yaw_control(self):
#         if self.yaw_target is None:
#             return 0

#         error = self.yaw_target - self.yaw

#         if error > 180:
#             error -= 360
#         elif error < -180:
#             error += 360

#         Kp = 5.0
#         yaw_cmd = Kp * error

#         return max(-300, min(300, yaw_cmd))

#     # =========================
#     # 🔥 START (setup awal lengkap)
#     # =========================
#     def start(self, target_depth_cm=60, tolerance_cm=5, dive_timeout=30):
#         """
#         Setup awal lengkap:
#         1. Set mode ALT_HOLD
#         2. Arm
#         3. Lock yaw
#         4. Dive ke target depth
#         """
#         # Arm dulu di MANUAL (lebih mudah lolos pre-arm check)
#         self.set_mode("MANUAL")

#         # Cek dulu ada pre-arm error tidak
#         print("Cek pre-arm check...")
#         self.check_statustext(duration=2)

#         if not self.arm():
#             print("Berhenti karena gagal arm.")
#             sys.exit(1)

#         # Setelah arm, baru ganti ke ALT_HOLD
#         self.set_mode("ALT_HOLD")

#         self.set_yaw_lock()

#         if not self.dive_to_depth(target_depth_cm=target_depth_cm, tolerance_cm=tolerance_cm, timeout=dive_timeout):
#             print("⚠️  Gagal mencapai depth target, tetap lanjut dengan depth saat ini")

#     # =========================
#     # 🔥 DIVE TO DEPTH (ALT_HOLD)
#     # =========================
#     def dive_to_depth(self, target_depth_cm, tolerance_cm=5, timeout=30):
#         """
#         Turun ke kedalaman target menggunakan heave manual.
#         Di ALT_HOLD: heave=500 = hover, >500 = turun, <500 = naik.
#         Bar30 memberikan feedback kedalaman aktual.
#         """
#         print(f"Menuju depth {target_depth_cm} cm...")
#         start = time.time()

#         while time.time() - start < timeout:
#             self.update_sensor()
#             current_cm = self.depth * 100  # konversi ke cm

#             error_cm = target_depth_cm - current_cm
#             print(f"  Depth: {current_cm:.1f} cm | Target: {target_depth_cm} cm | Error: {error_cm:.1f} cm")

#             if abs(error_cm) <= tolerance_cm:
#                 print(f"  ✅ Depth target tercapai ({current_cm:.1f} cm)")
#                 self.send_control(0, 0, 500, 0)  # hover
#                 return True

#             # Proportional control heave
#             # error positif = perlu turun → heave > 500
#             # error negatif = perlu naik  → heave < 500
#             Kp = 2.0
#             heave_cmd = 500 + (Kp * error_cm)
#             heave_cmd = max(300, min(700, int(heave_cmd)))

#             yaw_cmd = self.yaw_control()
#             self.send_control(0, 0, heave_cmd, yaw_cmd)
#             time.sleep(0.1)

#         print(f"  ⚠️  TIMEOUT dive_to_depth! Depth terakhir: {self.depth * 100:.1f} cm")
#         self.send_control(0, 0, 500, 0)  # hover saat timeout
#         return False

#     # =========================
#     # 🚀 GERAK MAJU di ALT_HOLD
#     # =========================
#     def bai(self, duration, surge, sway=0, yaw_override=None):
#         """
#         Gerak maju/sway dengan depth otomatis dijaga ALT_HOLD.
#         Heave = 500 (netral) → ArduSub yang kontrol depth via Bar30.
#         Tidak perlu parameter depth karena depth sudah dikunci saat dive_to_depth().
#         """
#         start = time.time()

#         while time.time() - start < duration:
#             self.update_sensor()

#             if yaw_override is None:
#                 yaw_cmd = self.yaw_control()
#             else:
#                 yaw_cmd = yaw_override

#             # Heave = 500 → ALT_HOLD menahan depth saat ini
#             self.send_control(
#                 surge=surge,
#                 sway=sway,
#                 heave=500,
#                 yaw=yaw_cmd
#             )

#             self.print_status(surge, sway, 500, yaw_cmd)
#             self.watchdog_check()
#             time.sleep(0.1)

#         self.stop_all()
#         print("SELESAI MAJU")

#     # =========================
#     # 🎯 ROTATE BERBASIS DERAJAT
#     # =========================
#     def rotate_to_yaw(self, target_yaw, duration=5):
#         print(f"Rotate ke {target_yaw:.2f}°")

#         start = time.time()

#         while time.time() - start < duration:
#             self.update_sensor()

#             error = target_yaw - self.yaw

#             if error > 180:
#                 error -= 360
#             elif error < -180:
#                 error += 360

#             Kp = 4.0
#             yaw_cmd = Kp * error
#             yaw_cmd = max(-300, min(300, yaw_cmd))

#             # Heave = 500 → ALT_HOLD tetap tahan depth saat scan
#             self.send_control(0, 0, 500, yaw_cmd)
#             self.print_status(0, 0, 500, yaw_cmd)

#             if abs(error) < 2:
#                 print("Target tercapai")
#                 break

#             time.sleep(0.1)

#         self.stop_all()

#     # =========================
#     # 🔍 SCAN ±ANGLE
#     # =========================
#     def scan_yaw(self, angle=30, hold_time=2):
#         print("🔍 START SCAN")

#         self.update_sensor()
#         yaw_center = self.yaw

#         yaw_left = yaw_center - angle
#         yaw_right = yaw_center + angle

#         if yaw_left < -180:
#             yaw_left += 360
#         if yaw_right > 180:
#             yaw_right -= 360

#         print(f"Center: {yaw_center:.2f}")
#         print(f"Kiri: {yaw_left:.2f}")
#         print(f"Kanan: {yaw_right:.2f}")

#         self.rotate_to_yaw(yaw_left)
#         time.sleep(hold_time)

#         self.rotate_to_yaw(yaw_right)
#         time.sleep(hold_time)

#         self.rotate_to_yaw(yaw_center)
#         time.sleep(hold_time)

#         print("SCAN SELESAI")

import time
import math
import signal
import sys
from pymavlink import mavutil


class Movement:

    # =========================
    # INIT & CONNECT
    # =========================
    def __init__(self, port_list=["/dev/ttyACM0", "/dev/ttyACM1"], baud=115200):
        print("Connecting to Pixhawk...")
        self.master = None

        for port in port_list:
            try:
                print(f"  Coba {port}...")
                master = mavutil.mavlink_connection(port, baud=baud)
                master.wait_heartbeat(timeout=3)
                print(f"  Connected di {port}")
                self.master = master
                break
            except:
                print(f"  Gagal di {port}")

        if self.master is None:
            raise Exception("Tidak bisa connect ke Pixhawk!")

        # Data sensor
        self.roll              = 0.0
        self.pitch             = 0.0
        self.yaw               = 0.0
        self.depth             = 0.0      # meter, relatif dari permukaan
        self.press_raw         = 0.0      # hPa raw dari Bar30
        self._surface_pressure = 1013.25  # hPa default, dikalibrasi ulang di start()

        # Depth hold
        self.depth_target_cm   = None     # target kedalaman aktif (cm)

        # Yaw lock
        self.yaw_target        = None

        # Watchdog
        self.last_command_time = time.time()

        # CTRL+C handler
        signal.signal(signal.SIGINT, self._signal_handler)

        # Request data stream
        self._setup_data_streams()

    # =========================
    # SAFETY
    # =========================
    def _signal_handler(self, sig, frame):
        print("\nCTRL+C terdeteksi! Emergency stop...")
        self.cleanup()

    def cleanup(self):
        self.stop_all()
        time.sleep(0.5)
        self.disarm()
        sys.exit(0)

    # =========================
    # DATA STREAM
    # =========================
    def _request_message_interval(self, message_id, frequency_hz):
        self.master.mav.command_long_send(
            self.master.target_system,
            self.master.target_component,
            mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL,
            0,
            message_id,
            int(1e6 / frequency_hz),
            0, 0, 0, 0, 0
        )

    def _setup_data_streams(self):
        self._request_message_interval(mavutil.mavlink.MAVLINK_MSG_ID_ATTITUDE, 10)
        self._request_message_interval(mavutil.mavlink.MAVLINK_MSG_ID_SCALED_PRESSURE2, 10)

    # =========================
    # SENSOR
    # =========================
    def update_sensor(self):
        """Drain semua pesan yang masuk, update sensor terbaru."""
        while True:
            msg = self.master.recv_match(blocking=False)
            if msg is None:
                break

            t = msg.get_type()

            if t == 'ATTITUDE':
                self.roll  = math.degrees(msg.roll)
                self.pitch = math.degrees(msg.pitch)
                self.yaw   = math.degrees(msg.yaw)

            elif t == 'SCALED_PRESSURE2':
                self.press_raw = msg.press_abs  # hPa
                self.depth = (msg.press_abs - self._surface_pressure) * 0.01  # meter

    def print_status(self, surge, sway, heave, yaw_cmd):
        print(
            f"[STATUS] surge:{surge:4} sway:{sway:4} heave:{heave:4} yaw_cmd:{yaw_cmd:7.1f} | "
            f"Yaw:{self.yaw:7.2f} Roll:{self.roll:6.2f} Pitch:{self.pitch:6.2f} | "
            f"Depth:{self.depth * 100:6.1f}cm"
            + (f" (target:{self.depth_target_cm}cm)" if self.depth_target_cm is not None else "")
        )

    # =========================
    # ARM / DISARM
    # =========================
    def _bypass_arming_checks(self):
        self.master.mav.param_set_send(
            self.master.target_system,
            self.master.target_component,
            b'ARMING_CHECK',
            0,
            mavutil.mavlink.MAV_PARAM_TYPE_INT32
        )
        time.sleep(0.5)

    def arm(self, timeout=5):
        print("Arming...")
        self.master.arducopter_arm()

        start = time.time()
        while time.time() - start < timeout:
            self.update_sensor()
            if self.master.motors_armed():
                print("  ARMED!")
                return True
            time.sleep(0.2)

        print("  GAGAL ARM! Alasan:")
        deadline = time.time() + 2
        while time.time() < deadline:
            msg = self.master.recv_match(type='STATUSTEXT', blocking=False)
            if msg:
                print(f"  >> {msg.text}")
            time.sleep(0.05)
        return False

    def disarm(self):
        print("Disarming...")
        self.master.arducopter_disarm()

    # =========================
    # MODE
    # =========================
    def set_mode(self, mode_name, timeout=5):
        _fallback = {"MANUAL": 19, "ALT_HOLD": 2, "STABILIZE": 0, "DEPTH_HOLD": 2}

        try:
            mode_id = self.master.mode_mapping()[mode_name]
        except (KeyError, TypeError):
            mode_id = _fallback.get(mode_name, 19)
            print(f"  mode_mapping tidak ada '{mode_name}', pakai id={mode_id}")

        self.master.set_mode(mode_id)

        start = time.time()
        while time.time() - start < timeout:
            hb = self.master.recv_match(type='HEARTBEAT', blocking=True, timeout=1)
            if hb and hb.custom_mode == mode_id:
                print(f"  Mode: {mode_name}")
                return True

        print(f"  WARNING: konfirmasi mode {mode_name} timeout, lanjut saja")
        return False

    # =========================
    # KONTROL DASAR
    # =========================
    def send_control(self, surge, sway, heave, yaw):
        self.master.mav.manual_control_send(
            self.master.target_system,
            int(surge), int(sway), int(heave), int(yaw),
            0
        )
        self.last_command_time = time.time()

    def stop_all(self):
        self.master.mav.manual_control_send(
            self.master.target_system,
            0, 0, 500, 0, 0
        )
        print("  [STOP]")

    def watchdog_check(self):
        if time.time() - self.last_command_time > 1.0:
            print("  [WATCHDOG] timeout, stop!")
            self.stop_all()

    # =========================
    # YAW LOCK
    # =========================
    def set_yaw_lock(self, timeout=5):
        print("Set yaw lock...")
        start = time.time()
        while time.time() - start < timeout:
            self.update_sensor()
            if self.yaw != 0.0:
                self.yaw_target = self.yaw
                print(f"  Yaw dikunci: {self.yaw_target:.2f}°")
                return True
            time.sleep(0.05)

        print("  WARNING: yaw data belum masuk, lock ke 0°")
        self.yaw_target = 0.0
        return False

    def yaw_control(self):
        if self.yaw_target is None:
            return 0

        error = self.yaw_target - self.yaw
        if error > 180:
            error -= 360
        elif error < -180:
            error += 360

        return max(-300, min(300, 5.0 * error))

    # =========================
    # DEPTH HOLD CONTROL (AKTIF SAAT MAJU)
    # =========================
    def depth_hold_control(self):
        """
        Hitung heave untuk mempertahankan self.depth_target_cm.
        Return nilai heave (300–700). 500 = hover.
        Gunakan ini setiap loop agar ROV tidak naik/turun saat maju.
        """
        if self.depth_target_cm is None:
            return 500  # hover default jika belum di-set

        current_cm  = self.depth * 100
        error_cm    = self.depth_target_cm - current_cm

        # P-controller: gain=2.5, clamp 300–700
        heave = int(max(300, min(700, 500 + 2.5 * error_cm)))
        return heave

    # =========================
    # START (SETUP AWAL LENGKAP)
    # =========================
    def start(self, target_depth_cm=60):
        """
        Urutan setup awal:
          1. Bypass pre-arm check
          2. Arm di MANUAL
          3. Switch ke ALT_HOLD
          4. Kalibrasi tekanan permukaan Bar30
          5. Lock yaw
          6. Simpan depth target (TIDAK nunggu depth tercapai)
             → depth dikejar bersamaan saat bai() berjalan
        """
        print("[1/5] Bypass arming checks...")
        self._bypass_arming_checks()

        print("[2/5] Set MANUAL & arm...")
        self.set_mode("MANUAL")
        if not self.arm():
            print("Berhenti karena gagal arm.")
            sys.exit(1)

        print("[3/5] Switch ke ALT_HOLD...")
        self.set_mode("ALT_HOLD")

        print("[4/5] Kalibrasi Bar30 (ambil tekanan permukaan)...")
        self._surface_pressure = 1013.25
        for _ in range(30):
            self.update_sensor()
            time.sleep(0.1)
        if self.press_raw > 0:
            self._surface_pressure = self.press_raw
            print(f"  Tekanan permukaan: {self._surface_pressure:.2f} hPa")
            print(f"  Depth saat ini   : {self.depth * 100:.1f} cm")
        else:
            print("  WARNING: Bar30 belum terbaca! Cek koneksi I2C.")
            print(f"  Pakai default surface pressure: {self._surface_pressure} hPa")

        print("[5/5] Set yaw lock...")
        self.set_yaw_lock()

        # Simpan depth target saja — tidak nunggu tercapai
        # Depth akan dikejar oleh depth_hold_control() di dalam bai()
        self.depth_target_cm = target_depth_cm
        print(f"  Depth target di-set: {target_depth_cm} cm (dikejar saat bai() berjalan)")

        print("=== START selesai, siap bergerak ===\n")

    # =========================
    # DIVE TO DEPTH
    # =========================
    def dive_to_depth(self, target_depth_cm, tolerance_cm=5, timeout=30):
        """
        Turun/naik ke kedalaman target lalu hover.
        Setelah selesai, self.depth_target_cm di-update.
        """
        self.depth_target_cm = target_depth_cm
        start = time.time()

        while time.time() - start < timeout:
            self.update_sensor()
            current_cm = self.depth * 100
            error_cm   = target_depth_cm - current_cm

            print(
                f"  Depth: {current_cm:6.1f} cm | "
                f"Target: {target_depth_cm} cm | "
                f"Error: {error_cm:+.1f} cm"
            )

            if abs(error_cm) <= tolerance_cm:
                print(f"  Depth target tercapai ({current_cm:.1f} cm)")
                self.send_control(0, 0, 500, 0)
                return True

            heave_cmd = self.depth_hold_control()
            self.send_control(0, 0, heave_cmd, self.yaw_control())
            time.sleep(0.1)

        print(f"  TIMEOUT dive! Depth terakhir: {self.depth * 100:.1f} cm")
        self.send_control(0, 0, 500, 0)
        return False

    # =========================
    # MAJU (BAI) — DENGAN DEPTH HOLD AKTIF
    # =========================
    def bai(self, duration, surge, sway=0, target_depth_cm=None, yaw_override=None):
        """
        Gerak maju/sway dengan depth hold aktif secara manual.

        Parameters
        ----------
        duration        : float  — durasi gerak (detik)
        surge           : int    — kecepatan maju (-1000 s/d 1000; positif = maju)
        sway            : int    — kecepatan samping (default 0)
        target_depth_cm : float  — kedalaman target (cm). Jika None, pakai depth_target
                                   yang sudah di-set oleh start() atau dive_to_depth().
        yaw_override    : float  — override yaw langsung (jika None, pakai yaw lock PID)

        Catatan: heave TIDAK fix 500, melainkan dihitung tiap loop oleh
        depth_hold_control() agar ROV aktif mempertahankan kedalaman saat maju.
        """
        # Tentukan depth target
        if target_depth_cm is not None:
            self.depth_target_cm = target_depth_cm

        if self.depth_target_cm is None:
            print("  WARNING: depth_target_cm belum di-set! Pakai depth saat ini.")
            self.update_sensor()
            self.depth_target_cm = self.depth * 100

        # Refresh yaw lock ke arah ROV saat ini
        self.update_sensor()
        self.yaw_target = self.yaw

        print(
            f"Maju | Yaw lock: {self.yaw_target:.2f}° | "
            f"Duration: {duration}s | Surge: {surge} | "
            f"Depth target: {self.depth_target_cm:.1f} cm"
        )

        start = time.time()
        while time.time() - start < duration:
            self.update_sensor()

            heave_cmd = self.depth_hold_control()   # ← koreksi depth tiap loop
            yaw_cmd   = yaw_override if yaw_override is not None else self.yaw_control()

            self.send_control(surge=surge, sway=sway, heave=heave_cmd, yaw=yaw_cmd)
            self.print_status(surge, sway, heave_cmd, yaw_cmd)
            self.watchdog_check()
            time.sleep(0.1)

        self.stop_all()
        print("Selesai maju\n")

    # =========================
    # ROTATE KE YAW TERTENTU
    # =========================
    def rotate_to_yaw(self, target_yaw, duration=5):
        """Putar ROV ke sudut yaw tertentu (derajat), depth tetap di-hold."""
        print(f"Rotate ke {target_yaw:.2f}°")
        start = time.time()

        while time.time() - start < duration:
            self.update_sensor()

            error = target_yaw - self.yaw
            if error > 180:  error -= 360
            if error < -180: error += 360

            yaw_cmd   = max(-300, min(300, 4.0 * error))
            heave_cmd = self.depth_hold_control()   # ← jaga depth saat rotate

            self.send_control(0, 0, heave_cmd, yaw_cmd)
            self.print_status(0, 0, heave_cmd, yaw_cmd)

            if abs(error) < 2.0:
                print("  Target yaw tercapai")
                break

            time.sleep(0.1)

        self.stop_all()

    # =========================
    # SCAN YAW ±ANGLE
    # =========================
    def scan_yaw(self, angle=30, hold_time=2):
        """Scan kiri dan kanan dari posisi yaw saat ini, depth tetap di-hold."""
        print(f"Scan yaw ±{angle}°")
        self.update_sensor()
        center = self.yaw

        left  = center - angle
        right = center + angle
        if left  < -180: left  += 360
        if right >  180: right -= 360

        print(f"  Center:{center:.2f}° | Kiri:{left:.2f}° | Kanan:{right:.2f}°")

        self.rotate_to_yaw(left);   time.sleep(hold_time)
        self.rotate_to_yaw(right);  time.sleep(hold_time)
        self.rotate_to_yaw(center); time.sleep(hold_time)

        print("Scan selesai\n")