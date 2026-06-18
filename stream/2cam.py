import cv2
import gi
import threading
import time
import signal
import sys
import os
from datetime import datetime

gi.require_version('Gst', '1.0')
gi.require_version('GstRtspServer', '1.0')
from gi.repository import Gst, GstRtspServer, GLib

Gst.init(None)

# --- KONFIGURASI ---
W, H, FPS = 1280, 720, 30  # Resolusi per kamera
STITCHED_W = W * 2         # Hasil akhir 2560x720
CAM1_IDX = 0
CAM2_IDX = 2
BITRATE = "4000000"        # 4Mbps karena menangani 2 gambar sekaligus

global_appsrc = None
run = True
loop = None

os.makedirs("record", exist_ok=True)

def create_gpu_writer():
    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"record/dual_cam_{now}.mp4"
    # Pipeline recording untuk frame lebar (2560x720)
    gst_record = (
        f"appsrc ! videoconvert ! video/x-raw,format=I420 ! "
        f"nvvidconv ! video/x-raw(memory:NVMM),format=NV12 ! "
        f"nvv4l2h264enc bitrate={BITRATE} ! h264parse ! mp4mux ! "
        f"filesink location={filename}"
    )
    return cv2.VideoWriter(gst_record, cv2.CAP_GSTREAMER, 0, FPS, (STITCHED_W, H))

def camera_worker():
    global global_appsrc, run
    
    # Inisialisasi Kamera 1 & 2
    cap1 = cv2.VideoCapture(CAM1_IDX, cv2.CAP_V4L2)
    cap2 = cv2.VideoCapture(CAM2_IDX, cv2.CAP_V4L2)
    
    for c in [cap1, cap2]:
        c.set(cv2.CAP_PROP_FRAME_WIDTH, W)
        c.set(cv2.CAP_PROP_FRAME_HEIGHT, H)
        c.set(cv2.CAP_PROP_FPS, FPS)

    if not cap1.isOpened() or not cap2.isOpened():
        print("[ERROR] Salah satu atau kedua kamera tidak terdeteksi!")
        run = False
        return

    writer = create_gpu_writer()
    numframe = 0

    print(f"[INFO] Streaming Dual Camera Start: {STITCHED_W}x{H}")

    while run:
        ret1, frame1 = cap1.read()
        ret2, frame2 = cap2.read()

        if not ret1 or not ret2:
            continue

        # --- PROSES STITCHING (GABUNG KIRI-KANAN) ---
        # frame1 di kiri, frame2 di kanan
        stitched_frame = cv2.hconcat([frame1, frame2])

        # 1. Recording ke Disk
        writer.write(stitched_frame)

        # 2. Kirim ke RTSP Stream
        if global_appsrc is not None:
            data = stitched_frame.tobytes()
            buf = Gst.Buffer.new_allocate(None, len(data), None)
            buf.fill(0, data)
            
            ts = Gst.util_uint64_scale(numframe, Gst.SECOND, FPS)
            buf.pts = ts
            buf.duration = Gst.SECOND // FPS

            global_appsrc.emit("push-buffer", buf)
            numframe += 1
    
    writer.release()
    cap1.release()
    cap2.release()

class StitchedRTSPServer:
    def __init__(self, port=8554):
        self.server = GstRtspServer.RTSPServer()
        self.server.set_service(str(port))
        
        factory = GstRtspServer.RTSPMediaFactory()
        
        # Pipeline disesuaikan dengan STITCHED_W (2560)
        pipeline = (
            f"( appsrc name=mysrc is-live=true format=time do-timestamp=true "
            f"caps=video/x-raw,format=BGR,width={STITCHED_W},height={H},framerate={FPS}/1 "
            f"! videoconvert ! video/x-raw,format=I420 "
            f"! nvvidconv ! video/x-raw(memory:NVMM),format=NV12 "
            f"! nvv4l2h264enc bitrate={BITRATE} insert-sps-pps=true maxperf-enable=true "
            f"! h264parse ! rtph264pay pt=96 name=pay0 config-interval=1 )"
        )
        
        factory.set_launch(pipeline)
        factory.set_shared(True)
        factory.connect("media-configure", self.on_configure)
        
        mounts = self.server.get_mount_points()
        mounts.add_factory("/live", factory)

    def on_configure(self, factory, media):
        global global_appsrc
        global_appsrc = media.get_element().get_child_by_name("mysrc")
        print("[INFO] Client Connected - Streaming Dual Camera")

    def run(self, ip):
        self.server.set_address(ip)
        self.server.attach(None)
        print(f"\n[OK] RTSP Stream Ready: rtsp://{ip}:8554/live")
        global loop
        loop = GLib.MainLoop()
        try:
            loop.run()
        except KeyboardInterrupt:
            pass

def signal_handler(sig, frame):
    global run, loop
    run = False
    if loop:
        loop.quit()
    sys.exit(0)

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: python3 {sys.argv[0]} <IP_ADDRESS>")
        sys.exit(1)

    target_ip = sys.argv[1]
    signal.signal(signal.SIGINT, signal_handler)

    # Jalankan thread kamera
    t = threading.Thread(target=camera_worker, daemon=True)
    t.start()

    # Jalankan RTSP Server
    server = StitchedRTSPServer(8554)
    server.run(target_ip)