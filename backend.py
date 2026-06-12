# from flask import Flask, Response, jsonify, send_file, request
# from flask_cors import CORS
# import cv2
# import threading
# import time
# import math
# import datetime
# import os
# import csv
# import io
# import zipfile

# # pyzbar opsional
# try:
#     from pyzbar import pyzbar
#     PYZBAR_AVAILABLE = True
# except ImportError:
#     PYZBAR_AVAILABLE = False
#     print("[WARN] pyzbar tidak ditemukan. QR scan dinonaktifkan.")

# # pymavlink opsional
# try:
#     from pymavlink import mavutil
#     MAVLINK_AVAILABLE = True
# except ImportError:
#     MAVLINK_AVAILABLE = False
#     print("[WARN] pymavlink tidak ditemukan. Telemetri akan menggunakan dummy data.")

# app = Flask(__name__)
# CORS(app)

# # ============================================================
# # KONFIGURASI — SESUAIKAN DI SINI
# # ============================================================
# SERIAL_PORT = '/dev/ttyACM0'
# BAUD_RATE   = 115200

# CAM_MAPPING = {0: 0, 1: 2}   # Cam 1 → index 0, Cam 2 → index 2
# CAM_W, CAM_H = 640, 480

# # Direktori penyimpanan di Jetson
# DATA_DIR = os.path.expanduser("~/rov_data")
# os.makedirs(DATA_DIR, exist_ok=True)

# # ============================================================
# # GLOBAL STATE
# # ============================================================
# state = {
#     "x": 0.0, "y": 0.0, "z": 0.0,
#     "roll": 0.0, "pitch": 0.0, "yaw": 0.0,
#     "depth": 0.0, "depth_pressure": 0.0,
#     "dr_x": 0.0, "dr_y": 0.0,
#     "pos_valid": False,
#     "rollspeed": 0.0, "pitchspeed": 0.0, "yawspeed": 0.0,
#     "mavlink_connected": False,
#     "qr_data": {
#         "target_id": "-",
#         "type": "-",
#         "valid": False,
#         "time": "-"
#     }
# }

# _dr_lock   = threading.Lock()
# _dr_vx     = 0.0
# _dr_vy     = 0.0
# _dr_last_t = None

# zoom_level     = 1.0
# cameras_active = False
# state_lock     = threading.Lock()

# # ── Rekaman video ──
# _rec_lock       = threading.Lock()
# _rec_active     = False
# _rec_session_id = None
# _rec_writers    = {}    # {cam_id: cv2.VideoWriter}
# _rec_caps       = {}    # reference ke cap yang sedang streaming
# _rec_session_dir = None

# # ── Telemetry CSV ──
# _csv_file   = None
# _csv_writer = None

# # ── Log buffer ──
# _log_buffer = []
# _log_lock   = threading.Lock()

# def _add_log(msg):
#     ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
#     entry = f"[{ts}] {msg}"
#     with _log_lock:
#         _log_buffer.append(entry)
#         if len(_log_buffer) > 500:
#             _log_buffer.pop(0)
#     print(entry)

# # ============================================================
# # 1. MAVLINK THREAD
# # ============================================================
# def wrap_deg(angle):
#     return (angle + 180) % 360 - 180

# def mavlink_thread():
#     if not MAVLINK_AVAILABLE:
#         print("[MAVLink] pymavlink tidak tersedia. Thread tidak dijalankan.")
#         return

#     while True:
#         try:
#             print(f"[MAVLink] Mencoba konek ke {SERIAL_PORT} @ {BAUD_RATE}...")
#             master = mavutil.mavlink_connection(SERIAL_PORT, baud=BAUD_RATE)

#             print("[MAVLink] Menunggu heartbeat Pixhawk...")
#             hb = master.wait_heartbeat(timeout=10)
#             if hb is None:
#                 print("[MAVLink] Heartbeat timeout. Retry...")
#                 time.sleep(3)
#                 continue

