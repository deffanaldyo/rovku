#!/usr/bin/env python3

import subprocess
import time
import logging
import signal
import sys
import os
import socket
import threading
import shutil

# ─── KONFIGURASI ─────────────────────────────────────────

SERIAL_PORTS = ["/dev/ttyACM0", "/dev/ttyACM1"]
BAUDRATE = 115200

UDP_OUTPUTS = [
    "udp:192.168.1.2:14550",   # Laptop QGround
    "udp:192.168.1.255:14550", # Broadcast
    "udp:127.0.0.1:14550",     # Debug lokal
]

RESTART_DELAY = 5
LOG_FILE = "/tmp/mavproxy_connector.log"

HEARTBEAT_PORT = 14550
HEARTBEAT_TIMEOUT = 30

# ─── LOGGING ─────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ]
)

log = logging.getLogger("MAVConnector")

# ─── GLOBAL STATE ────────────────────────────────────────

process = None
running = True
last_heartbeat = None

# ─── SIGNAL HANDLER ─────────────────────────────────────

def shutdown(sig, frame):
    global running, process
    log.info("Shutdown diterima...")
    running = False

    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except:
            process.kill()

    sys.exit(0)

signal.signal(signal.SIGINT, shutdown)
signal.signal(signal.SIGTERM, shutdown)

# ─── SERIAL DETECTION ────────────────────────────────────

def find_serial():
    for port in SERIAL_PORTS:
        if os.path.exists(port):
            return port
    return None

# ─── CEK MAVPROXY (COMPATIBLE PYTHON 3.6) ───────────────

def check_mavproxy():
    path = shutil.which("mavproxy.py")

    if not path:
        log.error("MAVProxy belum terinstall!")
        log.error("Install: pip3 install MAVProxy")
        sys.exit(1)

    log.info("MAVProxy ditemukan: {}".format(path))

# ─── HEARTBEAT MONITOR ──────────────────────────────────

def heartbeat_monitor():
    global last_heartbeat

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", HEARTBEAT_PORT))
    sock.settimeout(1.0)

    log.info("Heartbeat monitor aktif di port {}".format(HEARTBEAT_PORT))

    while running:
        try:
            data, _ = sock.recvfrom(1024)
            if data:
                last_heartbeat = time.time()
        except socket.timeout:
            pass

    sock.close()

# ─── BUILD COMMAND ──────────────────────────────────────

def build_command(port):
    cmd = [
        "mavproxy.py",
        "--master={}".format(port),
        "--baudrate={}".format(BAUDRATE),
    ]

    for out in UDP_OUTPUTS:
        cmd += ["--out", out]

    return cmd

# ─── STATUS ─────────────────────────────────────────────

def print_status(start_time):
    uptime = int(time.time() - start_time)

    if last_heartbeat:
        hb = "{}s ago".format(int(time.time() - last_heartbeat))
    else:
        hb = "NO DATA"

    log.info("[STATUS] uptime={}s | heartbeat={}".format(uptime, hb))

# ─── MAIN LOOP ──────────────────────────────────────────

def main():
    global process

    log.info("=" * 50)
    log.info("MAVProxy Connector START")
    log.info("Jetson → QGroundControl")
    log.info("=" * 50)

    check_mavproxy()

    # start heartbeat thread
    threading.Thread(target=heartbeat_monitor, daemon=True).start()

    while running:

        port = find_serial()

        if not port:
            log.warning("Serial tidak ditemukan, retry...")
            time.sleep(RESTART_DELAY)
            continue

        log.info("Serial ditemukan: {}".format(port))

        cmd = build_command(port)

        log.info("Menjalankan:")
        log.info(" ".join(cmd))

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1
            )

            start_time = time.time()

            for line in process.stdout:
                if line:
                    log.info("[MAVProxy] " + line.strip())

                if not running:
                    break

                # print status tiap 10 detik
                if int(time.time() - start_time) % 10 == 0:
                    print_status(start_time)

            process.wait()
            log.warning("MAVProxy berhenti!")

        except Exception as e:
            log.error("Error: {}".format(e))

        log.info("Restart dalam {} detik...".format(RESTART_DELAY))
        time.sleep(RESTART_DELAY)

# ─── ENTRY POINT ────────────────────────────────────────

if __name__ == "__main__":
    main()
