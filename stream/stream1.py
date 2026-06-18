import cv2
import gi
import threading
import time
import signal
import sys
import os
from datetime import datetime
from collections import deque

gi.require_version('Gst', '1.0')
gi.require_version('GstRtspServer', '1.0')
from gi.repository import Gst, GstRtspServer, GLib

Gst.init(None)

WIDTH, HEIGHT, FPS = 1280, 720, 30
CAM_INDEX = 0

run = True
appsrc = None
numframe = 0
loop = None

os.makedirs("record", exist_ok=True)

# ---------------- FPS ----------------
class FPSCounter:
    def __init__(self):
        self.count = 0
        self.start = time.time()

    def update(self):
        self.count += 1
        if time.time() - self.start >= 1:
            print(f"[FPS] {self.count}")
            self.count = 0
            self.start = time.time()

fps = FPSCounter()

# ---------------- Recording ----------------
def create_writer():
    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = f"record/cam_{now}.mkv"
    writer = cv2.VideoWriter(
        path,
        cv2.VideoWriter_fourcc(*"MJPG"),
        FPS,
        (WIDTH, HEIGHT)
    )
    print("[REC]", path)
    return writer, time.time()

# ---------------- Camera ----------------
def open_camera():
    cap = cv2.VideoCapture(CAM_INDEX, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
    cap.set(cv2.CAP_PROP_FPS, FPS)
    return cap

def camera_loop():
    global appsrc, run, numframe

    cap = open_camera()
    if not cap.isOpened():
        print("Camera gagal dibuka")
        return

    writer, t0 = create_writer()

    while run:
        ret, frame = cap.read()
        if not ret:
            continue

        # ================= FIX KAMERA TERBALIK =================
        frame = cv2.flip(frame, 0)   # 0 = atas-bawah (ubah ke 1 atau -1 jika perlu)
        # =======================================================

        fps.update()

        # record
        writer.write(frame)

        # RTSP push
        if appsrc:
            data = frame.tobytes()
            buf = Gst.Buffer.new_allocate(None, len(data), None)
            buf.fill(0, data)

            ts = Gst.util_uint64_scale(numframe, Gst.SECOND, FPS)
            buf.pts = buf.dts = ts
            buf.duration = Gst.SECOND // FPS

            appsrc.emit("push-buffer", buf)
            numframe += 1

        # rotate file tiap 1 jam
        if time.time() - t0 > 3600:
            writer.release()
            writer, t0 = create_writer()

    writer.release()

# ---------------- RTSP Server ----------------
class RTSPServer:
    def __init__(self, ip, port=8554):
        self.server = GstRtspServer.RTSPServer()
        self.server.set_service(str(port))

        factory = GstRtspServer.RTSPMediaFactory()
        factory.set_launch(f"""
        ( appsrc name=mysrc is-live=true format=time do-timestamp=true
        caps=video/x-raw,format=BGR,width={WIDTH},height={HEIGHT},framerate={FPS}/1
        ! videoconvert
        ! x264enc tune=zerolatency bitrate=1200 speed-preset=ultrafast
        ! rtph264pay name=pay0 pt=96 )
        """)

        factory.set_shared(True)
        factory.connect("media-configure", self.on_configure)

        self.server.get_mount_points().add_factory("/live", factory)
        self.server.set_address(ip)

    def on_configure(self, factory, media):
        global appsrc, numframe
        appsrc = media.get_element().get_child_by_name("mysrc")
        numframe = 0

    def run(self):
        self.server.attach(None)
        print(f"RTSP: rtsp://{self.server.get_address()}:8554/live")

        global loop
        loop = GLib.MainLoop()
        loop.run()

# ---------------- STOP ----------------
def stop(sig, frame):
    global run, loop
    run = False
    if loop:
        loop.quit()

signal.signal(signal.SIGINT, stop)

# ---------------- MAIN ----------------
if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 app.py <IP>")
        sys.exit(1)

    ip = sys.argv[1]

    threading.Thread(target=camera_loop, daemon=True).start()

    server = RTSPServer(ip)
    server.run()