#             print(f"[MAVLink] Terhubung! System ID: {master.target_system}")
#             state["mavlink_connected"] = True

#             def request_message_interval(message_id, frequency_hz):
#                 master.mav.command_long_send(
#                     master.target_system, master.target_component,
#                     mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL, 0,
#                     message_id, 1e6 / frequency_hz,
#                     0, 0, 0, 0, 0
#                 )

#             request_message_interval(mavutil.mavlink.MAVLINK_MSG_ID_ATTITUDE, 10)
#             request_message_interval(mavutil.mavlink.MAVLINK_MSG_ID_LOCAL_POSITION_NED, 10)
#             request_message_interval(mavutil.mavlink.MAVLINK_MSG_ID_SCALED_PRESSURE2, 10)
#             request_message_interval(mavutil.mavlink.MAVLINK_MSG_ID_RAW_IMU, 25)

#             global _dr_vx, _dr_vy, _dr_last_t
#             _dr_vx = 0.0; _dr_vy = 0.0; _dr_last_t = None
#             state["dr_x"] = 0.0; state["dr_y"] = 0.0
#             state["pos_valid"] = False

#             while True:
#                 msg = master.recv_match(blocking=False)
#                 if msg is None:
#                     time.sleep(0.001)
#                     continue

#                 msg_type = msg.get_type()

#                 if msg_type == 'ATTITUDE':
#                     state["roll"]       = math.degrees(msg.roll)
#                     state["pitch"]      = math.degrees(msg.pitch)
#                     state["yaw"]        = wrap_deg(math.degrees(msg.yaw))
#                     state["rollspeed"]  = math.degrees(msg.rollspeed)
#                     state["pitchspeed"] = math.degrees(msg.pitchspeed)
#                     state["yawspeed"]   = math.degrees(msg.yawspeed)

#                     # Tulis ke CSV kalau lagi rekam
#                     with _rec_lock:
#                         if _rec_active and _csv_writer:
#                             _csv_writer.writerow([
#                                 datetime.datetime.now().isoformat(),
#                                 state["roll"], state["pitch"], state["yaw"],
#                                 state["depth"], state["depth_pressure"],
#                                 state["x"], state["y"], state["z"],
#                                 state["dr_x"], state["dr_y"]
#                             ])
#                             _csv_file.flush()

#                 elif msg_type == 'LOCAL_POSITION_NED':
#                     x, y, z = msg.x, msg.y, msg.z
#                     if not state["pos_valid"] and (abs(x) > 0.05 or abs(y) > 0.05):
#                         state["pos_valid"] = True
#                     state["x"] = x; state["y"] = y; state["z"] = z
#                     state["depth"] = max(0.0, -z)

#                 elif msg_type == 'RAW_IMU':
#                     ACCEL_SCALE = 9.80665 / 1000.0
#                     ax_raw = msg.xacc * ACCEL_SCALE
#                     ay_raw = msg.yacc * ACCEL_SCALE
#                     yaw_rad = math.radians(state["yaw"])
#                     ax_ned = ax_raw * math.cos(yaw_rad) - ay_raw * math.sin(yaw_rad)
#                     ay_ned = ax_raw * math.sin(yaw_rad) + ay_raw * math.cos(yaw_rad)
#                     now = time.time()
#                     with _dr_lock:
#                         if _dr_last_t is not None:
#                             dt = now - _dr_last_t
#                             if 0 < dt < 0.5:
#                                 DECAY = 0.92
#                                 _dr_vx = _dr_vx * DECAY + ax_ned * dt
#                                 _dr_vy = _dr_vy * DECAY + ay_ned * dt
#                                 state["dr_x"] += _dr_vx * dt
#                                 state["dr_y"] += _dr_vy * dt
#                         _dr_last_t = now

#                 elif msg_type == 'SCALED_PRESSURE2':
#                     state["depth_pressure"] = (msg.press_abs - 1013.25) * 0.01

