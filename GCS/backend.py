from flask import Flask, Response, jsonify, request
from flask_cors import CORS
import cv2
import threading
import time
import math
import datetime
import numpy as np

# pyzbar opsional
try:
    from pyzbar import pyzbar
    PYZBAR_AVAILABLE = True
except ImportError:
    PYZBAR_AVAILABLE = False
    print("[WARN] pyzbar tidak ditemukan. QR scan dinonaktifkan.")

# pymavlink opsional
try:
    from pymavlink import mavutil
    MAVLINK_AVAILABLE = True
except ImportError:
    MAVLINK_AVAILABLE = False
    print("[WARN] pymavlink tidak ditemukan. Mode dummy aktif.")

app = Flask(__name__)
CORS(app)

# ============================================================
# KONFIGURASI — SESUAIKAN DI SINI
# ============================================================

try:
    SERIAL_PORT = '/dev/ttyACM0'
    BAUD_RATE   = 115200
except :
    SERIAL_PORT = '/dev/ttyACM1'
    BAUD_RATE   = 115200
    

CAM_MAPPING = {0: 0, 1: 1}   # cam_id → OpenCV index
CAM_W, CAM_H = 640, 480

# ============================================================
# GLOBAL STATE
# ============================================================
state = {
    "x": 0.0, "y": 0.0, "z": 0.0,
    "roll": 0.0, "pitch": 0.0, "yaw": 0.0,
    "depth": 0.0, "depth_pressure": 0.0,
    "dr_x": 0.0, "dr_y": 0.0,
    "pos_valid": False,
    "rollspeed": 0.0, "pitchspeed": 0.0, "yawspeed": 0.0,
    "mavlink_connected": False,
    "qr_data": {"target_id": "-", "type": "-", "valid": False, "time": "-"}
}

_dr_lock   = threading.Lock()
_dr_vx     = 0.0
_dr_vy     = 0.0
_dr_last_t = None

zoom_level     = 1.0
cameras_active = False
state_lock     = threading.Lock()

_last_frames      = {}
_last_frames_lock = threading.Lock()

# ============================================================
# 1. MAVLINK THREAD (Dual-Mode Tracker & Simulation Fallback)
# ============================================================
def wrap_deg(angle):
    return (angle + 180) % 360 - 180

