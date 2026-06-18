#  Streaming & Record
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
camin = 2
global_appsrc = None
run = True
loop = None
os.makedirs("record", exist_ok=True)

BUFF_SEC = 1         # buffer sebelum deteksi
ROTATE_SEC = 3600    # rotate file

class FPSCounter:
    def __init__(self):
        self.count = 0
        self.start = time.time()

    def update(self):
        self.count += 1
        now = time.time()
        if now - self.start >= 1.0:
            print(f"[FPS] {self.count/(now - self.start):.2f}")
            self.count = 0
            self.start = now
fps = FPSCounter()

def create_writer(name):
    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"record/{name}_{now}.mkv"
    fourcc = cv2.VideoWriter_fourcc(*'MJPG')
    writer = cv2.VideoWriter(filename, fourcc, FPS, (WIDTH, HEIGHT))

    if not writer.isOpened():
        print(f"[ERROR] Writer gagal: {filename}")
    else:
        print(f"[INFO] Recording: {filename}")
    return writer, time.time()

def signal_handler(sig, frame):
    global run, loop
    print("\n[INFO] Shutdown...")
    run = False
    if loop:
        loop.quit()

signal.signal(signal.SIGINT, signal_handler)

def open_camera():
    cap = cv2.VideoCapture(camin, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
    cap.set(cv2.CAP_PROP_FPS, FPS)
    return cap

def camera_loop():
    global global_appsrc, run, numframe
    cap = open_camera()

    if not cap.isOpened():
        print("Camera tidak terbuka")
        return

    fwriter, ftime = create_writer("full")
    buffer = deque(maxlen=FPS * BUFF_SEC)
    numframe = 0

    while run:
        ret, frame = cap.read()
        if not ret:
            print("[WARN] Frame drop")
            continue

        fps.update()
        
        fwriter.write(frame)
        buffer.append(frame.copy())

        if time.time() - ftime > ROTATE_SEC:
            fwriter.release()
            fwriter, ftime = create_writer("full")

        if global_appsrc is not None:
            data = frame.tobytes()
            buf = Gst.Buffer.new_allocate(None, len(data), None)
            buf.fill(0, data)

            ts = Gst.util_uint64_scale(numframe, Gst.SECOND, FPS)
            buf.pts = ts
            buf.dts = ts
            buf.duration = Gst.SECOND // FPS

            global_appsrc.emit("push-buffer", buf)
            numframe += 1
    
    fwriter.release()
    print("[INFO] DONE\n");

class RTSPServer:
    def __init__(self, port=8554):
        self.server = GstRtspServer.RTSPServer()
        self.server.set_service(str(port))
        factory = GstRtspServer.RTSPMediaFactory()
        
        # factory.set_launch(
        #     "( appsrc name=mysrc is-live=true format=time do-timestamp=true block=true "
        #     f"caps=video/x-raw,format=BGR,width={WIDTH},height={HEIGHT},framerate={FPS}/1 "
        #     "! queue max-size-buffers=1 leaky=downstream max-size-time=0 max-size-bytes=0 "
        #     "! videoconvert "
        #     "! video/x-raw,format=NV12 "
        #     "! x264enc tune=zerolatency speed-preset=ultrafast bitrate=800 key-int-max=15 "
        #     "bframes=0 byte-stream=true aud=true insert-vui=true "
        #     "! video/x-h264,stream-format=byte-stream,alignment=au,profile=baseline "
        #     "! h264parse config-interval=1 "
        #     "! rtph264pay pt=96 name=pay0 config-interval=1 )"
        # )

        factory.set_launch(
            "( appsrc name=mysrc is-live=true format=time do-timestamp=true block=true "
            f"caps=video/x-raw,format=BGR,width={WIDTH},height={HEIGHT},framerate={FPS}/1 "
            "! queue max-size-buffers=1 leaky=downstream max-size-time=0 max-size-bytes=0 "
            "! videoconvert "
            "! video/x-raw,format=NV12 "
            "! x264enc tune=zerolatency speed-preset=ultrafast bitrate=1200 key-int-max=15 "
            "bframes=0 byte-stream=true aud=true insert-vui=true "
            "! video/x-h264,stream-format=byte-stream,alignment=au,profile=baseline "
            "! h264parse config-interval=1 "
            "! rtph264pay pt=96 name=pay0 config-interval=1 )"
        )

        # factory.set_launch(
        #     "( appsrc name=mysrc is-live=true format=time do-timestamp=true block=true "
        #     f"caps=video/x-raw,format=BGR,width={WIDTH},height={HEIGHT},framerate={FPS}/1 "
        #     "! queue leaky=downstream max-size-buffers=1 "
        #     "! videoconvert "
        #     "! video/x-raw,format=NV12 "
        #     "! x264enc tune=zerolatency speed-preset=ultrafast bitrate=1200 key-int-max=15 bframes=0 "
        #     "! h264parse config-interval=1 "
        #     "! rtph264pay pt=96 name=pay0 config-interval=1 )"
        # ) # Orange Pi 5 Pro & Laptop

        # factory.set_launch(
        #     "( appsrc name=mysrc is-live=true format=time do-timestamp=true block=true "
        #     f"caps=video/x-raw,format=BGR,width={WIDTH},height={HEIGHT},framerate={FPS}/1 "
        #     "! queue leaky=downstream max-size-buffers=1 "
        #     "! videoconvert "
        #     "! video/x-raw,format=NV12 "
        #     "! mpph264enc bps=2000000 gop=10 rc-mode=cbr "
        #     "! h264parse config-interval=1 "
        #     "! rtph264pay pt=96 name=pay0 config-interval=1 )"
        # ) # Orange Pi 5 Pro

        factory.set_shared(True)
        mounts = self.server.get_mount_points()
        mounts.add_factory("/live", factory)
        factory.connect("media-configure", self.media_configure)

    def media_configure(self, factory, media):
        global global_appsrc, numframe
        global_appsrc = media.get_element().get_child_by_name("mysrc")
        numframe = 0 

    def run(self, ip):
        self.server.set_address(ip)
        self.server.attach(None)

        print("\n[INFO] RTSP Stream Ready")
        print(f"rtsp://{ip}:8554/live")

        global loop
        loop = GLib.MainLoop()
        loop.run()

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: python3 {sys.argv[0]} <IP_ADDRESS>")
        sys.exit(1)

    ip = sys.argv[1]
    t = threading.Thread(target=camera_loop, daemon=True)
    t.start()

    server = RTSPServer(8554)
    server.run(ip)