#         except Exception as e:
#             print(f"[MAVLink] Error: {e}")
#             state["mavlink_connected"] = False
#             print("[MAVLink] Reconnect dalam 3 detik...")
#             time.sleep(3)

# threading.Thread(target=mavlink_thread, daemon=True).start()

# # ============================================================
# # 2. PROSES FRAME (ZOOM + QR + REKAM)
# # ============================================================
# def zoom_frame(frame, zoom=1.0):
#     if zoom <= 1.0:
#         return frame
#     h, w = frame.shape[:2]
#     new_w = int(w / zoom)
#     new_h = int(h / zoom)
#     x1 = (w - new_w) // 2
#     y1 = (h - new_h) // 2
#     cropped = frame[y1:y1 + new_h, x1:x1 + new_w]
#     return cv2.resize(cropped, (w, h))

# def generate_frames(camera_id):
#     global cameras_active, zoom_level

#     camera_idx = CAM_MAPPING.get(camera_id, camera_id)
#     print(f"[Kamera {camera_id}] Membuka index OpenCV: {camera_idx}")

#     cap = cv2.VideoCapture(camera_idx)
#     if not cap.isOpened():
#         print(f"[Kamera {camera_id}] GAGAL membuka index {camera_idx}!")
#         blank = b'\xff\xd8\xff'
#         yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + blank + b'\r\n')
#         return

#     cap.set(cv2.CAP_PROP_FRAME_WIDTH,  CAM_W)
#     cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAM_H)
#     cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

#     frame_count = 0
#     fps         = 0
#     start_time  = time.time()
#     print(f"[Kamera {camera_id}] Stream dimulai.")

#     while cameras_active:
#         success, frame = cap.read()
#         if not success:
#             time.sleep(0.05)
#             continue

#         frame_count += 1
#         elapsed = time.time() - start_time
#         if elapsed >= 1.0:
#             fps        = frame_count / elapsed
#             frame_count = 0
#             start_time  = time.time()

#         frame = zoom_frame(frame, zoom_level)

#         if PYZBAR_AVAILABLE:
#             barcodes = pyzbar.decode(frame)
#             for barcode in barcodes:
#                 (bx, by, bw, bh) = barcode.rect
#                 cv2.rectangle(frame, (bx, by), (bx + bw, by + bh), (0, 0, 255), 2)
#                 barcode_data = barcode.data.decode("utf-8", errors="ignore")
#                 barcode_data = "".join(c for c in barcode_data if 32 <= ord(c) <= 126)
#                 cv2.putText(frame, f"{barcode_data} ({barcode.type})",
#                             (bx, by - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
#                 with state_lock:
#                     state["qr_data"] = {
#                         "target_id": barcode_data,
#                         "type":      barcode.type,
#                         "valid":     True,
#                         "time":      datetime.datetime.now().strftime("%H:%M:%S")
#                     }

#         cv2.putText(frame, f"FPS: {int(fps)}",
#                     (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2, cv2.LINE_AA)

#         # ── Tulis ke VideoWriter kalau lagi rekam ──
#         with _rec_lock:
#             if _rec_active and camera_id in _rec_writers:
#                 _rec_writers[camera_id].write(frame)

#         ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
#         if not ret:
#             continue

#         yield (b'--frame\r\n'
#                b'Content-Type: image/jpeg\r\n\r\n'
#                + buffer.tobytes()
#                + b'\r\n')

#     cap.release()
#     print(f"[Kamera {camera_id}] Stream dihentikan.")

# # ============================================================
# # 3. HELPER REKAMAN
# # ============================================================
# def _new_session_dir():
#     ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
#     path = os.path.join(DATA_DIR, ts)
#     os.makedirs(path, exist_ok=True)
#     os.makedirs(os.path.join(path, "snapshots"), exist_ok=True)
#     return path, ts

