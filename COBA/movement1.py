import time
import math
import signal
import sys
import threading
from pymavlink import mavutil


class Movement:

    def __init__(self, port_list=["/dev/ttyACM0", "/dev/ttyACM1"], baud=115200):
        self.port_list = port_list
        self.baud = baud
        self.master = None

        # Data sensor
        self.roll = 0.0
        self.pitch = 0.0
        self.yaw = 0.0
        self.depth = 0.0
        self.press_raw = 0.0
        self._surface_pressure = 1013.25

        # Targets
        self.depth_target_cm = None
        self.yaw_target = None
        self._was_yawing = False

        self.last_command_time = time.time()

        self._lock = threading.Lock()

        self._sensor_thread = None
        self._sensor_stop_event = threading.Event()

        self._watchdog_thread = None
        self._watchdog_stop_event = threading.Event()

        signal.signal(signal.SIGINT, self._signal_handler)

    def connect(self):
        print("Connecting to Pixhawk...")
        for port in self.port_list:
            master = None
            try:
                print(f"  Mencoba {port}...")
                master = mavutil.mavlink_connection(port, baud=self.baud)
                master.wait_heartbeat(timeout=3)
                print(f"  Connected {port}")
                self.master = master
                self._setup_data_streams()
                return True
            except Exception:
                print(f"  Gagal di {port}")
                if master is not None:
                    try:
                        master.close()
                    except Exception:
                        pass

        raise Exception("Tidak bisa connect ke Pixhawk!")

    def _request_message_interval(self, message_id, frequency_hz):
        if self.master:
            self.master.mav.command_long_send(
                self.master.target_system,
                self.master.target_component,
                mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL,
                0, message_id, int(1e6 / frequency_hz),
                0, 0, 0, 0, 0
            )

    def _setup_data_streams(self):
        self._request_message_interval(mavutil.mavlink.MAVLINK_MSG_ID_ATTITUDE, 20)
        self._request_message_interval(mavutil.mavlink.MAVLINK_MSG_ID_SCALED_PRESSURE2, 20)

    def _bypass_arming_checks(self):
        if self.master:
            self.master.mav.param_set_send(
                self.master.target_system,
                self.master.target_component,
                b'ARMING_CHECK', 0,
                mavutil.mavlink.MAV_PARAM_TYPE_INT32
            )
            time.sleep(0.5)

    def set_mode(self, mode_name, timeout=3):
        _fallback = {"MANUAL": 19, "ALT_HOLD": 2, "STABILIZE": 0, "DEPTH_HOLD": 2}
        try:
            mode_id = self.master.mode_mapping()[mode_name]
        except (KeyError, TypeError):
            mode_id = _fallback.get(mode_name, 19)

        self.master.set_mode(mode_id)
        start = time.time()
        while time.time() - start < timeout:
            hb = self.master.recv_match(type='HEARTBEAT', blocking=True, timeout=0.5)
            if hb and hb.custom_mode == mode_id:
                print(f"  Mode berubah menjadi: {mode_name}")
                return True
        return False

    def arm(self, timeout=5):
        print("Arming Thrusters...")
        self.master.arducopter_arm()
        start = time.time()
        while time.time() - start < timeout:

            self.update_sensor()
            if self.master.motors_armed():
                print("  ARMED & READY!")
                return True
            time.sleep(0.1)
        print("  GAGAL ARM!")
        return False

    def disarm(self):
        print("Disarming Thrusters...")
        if self.master:
            self.master.arducopter_disarm()

    def start(self, default_depth_cm=50):
        self.connect()
        self._bypass_arming_checks()
        self.set_mode("STABILIZE")

        if not self.arm():
            self.cleanup()
            sys.exit(1)

        print("Kalibrasi tekanan permukaan Bar30...")
        for _ in range(20):
            self.update_sensor()
            time.sleep(0.05)
        if self.press_raw > 0:
            self._surface_pressure = self.press_raw
            print(f"  Tekanan Permukaan Locked: {self._surface_pressure:.2f} hPa")

        self.update_sensor()
        self.depth_target_cm = default_depth_cm

        self.set_yaw_target()
        print(f"  Yaw Lock awal: {self.yaw_target:.2f}°")

        self._start_sensor_thread()
        self._start_watchdog()

    def _signal_handler(self, sig, frame):
        print("\n[EMERGENCY] CTRL+C Terdeteksi!")
        self.cleanup()
        sys.exit(0)

    def stop(self):
        if self.master:
            self.send_control(surge=0, sway=0, heave=500, yaw=0)

    def cleanup(self):
        print("Cleaning up resources...")
        self._stop_watchdog()
        self._stop_sensor_thread()
        self.stop()
        time.sleep(0.2)
        self.disarm()
        if self.master:
            try:
                self.master.close()
            except Exception:
                pass


    def update_sensor(self):
        if not self.master:
            return
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
                self.press_raw = msg.press_abs
                self.depth = (msg.press_abs - self._surface_pressure) * 0.01

    def _sensor_loop(self, interval=0.02):          # ~50 Hz polling
        while not self._sensor_stop_event.wait(interval):
            try:
                self.update_sensor()
            except Exception as e:
                print(f"[SENSOR] Exception: {e}")

    def _start_sensor_thread(self):
        if self._sensor_thread and self._sensor_thread.is_alive():
            return
        self._sensor_stop_event.clear()
        self._sensor_thread = threading.Thread(target=self._sensor_loop, daemon=True)
        self._sensor_thread.start()

    def _stop_sensor_thread(self):
        self._sensor_stop_event.set()
        if self._sensor_thread is not None:
            self._sensor_thread.join(timeout=1.0)

    def get_depth(self):
        return self.depth * 100     # cm

    def get_yaw(self):
        return self.yaw

    def get_roll(self):
        return self.roll

    def get_pitch(self):
        return self.pitch

    def send_control(self, surge, sway, heave, yaw):
        if self.master:
            try:
                with self._lock:
                    self.master.mav.manual_control_send(
                        self.master.target_system,
                        self.master.target_component,
                        int(surge), int(sway), int(heave), int(yaw),
                        0
                    )
                self.last_command_time = time.time()
            except Exception as e:
                print(f"[SEND_CONTROL] Exception: {e}")

    def watchdog_check(self):
        if time.time() - self.last_command_time > 1.0:
            print("[WATCHDOG] Vision timeout — menghentikan ROV dan disarm.")
            self.stop()
            time.sleep(0.1)
            self.disarm()

    def _watchdog_loop(self, interval=0.2):
        while not self._watchdog_stop_event.wait(interval):
            self.watchdog_check()

    def _start_watchdog(self):
        if self._watchdog_thread and self._watchdog_thread.is_alive():
            return
        self._watchdog_stop_event.clear()
        self._watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True)
        self._watchdog_thread.start()

    def _stop_watchdog(self):
        self._watchdog_stop_event.set()
        if self._watchdog_thread is not None:
            self._watchdog_thread.join(timeout=1.0)

    def set_yaw_target(self):

        self.yaw_target = self.yaw

    def yaw_control(self):
        if self.yaw_target is None:
            return 0

        error = self.yaw_target - self.yaw
        if error > 180:
            error -= 360
        elif error < -180:
            error += 360

        return int(max(-250, min(250, 4.5 * error)))

    def set_depth_target(self, target_depth_cm):
        self.depth_target_cm = target_depth_cm

    def depth_hold_control(self):
        if self.depth_target_cm is None:
            return 500

        current_cm = self.depth * 100
        error_cm = self.depth_target_cm - current_cm

        if abs(error_cm) < 1.0:
            return 500

        return int(max(300, min(700, 500 + (2.5 * error_cm))))


    def _move_once(self, surge, sway, depth, yaw):

        surge = max(-1000, min(1000, surge))
        sway  = max(-1000, min(1000, sway))
        yaw   = max(-1000, min(1000, yaw))

        if depth is not None:
            self.depth_target_cm = depth

        heave = self.depth_hold_control()

        if yaw != 0:
            yaw_cmd = yaw
            self._was_yawing = True
        else:
            if self._was_yawing:
                # Baru selesai belok — kunci heading sekarang secara otomatis
                self.set_yaw_target()
                self._was_yawing = False
            if self.yaw_target is None:
                self.set_yaw_target()
            yaw_cmd = self.yaw_control()

        self.send_control(surge=surge, sway=sway, heave=heave, yaw=yaw_cmd)

    def move(self, duration=None, surge=0, sway=0, depth=None, yaw=0):

        if duration is None:
            # Non-blocking: satu tick seperti sebelumnya
            self._move_once(surge, sway, depth, yaw)
            return

        # Blocking mode
        if duration <= 0:
            return

        print(f"[MOVE] surge={surge} sway={sway} depth={depth} yaw={yaw} duration={duration:.2f}s")
        interval = 0.05          # 20 Hz
        end_time = time.time() + duration

        while time.time() < end_time:
            self._move_once(surge, sway, depth, yaw)
            time.sleep(interval)

        # Selesai: hentikan surge & sway, tapi pertahankan depth hold & yaw lock
        self._move_once(surge=0, sway=0, depth=None, yaw=0)
        print(f"[MOVE] Selesai — depth hold & yaw lock aktif")

    def dive_to_depth(self, target_depth_cm, tolerance_cm=4, timeout=15):
        print(f"Menyelam ke kedalaman: {target_depth_cm} cm")
        self.set_depth_target(target_depth_cm)
        start = time.time()

        while time.time() - start < timeout:
            current = self.depth * 100          # sensor thread yang update self.depth

            if abs(target_depth_cm - current) <= tolerance_cm:
                print(f"Kedalaman tercapai: {target_depth_cm:.1f} cm")
                self.move(surge=0, sway=0, depth=target_depth_cm, yaw=0)
                return True

            self.move(surge=0, sway=0, depth=target_depth_cm, yaw=0)
            time.sleep(0.05)

        print("Timeout dive tercapai")
        return False
