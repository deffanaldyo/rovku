import gi
import os
import sys
import signal

gi.require_version("Gst", "1.0")
gi.require_version("GstRtspServer", "1.0")
from gi.repository import Gst, GstRtspServer, GLib

Gst.init(None)

# ====== CONFIG ======
WIDTH, HEIGHT, FPS = 1280, 720, 30
BITRATE = 5_000_000
ROTATE_SEC = 3600
RTSP_PORT = 8554
RTSP_MOUNT = "/live"

os.makedirs("record", exist_ok=True)

global_appsrc = None
main_pipeline = None
loop = None


# ====== MAIN PIPELINE (GPU FULL) ======
def build_main_pipeline(device: str) -> Gst.Pipeline:
    pipeline_str = (
        f"v4l2src device={device} io-mode=2 ! "
        f"queue ! "
        f"image/jpeg,width={WIDTH},height={HEIGHT},framerate={FPS}/1 ! "
        f"jpegparse ! "
        f"nvv4l2decoder mjpeg=1 ! "
        f"nvvidconv ! video/x-raw(memory:NVMM),format=NV12 ! "
        f"tee name=t "

        # ===== RECORD =====
        f"t. ! queue leaky=downstream max-size-buffers=4 ! "
        f"nvv4l2h264enc bitrate={BITRATE} insert-sps-pps=true "
        f"preset-level=1 control-rate=1 maxperf-enable=true iframeinterval=15 ! "
        f"h264parse ! "
        f"splitmuxsink name=splitsink location=record/full_%03d.mp4 "
        f"max-size-time={ROTATE_SEC * Gst.SECOND} "

        # ===== STREAM =====
        f"t. ! queue leaky=downstream max-size-buffers=4 ! "
        f"nvv4l2h264enc bitrate={BITRATE} insert-sps-pps=true "
        f"preset-level=1 control-rate=1 maxperf-enable=true iframeinterval=15 ! "
        f"h264parse ! "
        f"appsink name=streamsink emit-signals=true max-buffers=2 drop=true sync=false"
    )

    print("[INFO] PIPELINE:\n", pipeline_str, "\n")

    pipeline = Gst.parse_launch(pipeline_str)

    appsink = pipeline.get_by_name("streamsink")
    appsink.connect("new-sample", on_new_sample)

    bus = pipeline.get_bus()
    bus.add_signal_watch()
    bus.connect("message", on_bus_message)

    return pipeline


def on_new_sample(sink):
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

    if message.type == Gst.MessageType.ERROR:
        err, debug = message.parse_error()
        print(f"[ERROR] {err} | {debug}")
        main_pipeline.set_state(Gst.State.NULL)
        loop.quit()

    elif message.type == Gst.MessageType.EOS:
        print("[INFO] EOS → file aman (finalized)")
        main_pipeline.set_state(Gst.State.NULL)
        loop.quit()


# ====== RTSP SERVER ======
class RTSPServer:
    def __init__(self, port=RTSP_PORT):
        self.server = GstRtspServer.RTSPServer()
        self.server.set_service(str(port))

        factory = GstRtspServer.RTSPMediaFactory()
        factory.set_shared(True)

        launch_str = (
            "( appsrc name=mysrc is-live=true block=true format=time do-timestamp=true "
            f"caps=video/x-h264,stream-format=byte-stream,alignment=au,"
            f"width={WIDTH},height={HEIGHT},framerate={FPS}/1 "
            "! h264parse ! rtph264pay pt=96 config-interval=1 name=pay0 )"
        )

        factory.set_launch(launch_str)

        mounts = self.server.get_mount_points()
        mounts.add_factory(RTSP_MOUNT, factory)

        factory.connect("media-configure", self.media_configure)

    def media_configure(self, factory, media):
        global global_appsrc
        global_appsrc = media.get_element().get_child_by_name("mysrc")
        print("[INFO] Client RTSP connected")

    def attach(self, ip):
        self.server.set_address(ip)
        self.server.attach(None)
        print(f"[INFO] RTSP READY: rtsp://{ip}:{RTSP_PORT}{RTSP_MOUNT}")


# ====== CLEAN EXIT ======
def signal_handler(sig, frame):
    print("\n[INFO] Ctrl+C → kirim EOS...")
    if main_pipeline:
        main_pipeline.send_event(Gst.Event.new_eos())


signal.signal(signal.SIGINT, signal_handler)


# ====== MAIN ======
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: python3 {sys.argv[0]} <IP> [device]")
        sys.exit(1)

    ip = sys.argv[1]
    device = sys.argv[2] if len(sys.argv) > 2 else "/dev/video0"

    main_pipeline = build_main_pipeline(device)

    if main_pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
        print("[FATAL] Pipeline gagal start")
        sys.exit(1)

    print("[INFO] Kamera jalan (GPU decode + encode aktif)")

    server = RTSPServer()
    server.attach(ip)

    loop = GLib.MainLoop()
    loop.run()

    print("[INFO] Program selesai")