# def _start_video_writer(session_dir, camera_id):
#     fourcc = cv2.VideoWriter_fourcc(*'mp4v')
#     path   = os.path.join(session_dir, f"video_cam{camera_id}.mp4")
#     writer = cv2.VideoWriter(path, fourcc, 20.0, (CAM_W, CAM_H))
#     return writer

# def _open_csv(session_dir):
#     path = os.path.join(session_dir, "telemetry.csv")
#     f    = open(path, "w", newline="")
#     w    = csv.writer(f)
#     w.writerow(["timestamp", "roll", "pitch", "yaw",
#                 "depth", "depth_pressure",
#                 "ned_x", "ned_y", "ned_z",
#                 "dr_x", "dr_y"])
#     return f, w

# # ============================================================
# # 4. ENDPOINTS API
# # ============================================================

# # ── Kamera dasar ──
# @app.route('/start_cameras', methods=['POST'])
# def start_cameras():
#     global cameras_active
#     cameras_active = True
#     _add_log("Kamera dinyalakan")
#     return jsonify({"status": "success"})

# @app.route('/stop_cameras', methods=['POST'])
# def stop_cameras():
#     global cameras_active
#     cameras_active = False
#     _add_log("Kamera dimatikan")
#     return jsonify({"status": "success"})

# @app.route('/video_feed/<int:camera_id>')
# def video_feed(camera_id):
#     return Response(
#         generate_frames(camera_id),
#         mimetype='multipart/x-mixed-replace; boundary=frame',
#         headers={
#             'Cache-Control': 'no-cache, no-store, must-revalidate',
#             'Access-Control-Allow-Origin': '*'
#         }
#     )

# # ── Zoom ──
# @app.route('/zoom/in', methods=['POST'])
# def zoom_in():
#     global zoom_level
#     zoom_level = min(round(zoom_level + 0.2, 1), 3.0)
#     return jsonify({"status": "success", "zoom_level": zoom_level})

# @app.route('/zoom/out', methods=['POST'])
# def zoom_out():
#     global zoom_level
#     zoom_level = max(round(zoom_level - 0.2, 1), 1.0)
#     return jsonify({"status": "success", "zoom_level": zoom_level})

# # ── Telemetri ──
# @app.route('/telemetry', methods=['GET'])
# def get_telemetry():
#     with state_lock:
#         data = dict(state)
#         data["qr_data"] = dict(state["qr_data"])
#     return jsonify(data)

# # ── SNAPSHOT ──
# @app.route('/snapshot', methods=['POST'])
# def snapshot():
#     """
#     Ambil snapshot dari kedua kamera dan simpan di Jetson.
#     Kalau ada sesi rekaman aktif, simpan ke folder sesi.
#     Kalau tidak, simpan ke ~/rov_data/snapshots/
#     """
#     ts       = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S_%f")[:-3]
#     saved    = []

#     for cam_id, cam_idx in CAM_MAPPING.items():
#         cap = cv2.VideoCapture(cam_idx)
#         if not cap.isOpened():
#             continue
#         ret, frame = cap.read()
#         cap.release()
#         if not ret:
#             continue

#         # Tentukan folder simpan
#         with _rec_lock:
#             if _rec_active and _rec_session_dir:
#                 folder = os.path.join(_rec_session_dir, "snapshots")
#             else:
#                 folder = os.path.join(DATA_DIR, "snapshots")
#         os.makedirs(folder, exist_ok=True)

#         filename = f"snap_cam{cam_id}_{ts}.jpg"
#         filepath = os.path.join(folder, filename)
#         cv2.imwrite(filepath, frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
#         saved.append(filename)
#         _add_log(f"[SNAP] Disimpan: {filepath}")

#     return jsonify({"status": "success", "saved": saved, "timestamp": ts})

# # ── REKAM VIDEO ──
# @app.route('/record/start', methods=['POST'])
# def record_start():
#     global _rec_active, _rec_session_id, _rec_writers, _rec_session_dir
#     global _csv_file, _csv_writer

