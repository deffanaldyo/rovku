"""
jetson_forwarder_gpu.py

Versi full-hardware: kamera dibuka SATU KALI lewat v4l2src (hindari konflik
exclusivity device), MJPG didecode di NVJPEG hardware decoder Jetson
(nvv4l2decoder mjpeg=1), color convert di GPU (nvvidconv), lalu di-tee ke
dua cabang:
  1. Recording  -> hardware H264 encoder -> splitmuxsink (auto rotate file,
     finalisasi mp4 otomatis & benar saat EOS)
  2. Streaming  -> hardware H264 encoder -> appsink, lalu di-relay ke
     appsrc milik GstRtspServer (hanya aktif kalau ada client connect)

Tidak ada decode/encode/convert yang lewat CPU sama sekali untuk jalur
video. Python hanya jadi "lem" antara dua pipeline (relay buffer H264).

Usage: python3 jetson_forwarder_gpu.py <IP_ADDRESS> [device]
Contoh: python3 jetson_forwarder_gpu.py 192.168.1.1 /dev/video0
"""

import gi
import os
import sys
import signal

gi.require_version("Gst", "1.0")
gi.require_version("GstRtspServer", "1.0")
from gi.repository import Gst, GstRtspServer, GLib

Gst.init(None)

# ====== Konfigurasi ======
WIDTH, HEIGHT, FPS = 1280, 720, 30
BITRATE = 5_000_000          # 5 Mbps, cocok untuk 720p30
ROTATE_SEC = 3600            # rotasi file recording setiap 1 jam
RTSP_PORT = 8554
RTSP_MOUNT = "/live"

os.makedirs("record", exist_ok=True)

global_appsrc = None         # appsrc milik RTSP factory, diisi saat client connect
main_pipeline = None
loop = None


# ====== Bagian 1: Pipeline utama (kamera -> decode -> tee) ======

def build_main_pipeline(device: str) -> Gst.Pipeline:
    pipeline_str = (
        f"v4l2src device={device} io-mode=2 ! "
        f"image/jpeg,width={WIDTH},height={HEIGHT},framerate={FPS}/1 ! "
        f"nvv4l2decoder mjpeg=1 ! "
        f"nvvidconv ! video/x-raw(memory:NVMM),format=NV12 ! "
        f"tee name=t "
        # --- Cabang recording (hardware encode + auto-rotate + auto-finalize) ---
        f"t. ! queue leaky=downstream max-size-buffers=4 ! "
        f"nvv4l2h264enc bitrate={BITRATE} insert-sps-pps=true "
        f"preset-level=1 maxperf-enable=true iframeinterval={FPS * 2} ! "
        f"h264parse ! "
        f"splitmuxsink name=splitsink location=record/full_%03d.mp4 "
        f"max-size-time={ROTATE_SEC * Gst.SECOND} "
        # --- Cabang streaming (hardware encode, diteruskan ke RTSP via appsink) ---
        f"t. ! queue leaky=downstream max-size-buffers=4 ! "
        f"nvv4l2h264enc bitrate={BITRATE} insert-sps-pps=true "
        f"preset-level=1 maxperf-enable=true iframeinterval={FPS * 2} ! "
        f"h264parse ! "
        f"appsink name=streamsink emit-signals=true max-buffers=2 drop=true sync=false"
    )

    print("[INFO] Pipeline:\n", pipeline_str, "\n")

    try:
        pipeline = Gst.parse_launch(pipeline_str)
    except GLib.Error as e:
        print(f"[FATAL] Gagal parse pipeline: {e}")
        sys.exit(1)

    appsink = pipeline.get_by_name("streamsink")
    appsink.connect("new-sample", on_new_sample)

    bus = pipeline.get_bus()
    bus.add_signal_watch()
    bus.connect("message", on_bus_message)

    return pipeline


def on_new_sample(sink):
    """Tarik buffer H264 hasil encode dan teruskan ke appsrc RTSP kalau ada client."""
    global global_appsrc

    sample = sink.emit("pull-sample")
    if sample is None:
        return Gst.FlowReturn.OK

    if global_appsrc is not None:
        buf = sample.get_buffer()
        global_appsrc.emit("push-buffer", buf)

    return Gst.FlowReturn.OK


def on_bus_message(bus, message):
    global main_pipeline, loop

    t = message.type
    if t == Gst.MessageType.EOS:
        print("[INFO] EOS diterima, file recording sudah difinalisasi.")
        if main_pipeline is not None:
            main_pipeline.set_state(Gst.State.NULL)
        if loop is not None:
            loop.quit()
    elif t == Gst.MessageType.ERROR:
        err, debug = message.parse_error()
        print(f"[ERROR] {err} | debug: {debug}")
        if main_pipeline is not None:
            main_pipeline.set_state(Gst.State.NULL)
        if loop is not None:
            loop.quit()


# ====== Bagian 2: RTSP server (appsrc menerima H264 yang sudah terenkode) ======

class RTSPServer:
    def __init__(self, port=RTSP_PORT):
        self.server = GstRtspServer.RTSPServer()
        self.server.set_service(str(port))

        factory = GstRtspServer.RTSPMediaFactory()
        launch_str = (
            "( appsrc name=mysrc is-live=true format=time do-timestamp=true "
            f"caps=video/x-h264,stream-format=byte-stream,alignment=au,"
            f"width={WIDTH},height={HEIGHT},framerate={FPS}/1 "
            "! h264parse ! rtph264pay pt=96 name=pay0 config-interval=1 )"
        )
        factory.set_launch(launch_str)
        factory.set_shared(True)

        mounts = self.server.get_mount_points()
        mounts.add_factory(RTSP_MOUNT, factory)
        factory.connect("media-configure", self.media_configure)

    def media_configure(self, factory, media):
        global global_appsrc
        global_appsrc = media.get_element().get_child_by_name("mysrc")
        print("[INFO] Client connected ke RTSP stream")

    def attach(self, ip):
        self.server.set_address(ip)
        self.server.attach(None)
        print(f"[INFO] RTSP ready: rtsp://{ip}:{RTSP_PORT}{RTSP_MOUNT}")


# ====== Bagian 3: Shutdown bersih ======

def signal_handler(sig, frame):
    print("\n[INFO] Ctrl+C diterima, mengirim EOS supaya file recording "
          "difinalisasi dengan benar...")
    if main_pipeline is not None:
        main_pipeline.send_event(Gst.Event.new_eos())
    # loop akan di-quit otomatis oleh on_bus_message saat EOS sampai di bus


signal.signal(signal.SIGINT, signal_handler)


# ====== Main ======

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: python3 {sys.argv[0]} <IP_ADDRESS> [device]")
        sys.exit(1)

    target_ip = sys.argv[1]
    device = sys.argv[2] if len(sys.argv) > 2 else "/dev/video0"

    main_pipeline = build_main_pipeline(device)

    ret = main_pipeline.set_state(Gst.State.PLAYING)
    if ret == Gst.StateChangeReturn.FAILURE:
        print("[FATAL] Pipeline gagal masuk state PLAYING. "
              "Cek apakah device kamera benar dan nvv4l2decoder support MJPEG.")
        sys.exit(1)

    print("[INFO] Pipeline kamera jalan (hardware decode + tee record/stream)")

    server = RTSPServer(RTSP_PORT)
    server.attach(target_ip)

    loop = GLib.MainLoop()
    try:
        loop.run()
    except KeyboardInterrupt:
        pass

    print("[INFO] Selesai.")