def mavlink_thread():
    global _dr_vx, _dr_vy, _dr_last_t, cameras_active, zoom_level

    if not MAVLINK_AVAILABLE:
        # MODE SIMULASI MANDIRI JIKA PYMAVLINK TIDAK ADA
        while True:
            time.sleep(0.1)
            now = time.time()
            if _dr_last_t is None:
                _dr_last_t = now
                continue
            dt = now - _dr_last_t
            _dr_last_t = now

            # Gerak melingkar otomatis untuk testing UI
            state["yaw"] = (state.get("yaw", 0) + 4) % 360
            yaw_rad = math.radians(state["yaw"])
            state["dr_x"] += 0.4 * math.cos(yaw_rad) * dt
            state["dr_y"] += 0.4 * math.sin(yaw_rad) * dt
            state["depth"] = 0.4 + 0.1 * math.sin(now)
            state["mavlink_connected"] = True
            state["pos_valid"] = False
        return

    while True:
        try:
            print(f"[MAVLink] Menghubungkan ke port {SERIAL_PORT}...")
            master = mavutil.mavlink_connection(SERIAL_PORT, baud=BAUD_RATE)
            hb = master.wait_heartbeat(timeout=10)
            if hb is None:
                print("[MAVLink] Heartbeat timeout. Mencoba kembali...")
                time.sleep(3)
                continue

            print(f"[MAVLink] Terhubung! System ID: {master.target_system}")
            state["mavlink_connected"] = True

            def req(msg_id, hz):
                master.mav.command_long_send(
                    master.target_system, master.target_component,
                    mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL, 0,
                    msg_id, 1e6 / hz, 0, 0, 0, 0, 0)

            req(mavutil.mavlink.MAVLINK_MSG_ID_ATTITUDE, 10)
            req(mavutil.mavlink.MAVLINK_MSG_ID_LOCAL_POSITION_NED, 10)
            req(mavutil.mavlink.MAVLINK_MSG_ID_SCALED_PRESSURE2, 10)
            req(mavutil.mavlink.MAVLINK_MSG_ID_RAW_IMU, 25)
            req(mavutil.mavlink.MAVLINK_MSG_ID_RC_CHANNELS, 10)

            _dr_vx = 0.0; _dr_vy = 0.0; _dr_last_t = None
            state["dr_x"] = 0.0; state["dr_y"] = 0.0
            state["pos_valid"] = False

            while True:
                msg = master.recv_match(blocking=False)
                if msg is None:
                    time.sleep(0.001)
                    continue
                t = msg.get_type()

                if t == 'ATTITUDE':
                    state["roll"]       = math.degrees(msg.roll)
                    state["pitch"]      = math.degrees(msg.pitch)
                    # Normalisasi sudut kompas ke format 0-360 derajat
                    raw_yaw = math.degrees(msg.yaw)
                    state["yaw"]        = raw_yaw if raw_yaw >= 0 else raw_yaw + 360
                    state["rollspeed"]  = math.degrees(msg.rollspeed)
                    state["pitchspeed"] = math.degrees(msg.pitchspeed)
                    state["yawspeed"]   = math.degrees(msg.yawspeed)

                elif t == 'LOCAL_POSITION_NED':
                    x, y, z = msg.x, msg.y, msg.z
                    # Jika terdeteksi perubahan posisi absolut (SITL / USBL aktif)
                    if not state["pos_valid"] and (abs(x) > 0.05 or abs(y) > 0.05):
                        state["pos_valid"] = True
                    state["x"] = x; state["y"] = y; state["z"] = z
                    state["depth"] = max(0.0, -z)

                elif t == 'RC_CHANNELS':
                    # Integrasi Dead Reckoning Kinematik berbasis Channel RC input Gerak Maju (Ch 5)
                    ch5_forward = msg.chan5_raw if hasattr(msg, 'chan5_raw') else 1500
                    now = time.time()
                    if _dr_last_t is not None:
                        dt = now - _dr_last_t
                        if 0 < dt < 0.5 and not state["pos_valid"]:
                            # Batas threshold mati joystick tengah = 1500 (+/- 50)
                            if abs(ch5_forward - 1500) > 50:
                                speed = 0.6 if ch5_forward > 1500 else -0.6
                                yaw_rad = math.radians(state.get("yaw", 0))
                                state["dr_x"] += speed * math.cos(yaw_rad) * dt
                                state["dr_y"] += speed * math.sin(yaw_rad) * dt
                    _dr_last_t = now

                elif t == 'RAW_IMU':
                    # ============================================================
                    # PERBAIKAN BUG: Koreksi gravitasi dari pitch & roll
                    # ============================================================
                    # Sebelumnya: ax/ay body frame langsung dirotasi pakai yaw saja.
                    # Masalah: ketika ROV pitch, sensor xacc merekam komponen gravitasi
                    # (g * sin(pitch)) dan dianggap sebagai gerak translasi → trajectory
                    # ikut maju padahal ROV diam di tempat.
                    #
                    # Fix: subtract proyeksi gravitasi ke body frame (dari pitch & roll)
                    # sebelum diintegrasikan, sehingga hanya akselerasi gerak bersih
                    # yang masuk ke dead reckoning.
                    # ============================================================
                    SC = 9.80665 / 1000.0
                    ax_body = msg.xacc * SC
                    ay_body = msg.yacc * SC
                    # az_body = msg.zacc * SC  # tidak dipakai untuk dr_x/dr_y

                    roll_r  = math.radians(state.get("roll",  0.0))
                    pitch_r = math.radians(state.get("pitch", 0.0))
                    yr      = math.radians(state.get("yaw",   0.0))

                    g = 9.80665
                    # Kurangi komponen gravitasi yang terproyeksi ke body X dan Y
                    # akibat kemiringan pitch dan roll
                    ax_body -= g * math.sin(pitch_r)
                    ay_body += g * math.sin(roll_r) * math.cos(pitch_r)

                    # Rotasi sisa akselerasi gerak dari body frame → NED frame (pakai yaw)
                    ax_ned = ax_body * math.cos(yr) - ay_body * math.sin(yr)
                    ay_ned = ax_body * math.sin(yr) + ay_body * math.cos(yr)

                    now = time.time()
                    with _dr_lock:
                        if _dr_last_t is not None and not state["pos_valid"]:
                            dt = now - _dr_last_t
                            if 0 < dt < 0.5:
                                DECAY = 0.90
                                _dr_vx = _dr_vx * DECAY + ax_ned * dt
                                _dr_vy = _dr_vy * DECAY + ay_ned * dt
                                # Hanya tambahkan jika di luar noise threshold static
                                if abs(_dr_vx) > 0.02 or abs(_dr_vy) > 0.02:
                                    state["dr_x"] += _dr_vx * dt
                                    state["dr_y"] += _dr_vy * dt
                        _dr_last_t = now

                elif t == 'SCALED_PRESSURE2':
                    state["depth_pressure"] = max(0.0, (msg.press_abs - 1013.25) * 0.01)

        except Exception as e:
            print(f"[MAVLink] Terputus / Error: {e}")
            state["mavlink_connected"] = False
            time.sleep(3)