#     with _rec_lock:
#         if _rec_active:
#             return jsonify({"status": "already_recording", "session": _rec_session_id})

#         session_dir, session_id = _new_session_dir()
#         _rec_session_dir = session_dir
#         _rec_session_id  = session_id

#         # Buka VideoWriter untuk tiap kamera yang aktif
#         _rec_writers = {}
#         for cam_id in CAM_MAPPING:
#             _rec_writers[cam_id] = _start_video_writer(session_dir, cam_id)

#         # Buka CSV telemetri
#         _csv_file, _csv_writer = _open_csv(session_dir)

#         _rec_active = True
#         _add_log(f"[REC] Rekaman dimulai → sesi {session_id}")

#     return jsonify({"status": "recording", "session": session_id, "dir": session_dir})

# @app.route('/record/stop', methods=['POST'])
# def record_stop():
#     global _rec_active, _rec_session_id, _rec_writers
#     global _csv_file, _csv_writer

#     with _rec_lock:
#         if not _rec_active:
#             return jsonify({"status": "not_recording"})

#         _rec_active = False
#         sid = _rec_session_id

#         # Tutup VideoWriters
#         for w in _rec_writers.values():
#             w.release()
#         _rec_writers = {}

#         # Tutup CSV
#         if _csv_file:
#             _csv_file.close()
#             _csv_file   = None
#             _csv_writer = None

#         _add_log(f"[REC] Rekaman dihentikan → sesi {sid}")

#     return jsonify({"status": "stopped", "session": sid})

# @app.route('/record/status', methods=['GET'])
# def record_status():
#     with _rec_lock:
#         return jsonify({
#             "recording": _rec_active,
#             "session":   _rec_session_id
#         })

# # ── SESI / DOWNLOAD ──
# @app.route('/sessions', methods=['GET'])
# def list_sessions():
#     """Daftar semua folder sesi di ~/rov_data/"""
#     sessions = []
#     for name in sorted(os.listdir(DATA_DIR), reverse=True):
#         path = os.path.join(DATA_DIR, name)
#         if not os.path.isdir(path):
#             continue

#         # Hitung total ukuran
#         total_bytes = 0
#         files_info  = []
#         for root, _, files in os.walk(path):
#             for f in files:
#                 fp   = os.path.join(root, f)
#                 size = os.path.getsize(fp)
#                 total_bytes += size
#                 rel  = os.path.relpath(fp, path)
#                 files_info.append({"name": rel, "size": size})

#         sessions.append({
#             "id":          name,
#             "path":        path,
#             "total_bytes": total_bytes,
#             "files":       files_info
#         })

#     return jsonify(sessions)

# @app.route('/sessions/<session_id>/download', methods=['GET'])
# def download_session(session_id):
#     """
#     Download seluruh sesi sebagai satu file ZIP.
#     Frontend bisa panggil ini lalu browser otomatis download.
#     """
#     # Validasi nama sesi (keamanan dasar)
#     session_id = os.path.basename(session_id)
#     session_dir = os.path.join(DATA_DIR, session_id)
#     if not os.path.isdir(session_dir):
#         return jsonify({"error": "Sesi tidak ditemukan"}), 404

#     # Buat ZIP di memori
#     buf = io.BytesIO()
#     with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
#         for root, _, files in os.walk(session_dir):
#             for fname in files:
#                 fpath   = os.path.join(root, fname)
#                 arcname = os.path.join(session_id, os.path.relpath(fpath, session_dir))
#                 zf.write(fpath, arcname)
#     buf.seek(0)

#     _add_log(f"[DL] Download sesi: {session_id}")
#     return send_file(
#         buf,
#         mimetype="application/zip",
#         as_attachment=True,
#         download_name=f"ROV_{session_id}.zip"
#     )

# @app.route('/sessions/<session_id>/file', methods=['GET'])
# def download_file(session_id):
#     """
#     Download satu file dalam sesi.
#     Query param: ?path=video_cam0.mp4  atau  ?path=snapshots/snap_cam0_xxx.jpg
#     """
#     session_id = os.path.basename(session_id)
#     session_dir = os.path.join(DATA_DIR, session_id)
#     rel_path    = request.args.get("path", "")

#     # Keamanan: tidak boleh ada ".." atau path absolut
#     if ".." in rel_path or rel_path.startswith("/"):
#         return jsonify({"error": "Path tidak valid"}), 400

#     fpath = os.path.join(session_dir, rel_path)
#     if not os.path.isfile(fpath):
#         return jsonify({"error": "File tidak ditemukan"}), 404

#     return send_file(fpath, as_attachment=True)

# @app.route('/sessions/<session_id>', methods=['DELETE'])
# def delete_session(session_id):
#     """Hapus folder sesi dari Jetson (bersihkan storage)."""
#     import shutil
#     session_id  = os.path.basename(session_id)
#     session_dir = os.path.join(DATA_DIR, session_id)
#     if not os.path.isdir(session_dir):
#         return jsonify({"error": "Sesi tidak ditemukan"}), 404

#     # Jangan hapus sesi yang sedang direkam
#     with _rec_lock:
#         if _rec_active and _rec_session_id == session_id:
#             return jsonify({"error": "Sesi sedang aktif direkam"}), 409

#     shutil.rmtree(session_dir)
#     _add_log(f"[DEL] Sesi dihapus: {session_id}")
#     return jsonify({"status": "deleted", "session": session_id})

# # ── Log ──
# @app.route('/log', methods=['GET'])
# def get_log():
#     """Ambil log terbaru (maks 100 baris terakhir)."""
#     with _log_lock:
#         lines = list(_log_buffer[-100:])
#     return jsonify({"log": lines})

# # ── Status ──
# @app.route('/status', methods=['GET'])
# def status():
#     return jsonify({
#         "backend":           "online",
#         "mavlink_connected": state.get("mavlink_connected", False),
#         "cameras_active":    cameras_active,
#         "zoom_level":        zoom_level,
#         "pyzbar":            PYZBAR_AVAILABLE,
#         "pymavlink":         MAVLINK_AVAILABLE,
#         "recording":         _rec_active,
#         "session":           _rec_session_id,
#         "data_dir":          DATA_DIR
#     })

# # ============================================================
# # 5. JALANKAN SERVER
# # ============================================================
# if __name__ == '__main__':
#     print("=" * 50)
#     print("  ROV GCS Backend  (with recording)")
#     print("=" * 50)
#     print(f"  Serial port   : {SERIAL_PORT}")
#     print(f"  Kamera mapping: {CAM_MAPPING}")
#     print(f"  Data dir      : {DATA_DIR}")
#     print(f"  pyzbar        : {'OK' if PYZBAR_AVAILABLE else 'TIDAK TERSEDIA'}")
#     print(f"  pymavlink     : {'OK' if MAVLINK_AVAILABLE else 'TIDAK TERSEDIA'}")
#     print(f"  Akses GCS di  : http://0.0.0.0:8080")
#     print(f"  Cek status    : http://localhost:8080/status")
#     print("=" * 50)
#     app.run(host='0.0.0.0', port=8080, debug=False, threaded=True)

from flask import Flask, Response, jsonify, request
from flask_cors import CORS
import cv2
import threading
import time
import math
import datetime

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
SERIAL_PORT = '/dev/ttyACM0'
BAUD_RATE   = 115200

CAM_MAPPING = {0: 0, 1: 2}   # cam_id → OpenCV index
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

# ============================================================
# 1. MAVLINK THREAD
# ============================================================
def wrap_deg(angle):
    return (angle + 180) % 360 - 180