threading.Thread(target=mavlink_thread, daemon=True).start()

# ============================================================
# 2. CAMERA STREAM & INSTANT SNAPSHOT CACHE
# ============================================================
def zoom_frame(frame, zoom=1.0):
    if zoom <= 1.0: return frame
    h, w = frame.shape[:2]
    nw = int(w / zoom); nh = int(h / zoom)
    x1 = (w - nw) // 2; y1 = (h - nh) // 2
    return cv2.resize(frame[y1:y1+nh, x1:x1+nw], (w, h))

# filter camera
def white_balance_gray_world(frame):
    result = frame.astype(np.float32)
    avg_b = np.mean(result[:, :, 0])
    avg_g = np.mean(result[:, :, 1])
    avg_r = np.mean(result[:, :, 2])
    avg_gray = (avg_b + avg_g + avg_r) / 3
    result[:, :, 0] *= avg_gray / (avg_b + 1e-6)
    result[:, :, 1] *= avg_gray / (avg_g + 1e-6)
    result[:, :, 2] *= avg_gray / (avg_r + 1e-6)
    return np.clip(result, 0, 255).astype(np.uint8)

def apply_clahe(frame, clip_limit=2.0, tile_grid_size=(8, 8)):
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(
        clipLimit=clip_limit,
        tileGridSize=tile_grid_size
    )
    l_clahe = clahe.apply(l)
    lab_clahe = cv2.merge((l_clahe, a, b))
    return cv2.cvtColor(lab_clahe, cv2.COLOR_LAB2BGR)

def adjust_gamma(frame, gamma=1.0):
    inv_gamma = 1.0 / gamma
    table = np.array([
        ((i / 255.0) ** inv_gamma) * 255
        for i in range(256)
    ]).astype("uint8")
    return cv2.LUT(frame, table)

def adaptive_gamma(frame, dark_threshold=80, bright_threshold=170):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    brightness = np.mean(gray)
    if brightness < dark_threshold:
        # gambar terlalu gelap, diterangkan
        return adjust_gamma(frame, gamma=0.7)
    elif brightness > bright_threshold:
        # gambar terlalu terang, digelapkan sedikit
        return adjust_gamma(frame, gamma=1.3)
    return frame

def enhance_frame(frame):
    if frame is None:
        return None
    enhanced = frame.copy()
    enhanced = white_balance_gray_world(enhanced)
    # enhanced = apply_clahe(enhanced)
    enhanced = adaptive_gamma(enhanced)
    return enhanced