def mavlink_thread():
    if not MAVLINK_AVAILABLE:
        return
    while True:
        try:
            print(f"[MAVLink] Konek ke {SERIAL_PORT}...")
            master = mavutil.mavlink_connection(SERIAL_PORT, baud=BAUD_RATE)
            hb = master.wait_heartbeat(timeout=10)
            if hb is None:
                time.sleep(3)
                continue

            print(f"[MAVLink] Terhubung! SysID: {master.target_system}")
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

            global _dr_vx, _dr_vy, _dr_last_t
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
                    state["yaw"]        = wrap_deg(math.degrees(msg.yaw))
                    state["rollspeed"]  = math.degrees(msg.rollspeed)
                    state["pitchspeed"] = math.degrees(msg.pitchspeed)
                    state["yawspeed"]   = math.degrees(msg.yawspeed)

                elif t == 'LOCAL_POSITION_NED':
                    x, y, z = msg.x, msg.y, msg.z
                    if not state["pos_valid"] and (abs(x) > 0.05 or abs(y) > 0.05):
                        state["pos_valid"] = True
                    state["x"] = x; state["y"] = y; state["z"] = z
                    state["depth"] = max(0.0, -z)

                elif t == 'RAW_IMU':
                    SC = 9.80665 / 1000.0
                    ax = msg.xacc * SC
                    ay = msg.yacc * SC
                    yr = math.radians(state["yaw"])
                    ax_ned = ax * math.cos(yr) - ay * math.sin(yr)
                    ay_ned = ax * math.sin(yr) + ay * math.cos(yr)
                    now = time.time()
                    with _dr_lock:
                        if _dr_last_t is not None:
                            dt = now - _dr_last_t
                            if 0 < dt < 0.5:
                                DECAY = 0.92
                                _dr_vx = _dr_vx * DECAY + ax_ned * dt
                                _dr_vy = _dr_vy * DECAY + ay_ned * dt
                                state["dr_x"] += _dr_vx * dt
                                state["dr_y"] += _dr_vy * dt
                        _dr_last_t = now

                elif t == 'SCALED_PRESSURE2':
                    state["depth_pressure"] = (msg.press_abs - 1013.25) * 0.01

        except Exception as e:
            print(f"[MAVLink] Error: {e}")
            state["mavlink_connected"] = False
            time.sleep(3)

threading.Thread(target=mavlink_thread, daemon=True).start()

# ============================================================
# 2. CAMERA STREAM
# ============================================================
def zoom_frame(frame, zoom=1.0):
    if zoom <= 1.0:
        return frame
    h, w = frame.shape[:2]
    nw = int(w / zoom); nh = int(h / zoom)
    x1 = (w - nw) // 2; y1 = (h - nh) // 2
    return cv2.resize(frame[y1:y1+nh, x1:x1+nw], (w, h))

def generate_frames(camera_id):
    global cameras_active, zoom_level
    cam_idx = CAM_MAPPING.get(camera_id, camera_id)
    cap = cv2.VideoCapture(cam_idx)
    if not cap.isOpened():
        print(f"[CAM {camera_id}] Gagal buka index {cam_idx}")
        yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n\r\n'
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  CAM_W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAM_H)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    print(f"[CAM {camera_id}] Stream dimulai.")

    fps_count = 0; fps = 0; t0 = time.time()

    while cameras_active:
        ok, frame = cap.read()
        if not ok:
            time.sleep(0.05)
            continue

        fps_count += 1
        elapsed = time.time() - t0
        if elapsed >= 1.0:
            fps = fps_count / elapsed
            fps_count = 0; t0 = time.time()

        frame = zoom_frame(frame, zoom_level)

        # QR scan
        if PYZBAR_AVAILABLE:
            for bc in pyzbar.decode(frame):
                bx, by, bw, bh = bc.rect
                cv2.rectangle(frame, (bx, by), (bx+bw, by+bh), (0, 0, 255), 2)
                data = bc.data.decode("utf-8", errors="ignore")
                data = "".join(c for c in data if 32 <= ord(c) <= 126)
                cv2.putText(frame, f"{data} ({bc.type})",
                            (bx, by-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
                with state_lock:
                    state["qr_data"] = {
                        "target_id": data, "type": bc.type, "valid": True,
                        "time": datetime.datetime.now().strftime("%H:%M:%S")
                    }

        cv2.putText(frame, f"FPS: {int(fps)}",
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (255,255,255), 2, cv2.LINE_AA)

        ret, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not ret:
            continue
        yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n'
               + buf.tobytes() + b'\r\n')

    cap.release()
    print(f"[CAM {camera_id}] Stream dihentikan.")

# ============================================================
# 3. ENDPOINTS
# ============================================================

@app.route('/start_cameras', methods=['POST'])
def start_cameras():
    global cameras_active
    cameras_active = True
    return jsonify({"status": "ok"})

@app.route('/stop_cameras', methods=['POST'])
def stop_cameras():
    global cameras_active
    cameras_active = False
    return jsonify({"status": "ok"})

@app.route('/video_feed/<int:camera_id>')
def video_feed(camera_id):
    return Response(
        generate_frames(camera_id),
        mimetype='multipart/x-mixed-replace; boundary=frame',
        headers={
            'Cache-Control': 'no-cache, no-store, must-revalidate',
            'Access-Control-Allow-Origin': '*'
        }
    )

@app.route('/telemetry')
def get_telemetry():
    with state_lock:
        return jsonify(dict(state))

# ── Snapshot: kirim JPEG langsung ke browser (browser yang download) ──
@app.route('/snapshot/<int:camera_id>')
def snapshot(camera_id):
    """
    Buka kamera, ambil satu frame, kirim sebagai JPEG response.
    Browser / interact.js yang membuat Blob dan trigger download.
    """
    cam_idx = CAM_MAPPING.get(camera_id, camera_id)
    cap = cv2.VideoCapture(cam_idx)
    if not cap.isOpened():
        return jsonify({"error": "Kamera tidak tersedia"}), 503
    ok, frame = cap.read()
    cap.release()
    if not ok:
        return jsonify({"error": "Gagal capture frame"}), 503

    frame = zoom_frame(frame, zoom_level)
    ret, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
    if not ret:
        return jsonify({"error": "Encode gagal"}), 500

    from flask import make_response
    resp = make_response(buf.tobytes())
    resp.headers['Content-Type']  = 'image/jpeg'
    resp.headers['Cache-Control'] = 'no-cache'
    resp.headers['Access-Control-Allow-Origin'] = '*'
    return resp

# ── Zoom ──
@app.route('/zoom/in',  methods=['POST'])
def zoom_in():
    global zoom_level
    zoom_level = min(round(zoom_level + 0.2, 1), 3.0)
    return jsonify({"zoom_level": zoom_level})

@app.route('/zoom/out', methods=['POST'])
def zoom_out():
    global zoom_level
    zoom_level = max(round(zoom_level - 0.2, 1), 1.0)
    return jsonify({"zoom_level": zoom_level})

# ── Status ──
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

# ============================================================
# 4. MAIN
# ============================================================
if __name__ == '__main__':
    print("=" * 50)
    print("  ROV GCS Backend  —  stream-only mode")
    print("  Semua penyimpanan dilakukan di laptop (browser)")
    print("=" * 50)
    print(f"  Serial  : {SERIAL_PORT} @ {BAUD_RATE}")
    print(f"  Kamera  : {CAM_MAPPING}")
    print(f"  pyzbar  : {'OK' if PYZBAR_AVAILABLE else 'tidak tersedia'}")
    print(f"  mavlink : {'OK' if MAVLINK_AVAILABLE else 'tidak tersedia'}")
    print(f"  URL     : http://0.0.0.0:8080")
    print("=" * 50)
    app.run(host='0.0.0.0', port=8080, debug=False, threaded=True)