def generate_frames(camera_id):
    global cameras_active, zoom_level
    cv_index = CAM_MAPPING.get(camera_id, camera_id)
    cap = cv2.VideoCapture(cv_index)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAM_W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAM_H)

    while cameras_active:
        success, frame = cap.read()
        if not success:
            time.sleep(0.03)
            continue

        frame = zoom_frame(frame, zoom_level)
        frame = enhance_frame(frame)

        # Scanner QR khusus pada Kamera Utama (ID: 0)
        if camera_id == 0 and PYZBAR_AVAILABLE:
            barcodes = pyzbar.decode(frame)
            if barcodes:
                for b in barcodes:
                    text = b.data.decode("utf-8")
                    state["qr_data"] = {
                        "target_id": text,
                        "type": "QR-CODE",
                        "valid": True,
                        "time": datetime.datetime.now().strftime("%H:%M:%S")
                    }
                    break

        with _last_frames_lock:
            _last_frames[camera_id] = frame.copy()

        ret, jpeg = cv2.imencode('.jpg', frame)
        if not ret:
            continue
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')

    cap.release()

# ============================================================
# 3. HTTP FLASK ROUTING API
# ============================================================
@app.route('/start_cameras', methods=['POST'])
def start_cameras():
    global cameras_active
    if not cameras_active:
        cameras_active = True
    return jsonify({"status": "cameras activated"})

@app.route('/stop_cameras', methods=['POST'])
def stop_cameras():
    global cameras_active
    cameras_active = False
    return jsonify({"status": "cameras deactivated"})

@app.route('/video_feed/<int:camera_id>')
def video_feed(camera_id):
    return Response(generate_frames(camera_id),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/snapshot/<int:camera_id>')
def snapshot(camera_id):
    with _last_frames_lock:
        if camera_id in _last_frames:
            ret, jpeg = cv2.imencode('.jpg', _last_frames[camera_id])
            if ret:
                return Response(jpeg.tobytes(), mimetype='image/jpeg')
    return jsonify({"error": f"No cached frame for camera {camera_id}"}), 404

@app.route('/telemetry')
def get_telemetry():
    return jsonify({
        "x":              float(state.get("x", 0.0)),
        "y":              float(state.get("y", 0.0)),
        "z":              float(state.get("z", 0.0)),
        "roll":           float(state.get("roll", 0.0)),
        "pitch":          float(state.get("pitch", 0.0)),
        "yaw":            float(state.get("yaw", 0.0)),
        "depth":          float(state.get("depth", 0.0)),
        "depth_pressure": float(state.get("depth_pressure", 0.0)),
        "dr_x":           float(state.get("dr_x", 0.0)),
        "dr_y":           float(state.get("dr_y", 0.0)),
        "pos_valid":      bool(state.get("pos_valid", False)),
        "qr_data":        state.get("qr_data")
    })

@app.route('/zoom/in', methods=['POST'])
def zoom_in():
    global zoom_level
    zoom_level = min(round(zoom_level + 0.2, 1), 3.0)
    return jsonify({"zoom_level": zoom_level})

@app.route('/zoom/out', methods=['POST'])
def zoom_out():
    global zoom_level
    zoom_level = max(round(zoom_level - 0.2, 1), 1.0)
    return jsonify({"zoom_level": zoom_level})

@app.route('/status')
def status():
    return jsonify({
        "backend":           "online",
        "mavlink_connected": state.get("mavlink_connected", False),
        "cameras_active":    cameras_active,
        "zoom_level":        zoom_level,
        "pyzbar":            PYZBAR_AVAILABLE,
        "pymavlink":         MAVLINK_AVAILABLE,
    })

if __name__ == '__main__':
    print("=" * 50)
    print("  ROV GCS Backend System  ")
    print("=" * 50)
    app.run(host='0.0.0.0', port=8080, debug=False, threaded=True)
