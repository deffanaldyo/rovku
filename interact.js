// ============================================================
//  ROV Ground Control Station — interact.js
//  Semua rekaman, snapshot, log, trajectory disimpan di LAPTOP
//  Jetson hanya streaming video + telemetry JSON
// ============================================================

// ============================================================
//  ROV Ground Control Station — interact.js
//  Semua rekaman, snapshot, log, trajectory disimpan di LAPTOP
//  Jetson hanya streaming video + telemetry JSON
// ============================================================

const BACKEND_URL = "http://10.205.152.79:8080"; // <-- IP Jetson di jaringan lokal

// ============================================================
// SESSION ID
// Dibuat sekali saat halaman dibuka / setelah RESET SESSION.
// Semua file sesi memakai prefix:  ROV_<SESSION_ID>__*
//
// Contoh struktur di laptop:
//   /ROV - KKI 2026/REPLAY/
//   ├── ROV_2025-06-11_10-26-05__video_CAM1.webm
//   ├── ROV_2025-06-11_10-26-05__video_CAM2.webm
//   ├── ROV_2025-06-11_10-26-05__telemetry.csv
//   ├── ROV_2025-06-11_10-26-05__trajectory.png
//   ├── ROV_2025-06-11_10-26-05__log.txt
//   ├── ROV_2025-06-11_10-26-05__snap_CAM1_10-26-18.jpg
//   └── ROV_2025-06-11_10-26-05__snap_CAM2_10-30-44.jpg
// ============================================================
let SESSION_ID = _makeSessionId();

function _makeSessionId() {
  return new Date().toISOString().slice(0, 19).replace(/[T:]/g, "-");
}

function sesPrefix() {
  return `ROV_${SESSION_ID}`;
}

function nowStamp() {
  return new Date().toISOString().slice(0, 19).replace(/[T:]/g, "-");
}

// ============================================================
// FILE SYSTEM ACCESS API
// Saat GCS pertama dibuka, tampil dialog "Pilih Folder" sekali.
// Pengguna navigasi ke /ROV - KKI 2026/REPLAY/ lalu klik OK.
// Semua file berikutnya langsung tersimpan ke sana tanpa dialog.
//
// Fallback: jika browser tidak support (Firefox) atau pengguna
// menutup dialog, gunakan download biasa ke folder Downloads.
// ============================================================
let _rootDirHandle = null;   // DirectoryFileSystemHandle terpilih
let _fsaSupported  = ("showDirectoryPicker" in window);

/** Minta izin folder — dipanggil otomatis saat halaman load */
async function pickSaveFolder() {
  if (!_fsaSupported) {
    appendLog("[FOLDER] Browser tidak support File System Access API. Pakai Downloads biasa.");
    return false;
  }
  try {
    _rootDirHandle = await window.showDirectoryPicker({
      id:        "rov-replay",
      mode:      "readwrite",
      startIn:   "documents",
    });
    appendLog(`[FOLDER] ✓ Folder dipilih: "${_rootDirHandle.name}" — semua file akan disimpan di sini.`);
    _updateFolderBadge();
    return true;
  } catch (e) {
    if (e.name !== "AbortError") appendLog(`[FOLDER] ✖ Gagal pilih folder: ${e.message}`);
    else appendLog("[FOLDER] Dialog dibatalkan — pakai folder Downloads biasa.");
    return false;
  }
}

/** Simpan Blob ke folder yang sudah dipilih, atau fallback ke <a download> */
async function downloadBlob(blob, filename) {
  if (_rootDirHandle) {
    try {
      // Pastikan permission masih aktif
      const perm = await _rootDirHandle.queryPermission({ mode: "readwrite" });
      if (perm !== "granted") {
        await _rootDirHandle.requestPermission({ mode: "readwrite" });
      }
      const fh     = await _rootDirHandle.getFileHandle(filename, { create: true });
      const writable = await fh.createWritable();
      await writable.write(blob);
      await writable.close();
      return; // sukses — tidak perlu fallback
    } catch (e) {
      appendLog(`[FOLDER] ✖ Gagal tulis ke folder: ${e.message} — fallback ke Downloads.`);
    }
  }
  // Fallback: download biasa
  const url = URL.createObjectURL(blob);
  const a   = document.createElement("a");
  a.href     = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

/** Update badge nama folder di UI (jika modal sudah terbuka) */
function _updateFolderBadge() {
  const badge = document.getElementById("rp-folder-name");
  if (badge) {
    badge.textContent = _rootDirHandle
      ? `📁 ${_rootDirHandle.name}`
      : "📁 Downloads (belum dipilih)";
    badge.style.color = _rootDirHandle ? "#22d3ee" : "#f59e0b";
  }
}

// Minta folder otomatis saat halaman pertama kali dimuat
// (ditunda 800 ms agar UI sudah siap)
setTimeout(async () => {
  if (_fsaSupported) {
    appendLog("[FOLDER] Pilih folder penyimpanan untuk sesi ini...");
    await pickSaveFolder();
  }
}, 800);

// ============================================================
// ELEMEN DOM
// ============================================================
const toggleCam1 = document.getElementById("toggleCam1");
const toggleCam2 = document.getElementById("toggleCam2");
const videoBox1  = document.querySelector(".cam1 .video-box");
const videoBox2  = document.querySelector(".cam2 .video-box");
let camImg1 = null, camImg2 = null;

function setToggleText(toggle, text) {
  const t = toggle.closest(".camera-toggle")?.querySelector(".toggle-text");
  if (t) t.textContent = text;
}

// ============================================================
// 1. KAMERA — STREAM MJPEG
// ============================================================
async function startBackendCamera() {
  try { await fetch(`${BACKEND_URL}/start_cameras`, { method: "POST" }); }
  catch (e) { appendLog(`[CAM] Gagal start kamera: ${e.message}`); }
}
async function stopBackendCamera() {
  try { await fetch(`${BACKEND_URL}/stop_cameras`, { method: "POST" }); }
  catch (e) {}
}

function createStream(videoBox, camId) {
  const old = videoBox.querySelector(".video-stream");
  if (old) old.remove();
  const img = document.createElement("img");
  img.className = "video-stream";
  img.alt       = `CAM ${camId + 1}`;
  img.src       = `${BACKEND_URL}/video_feed/${camId}?t=${Date.now()}`;
  videoBox.prepend(img);
  return img;
}

async function turnCameraOn(id) {
  await startBackendCamera();
  if (id === 0) { camImg1 = createStream(videoBox1, 0); videoBox1.classList.add("camera-on"); setToggleText(toggleCam1, "ON"); }
  if (id === 1) { camImg2 = createStream(videoBox2, 1); videoBox2.classList.add("camera-on"); setToggleText(toggleCam2, "ON"); }
}
async function turnCameraOff(id) {
  if (id === 0) { camImg1?.remove(); camImg1 = null; videoBox1.classList.remove("camera-on"); setToggleText(toggleCam1, "OFF"); }
  if (id === 1) { camImg2?.remove(); camImg2 = null; videoBox2.classList.remove("camera-on"); setToggleText(toggleCam2, "OFF"); }
  if (!toggleCam1.checked && !toggleCam2.checked) await stopBackendCamera();
}

toggleCam1?.addEventListener("change", () => toggleCam1.checked ? turnCameraOn(0) : turnCameraOff(0));
toggleCam2?.addEventListener("change", () => toggleCam2.checked ? turnCameraOn(1) : turnCameraOff(1));

// ============================================================
// 2. CONSOLE LOG
// ============================================================
const consoleEl = document.querySelector(".console");
function appendLog(msg) {
  if (!consoleEl) return;
  const now  = new Date().toLocaleTimeString("id-ID", { hour12: false });
  const line = document.createElement("div");
  line.textContent      = `[${now}] ${msg}`;
  line.style.marginBottom = "2px";
  consoleEl.appendChild(line);
  consoleEl.scrollTop   = consoleEl.scrollHeight;
  while (consoleEl.children.length > 120) consoleEl.removeChild(consoleEl.firstChild);
}

// ============================================================
// 3. TELEMETRY
// ============================================================
const depthEl  = document.querySelector(".telemetry-card:first-child strong");
const rollEl   = document.querySelector(".setpoint p:nth-child(1) b");
const pitchEl  = document.querySelector(".setpoint p:nth-child(2) b");
const yawEl    = document.querySelector(".setpoint p:nth-child(3) b");
const qrTarget = document.querySelector(".qr-result strong");
const qrConf   = document.querySelector(".qr-result p b");
const qrStatus = document.querySelector(".qr-status strong");
const qrTime   = document.querySelector(".qr-time strong");

async function fetchTelemetry() {
  try {
    const res  = await fetch(`${BACKEND_URL}/telemetry`);
    if (!res.ok) return;
    const d = await res.json();

    if (depthEl) depthEl.textContent = `${(d.depth || 0).toFixed(2)} m`;
    if (rollEl)  rollEl.textContent  = Math.round(d.roll  || 0);
    if (pitchEl) pitchEl.textContent = Math.round(d.pitch || 0);
    if (yawEl)   yawEl.textContent   = Math.round(d.yaw   || 0);

    const qr = d.qr_data;
    if (qr) {
      if (qrTarget) qrTarget.textContent = qr.target_id || "-";
      if (qrConf)   qrConf.textContent   = qr.valid ? "98%" : "--%";
      if (qrTime)   qrTime.textContent   = qr.time  || "--:--:--";
      if (qrStatus) qrStatus.innerHTML   = qr.valid
        ? `<i class="fa-solid fa-circle-check"></i> VALID`
        : `<i class="fa-solid fa-circle-xmark"></i> NOT FOUND`;
    }

    const posValid = d.pos_valid === true;
    const tx = posValid ? (d.x || 0) : (d.dr_x || 0);
    const ty = posValid ? (d.y || 0) : (d.dr_y || 0);
    const td = (d.depth_pressure && d.depth_pressure > 0.05) ? d.depth_pressure : (d.depth || 0);
    recordTrajPoint(tx, ty, td, d.yaw || 0, posValid);

    // Rekam baris CSV kalau sedang recording
    if (isRecording) {
      csvRows.push([
        new Date().toISOString(),
        (d.roll||0).toFixed(4), (d.pitch||0).toFixed(4), (d.yaw||0).toFixed(4),
        (d.depth||0).toFixed(4), (d.depth_pressure||0).toFixed(4),
        (d.x||0).toFixed(4), (d.y||0).toFixed(4), (d.z||0).toFixed(4),
        (d.dr_x||0).toFixed(4), (d.dr_y||0).toFixed(4)
      ]);
    }

    appendLog(
      `${posValid ? "NED" : "DR"} X:${tx.toFixed(2)} Y:${ty.toFixed(2)} | ` +
      `DEPTH:${td.toFixed(2)}m | YAW:${(d.yaw||0).toFixed(1)}°`
    );
  } catch (_) {}
}
setInterval(fetchTelemetry, 100);

// ============================================================
// 4. SNAPSHOT — AMBIL JPEG DARI JETSON, DOWNLOAD KE LAPTOP
// ============================================================
async function takeSnapshot(camId, label) {
  // Nama file: ROV_<SESSION_ID>__snap_CAM1_<waktu>.jpg
  const timeTag = new Date().toTimeString().slice(0,8).replace(/:/g,"-");
  const fname   = `${sesPrefix()}__snap_${label}_${timeTag}.jpg`;
  try {
    const res = await fetch(`${BACKEND_URL}/snapshot/${camId}`);
    if (!res.ok) { appendLog(`[SNAP] Kamera ${label} tidak tersedia`); return; }
    const blob = await res.blob();
    downloadBlob(blob, fname);
    appendLog(`[SNAP] Downloads: ${fname}`);
  } catch (e) {
    // Fallback: capture dari <img> stream via canvas
    const img = (camId === 0 ? videoBox1 : videoBox2).querySelector(".video-stream");
    if (!img) { appendLog(`[SNAP] Tidak ada stream ${label}`); return; }
    const c = document.createElement("canvas");
    c.width  = img.naturalWidth  || 640;
    c.height = img.naturalHeight || 480;
    c.getContext("2d").drawImage(img, 0, 0);
    c.toBlob(b => { downloadBlob(b, fname); }, "image/jpeg", 0.95);
    appendLog(`[SNAP] Canvas fallback → Downloads: ${fname}`);
  }
}

// Tombol capture per kamera
document.querySelector(".cam1 .capture-btn")?.addEventListener("click", () => takeSnapshot(0, "CAM1"));
document.querySelector(".cam2 .capture-btn")?.addEventListener("click", () => takeSnapshot(1, "CAM2"));

// Tombol SNAPSHOT (ambil kedua kamera sekaligus)
document.querySelector(".btn.snapshot")?.addEventListener("click", () => {
  takeSnapshot(0, "CAM1");
  takeSnapshot(1, "CAM2");
});

// ============================================================
// 5. REKAM VIDEO DI LAPTOP (MediaRecorder via canvas)
// ============================================================
let isRecording    = false;
let mediaRecorders = [];  // [{ recorder, chunks }] per kamera
let csvRows        = [];  // baris telemetry selama rekam
let recStartTime   = null;

const btnRecord = document.querySelector(".btn.record");

function _canvasRecorderFor(videoBox) {
  const img = videoBox.querySelector(".video-stream");
  if (!img) return null;

  const canvas = document.createElement("canvas");
  canvas.width  = 640; canvas.height = 480;
  const ctx = canvas.getContext("2d");

  // Draw loop: salin frame dari <img> ke canvas agar MediaRecorder bisa capture
  let running = true;
  function draw() {
    if (!running) return;
    try { ctx.drawImage(img, 0, 0, 640, 480); } catch (_) {}
    requestAnimationFrame(draw);
  }
  draw();

  const stream  = canvas.captureStream(25); // 25 fps
  const options = MediaRecorder.isTypeSupported("video/webm;codecs=vp9")
    ? { mimeType: "video/webm;codecs=vp9" }
    : MediaRecorder.isTypeSupported("video/webm")
      ? { mimeType: "video/webm" }
      : {};

  const rec    = new MediaRecorder(stream, options);
  const chunks = [];
  rec.ondataavailable = e => { if (e.data.size > 0) chunks.push(e.data); };
  return { rec, chunks, stop: () => { running = false; } };
}

async function startRecording() {
  if (isRecording) return;
  mediaRecorders = [];
  csvRows = [
    ["timestamp","roll","pitch","yaw","depth","depth_pressure","ned_x","ned_y","ned_z","dr_x","dr_y"]
  ];
  recStartTime = new Date();

  const cams = [
    { box: videoBox1, label: "CAM1" },
    { box: videoBox2, label: "CAM2" },
  ];

  for (const cam of cams) {
    const r = _canvasRecorderFor(cam.box);
    if (!r) { appendLog(`[REC] Stream ${cam.label} tidak aktif, dilewati.`); continue; }
    r.label = cam.label;
    r.rec.start(1000); // kumpulkan chunk tiap 1 detik
    mediaRecorders.push(r);
  }

  if (mediaRecorders.length === 0) {
    appendLog("[REC] ⚠ Tidak ada kamera aktif — hanya merekam telemetry & trajectory.");
  }

  isRecording = true;
  if (btnRecord) {
    btnRecord.innerHTML = `<i class="fa-solid fa-stop"></i> STOP RECORD`;
    btnRecord.classList.add("recording-active");
  }
  appendLog(`[REC] ● Rekaman dimulai — ${mediaRecorders.length} kamera aktif`);
}

// stopRecording() digantikan sepenuhnya oleh stopRecordingWithReplay() di section 8.
// toggleRecord dan listener dipindah ke section 8 (pakai stopRecordingWithReplay)

// ============================================================
// 6. SIMPAN TRAJECTORY SEBAGAI PNG
// ============================================================

/** Ambil blob PNG trajectory tanpa langsung download (untuk replay data) */
function _getTrajectoryBlob() {
  return new Promise(res => {
    if (!trajCanvas) { res(null); return; }
    trajCanvas.toBlob(b => res(b), "image/png");
  });
}

/** Ambil blob lalu download — untuk tombol PNG manual di canvas */
function saveTrajectoryImage(label) {
  if (!trajCanvas) return;
  const tag   = label || nowStamp();
  const fname = `${sesPrefix()}__trajectory_${tag}.png`;
  _getTrajectoryBlob().then(blob => {
    if (!blob) return;
    downloadBlob(blob, fname);
    appendLog(`[TRAJ] Downloads: ${fname}`);
  });
}

// ============================================================
// 7. RESET SESSION
// ============================================================
function resetSession() {
  if (isRecording) stopRecordingWithReplay();
  SESSION_ID = _makeSessionId();
  clearTrajectory();
  csvRows = [];
  replayData = null;
  _setReplayBtnReady(false);
  if (consoleEl) consoleEl.innerHTML = "";
  const folderInfo = _rootDirHandle ? `"${_rootDirHandle.name}"` : "Downloads";
  appendLog(`[SYS] Sesi baru: ROV_${SESSION_ID}__*  →  ${folderInfo}`);
}
document.querySelector(".btn.reset")?.addEventListener("click", resetSession);

// ============================================================
// 8. REPLAY SYSTEM — rekam + putar ulang video, traj, log
// ============================================================

// ---- State replay ----
// Setelah stopRecording(), data replay tersimpan di sini:
let replayData = null;
// {
//   sessionId    : string,
//   videoBlobCam1: Blob | null,
//   videoBlobCam2: Blob | null,
//   csvRows      : string[][],          // baris header + data
//   trajSnapBlob : Blob | null,         // PNG trajectory saat stop
//   trajPoints   : {x,y,depth,yaw,t}[],// semua waypoint
//   logLines     : string[],            // teks log
//   duration     : number,              // ms
// }

let _replayAnim  = null;   // requestAnimationFrame handle
let _replayPaused = false;
let _replayStartWall = null;
let _replayElapsed   = 0;  // ms sudah diputar (saat di-pause)

// ---- Simpan snapshot trajectory + finalize replay data ----
function _finalizeReplayData(videoBlobs) {
  // Ambil snapshot canvas trajectory ke Blob (pakai helper terpusat)
  _getTrajectoryBlob().then(tBlob => {
    const logLines = consoleEl
      ? [...consoleEl.children].map(el => el.textContent)
      : [];

    replayData = {
      sessionId    : SESSION_ID,
      videoBlobCam1: videoBlobs[0] || null,
      videoBlobCam2: videoBlobs[1] || null,
      csvRows      : csvRows.slice(),
      trajSnapBlob : tBlob,
      trajPoints   : trajPoints.slice(),
      logLines,
      duration     : Date.now() - (recStartTime ? recStartTime.getTime() : Date.now()),
    };
    appendLog(`[REC] ✓ Replay data siap — durasi ${_fmtMs(replayData.duration)}`);
    // Update tombol REPLAY supaya menyala
    _setReplayBtnReady(true);
  });
}

function _fmtMs(ms) {
  const s = Math.floor(ms / 1000);
  const m = Math.floor(s / 60);
  return `${String(m).padStart(2,"0")}:${String(s % 60).padStart(2,"0")}`;
}

function _setReplayBtnReady(ready) {
  const btn = document.querySelector(".btn.replay");
  if (!btn) return;
  if (ready) {
    btn.style.borderColor = "#22d3ee";
    btn.style.color       = "#22d3ee";
    btn.title = "Putar replay sesi terakhir";
  } else {
    btn.style.borderColor = "";
    btn.style.color       = "";
    btn.title = "";
  }
}

function stopRecordingWithReplay() {
  if (!isRecording) return;
  isRecording = false;

  const pre      = sesPrefix();
  const videoBlobs = [null, null]; // [cam1, cam2]
  let   pending  = 0;

  function tryFinalize() {
    if (pending > 0) return;
    _finalizeReplayData(videoBlobs);
  }

  mediaRecorders.forEach((r, idx) => {
    pending++;
    r.rec.onstop = () => {
      r.stop();
      const blob = new Blob(r.chunks, { type: r.rec.mimeType || "video/webm" });
      const ext  = (r.rec.mimeType || "").includes("mp4") ? "mp4" : "webm";
      const fname = `${pre}__video_${r.label}.${ext}`;
      // Simpan ke disk
      downloadBlob(blob, fname);
      appendLog(`[REC] Downloads: ${fname} (${(blob.size/1024/1024).toFixed(1)} MB)`);
      // Simpan ke memori untuk replay
      if (r.label === "CAM1") videoBlobs[0] = blob;
      if (r.label === "CAM2") videoBlobs[1] = blob;
      pending--;
      tryFinalize();
    };
    r.rec.stop();
  });

  if (pending === 0) tryFinalize(); // tidak ada kamera aktif

  // Simpan CSV
  if (csvRows.length > 1) {
    const csv   = csvRows.map(row => row.join(",")).join("\n");
    const blob  = new Blob([csv], { type: "text/csv" });
    downloadBlob(blob, `${pre}__telemetry.csv`);
    appendLog(`[REC] Downloads: ${pre}__telemetry.csv (${csvRows.length - 1} baris)`);
  }

  // Trajectory PNG TIDAK di-download di sini —
  // sudah tersimpan di replayData.trajSnapBlob dan bisa di-export dari modal Replay.

  mediaRecorders = [];
  if (btnRecord) {
    btnRecord.innerHTML = `<i class="fa-solid fa-circle"></i> START RECORD`;
    btnRecord.classList.remove("recording-active");
  }
  appendLog(`[REC] ■ Rekaman selesai.`);
}

// Satu-satunya handler untuk tombol START / STOP RECORD
function toggleRecord() {
  isRecording ? stopRecordingWithReplay() : startRecording();
}
btnRecord?.addEventListener("click", toggleRecord);

// ============================================================
// 8b. REPLAY MODAL — putar ulang video + trajectory + log
// ============================================================
function openReplayModal() {
  // Jika belum ada data, tampilkan info + pilih folder
  _injectReplayStyles();
  const ex = document.getElementById("rov-replay-modal");
  if (ex) { ex.remove(); }

  const hasReplay = !!replayData;

  const modal = document.createElement("div");
  modal.id = "rov-replay-modal";

  // Buat URL object video sementara
  const url1 = (hasReplay && replayData.videoBlobCam1) ? URL.createObjectURL(replayData.videoBlobCam1) : null;
  const url2 = (hasReplay && replayData.videoBlobCam2) ? URL.createObjectURL(replayData.videoBlobCam2) : null;
  const trajURL = (hasReplay && replayData.trajSnapBlob) ? URL.createObjectURL(replayData.trajSnapBlob) : null;

  const dur     = hasReplay ? replayData.duration : 0;
  const durStr  = _fmtMs(dur);
  const logCount = hasReplay ? replayData.logLines.length : 0;
  const csvCount = hasReplay ? Math.max(0, replayData.csvRows.length - 1) : 0;
  const ptCount  = hasReplay ? replayData.trajPoints.length : 0;

  modal.innerHTML = `
    <div class="rp-overlay" id="rp-overlay"></div>
    <div class="rp-box rp-wide">
      <!-- HEADER -->
      <div class="rp-header">
        <span><i class="fa-solid fa-video"></i> REPLAY — ${hasReplay ? replayData.sessionId : "—"}</span>
        <button id="rp-close"><i class="fa-solid fa-xmark"></i></button>
      </div>

      ${!hasReplay ? `
        <div class="rp-no-data">
          <i class="fa-solid fa-circle-info"></i>
          Belum ada sesi yang direkam.<br>
          Tekan <b>START RECORD</b> di panel Controls untuk mulai merekam.
        </div>
      ` : `
        <!-- STAT ROW -->
        <div class="rp-stat-row">
          <div class="rp-stat"><span>DURASI</span><b>${durStr}</b></div>
          <div class="rp-stat"><span>LOG LINES</span><b>${logCount}</b></div>
          <div class="rp-stat"><span>TELEM ROWS</span><b>${csvCount}</b></div>
          <div class="rp-stat"><span>TRAJ PTS</span><b>${ptCount}</b></div>
        </div>

        <!-- VIDEO PLAYERS -->
        <div class="rp-video-row">
          ${url1 ? `<div class="rp-vid-wrap"><span>CAM 1</span><video id="rv-cam1" src="${url1}" preload="auto"></video></div>` : `<div class="rp-vid-wrap rp-no-cam"><i class="fa-solid fa-video-slash"></i><span>CAM 1 tidak direkam</span></div>`}
          ${url2 ? `<div class="rp-vid-wrap"><span>CAM 2</span><video id="rv-cam2" src="${url2}" preload="auto"></video></div>` : `<div class="rp-vid-wrap rp-no-cam"><i class="fa-solid fa-video-slash"></i><span>CAM 2 tidak direkam</span></div>`}
        </div>

        <!-- TRAJECTORY SNAPSHOT -->
        ${trajURL ? `
          <div class="rp-traj-row">
            <span class="rp-sect-lbl"><i class="fa-solid fa-map"></i> TRAJECTORY SNAPSHOT</span>
            <img id="rv-traj-img" src="${trajURL}" alt="Trajectory" />
          </div>
        ` : ""}

        <!-- LOG CONSOLE -->
        <div class="rp-log-section">
          <span class="rp-sect-lbl"><i class="fa-solid fa-terminal"></i> LOG REPLAY
            <em id="rv-log-idx" style="color:#22d3ee;font-style:normal;margin-left:8px;">0 / ${logCount}</em>
          </span>
          <div class="rp-log-console" id="rv-log-console"></div>
        </div>

        <!-- CONTROLS -->
        <div class="rp-ctrl-bar">
          <button id="rv-back"  title="Ke awal"><i class="fa-solid fa-backward-step"></i></button>
          <button id="rv-play" class="rv-play-btn" title="Putar"><i class="fa-solid fa-play"></i></button>
          <button id="rv-pause" title="Jeda"><i class="fa-solid fa-pause"></i></button>
          <button id="rv-fwd"  title="Ke akhir"><i class="fa-solid fa-forward-step"></i></button>
          <span id="rv-time" class="rv-time">00:00 / ${durStr}</span>
        </div>

        <!-- PROGRESS -->
        <div class="rp-progress-row">
          <input type="range" id="rv-seek" min="0" max="${dur}" value="0" step="100" />
        </div>

        <!-- EXPORT -->
        <div class="rp-export-row">
          <button id="rp-dl-csv"><i class="fa-solid fa-table"></i> CSV Telemetry</button>
          <button id="rp-dl-log"><i class="fa-solid fa-scroll"></i> Log TXT</button>
          <button id="rp-dl-traj"><i class="fa-solid fa-map"></i> Trajectory PNG</button>
        </div>
      `}

      <!-- FOLDER -->
      <div class="rp-folder-row">
        <div class="rp-folder-info">
          <span class="rp-folder-label">FOLDER SIMPAN</span>
          <span id="rp-folder-name" style="color:${_rootDirHandle ? '#22d3ee' : '#f59e0b'}">
            ${_rootDirHandle ? `📁 ${_rootDirHandle.name}` : '📁 Downloads (belum dipilih)'}
          </span>
        </div>
        <button id="rp-pick-folder"><i class="fa-solid fa-folder-open"></i> ${_rootDirHandle ? "Ganti" : "Pilih Folder"}</button>
      </div>
    </div>`;

  document.body.appendChild(modal);

  // ---- Close ----
  const close = () => {
    _stopReplayPlayback();
    modal.remove();
    if (url1) URL.revokeObjectURL(url1);
    if (url2) URL.revokeObjectURL(url2);
    if (trajURL) URL.revokeObjectURL(trajURL);
  };
  document.getElementById("rp-close").onclick   = close;
  document.getElementById("rp-overlay").onclick = close;

  // ---- Folder picker ----
  document.getElementById("rp-pick-folder").onclick = async () => {
    await pickSaveFolder();
    close();
    openReplayModal();
  };

  if (!hasReplay) return;

  // ---- Export buttons ----
  document.getElementById("rp-dl-csv").onclick = () => {
    if (csvCount === 0) { appendLog("[CSV] Tidak ada data."); return; }
    const blob = new Blob([replayData.csvRows.map(r => r.join(",")).join("\n")], { type: "text/csv" });
    downloadBlob(blob, `ROV_${replayData.sessionId}__telemetry.csv`);
    appendLog(`[CSV] Downloads: ROV_${replayData.sessionId}__telemetry.csv`);
  };
  document.getElementById("rp-dl-log").onclick = () => {
    const blob = new Blob([replayData.logLines.join("\n")], { type: "text/plain" });
    downloadBlob(blob, `ROV_${replayData.sessionId}__log.txt`);
    appendLog(`[LOG] Downloads: ROV_${replayData.sessionId}__log.txt`);
  };
  document.getElementById("rp-dl-traj").onclick = () => {
    if (!replayData.trajSnapBlob) { appendLog("[TRAJ] Tidak ada snapshot."); return; }
    downloadBlob(replayData.trajSnapBlob, `ROV_${replayData.sessionId}__trajectory.png`);
    appendLog(`[TRAJ] Downloads: ROV_${replayData.sessionId}__trajectory.png`);
  };

  // ---- Playback ----
  const vidCam1   = document.getElementById("rv-cam1");
  const vidCam2   = document.getElementById("rv-cam2");
  const seekEl    = document.getElementById("rv-seek");
  const timeEl    = document.getElementById("rv-time");
  const logConsole = document.getElementById("rv-log-console");
  const logIdxEl  = document.getElementById("rv-log-idx");

  const data = replayData;

  function _syncUI(elapsedMs) {
    const clampedMs = Math.min(elapsedMs, dur);

    // Sinkron video
    if (vidCam1) vidCam1.currentTime = clampedMs / 1000;
    if (vidCam2) vidCam2.currentTime = clampedMs / 1000;

    // Sinkron seekbar
    if (seekEl) seekEl.value = clampedMs;

    // Sinkron waktu
    if (timeEl) timeEl.textContent = `${_fmtMs(clampedMs)} / ${durStr}`;

    // Sinkron log — tampilkan semua log s.d. waktu elapsed
    // Setiap log line punya timestamp wall-clock, kita perkirakan dari indeks relatif
    if (logConsole && logIdxEl) {
      const ratio    = clampedMs / Math.max(dur, 1);
      const showUpTo = Math.round(ratio * data.logLines.length);
      logConsole.innerHTML = "";
      for (let i = 0; i < showUpTo; i++) {
        const d = document.createElement("div");
        d.textContent = data.logLines[i];
        logConsole.appendChild(d);
      }
      logConsole.scrollTop = logConsole.scrollHeight;
      logIdxEl.textContent = `${showUpTo} / ${data.logLines.length}`;
    }
  }

  function _startReplayPlayback() {
    _stopReplayPlayback();
    _replayPaused = false;
    _replayStartWall = performance.now() - _replayElapsed;

    if (vidCam1) { vidCam1.currentTime = _replayElapsed / 1000; vidCam1.play().catch(() => {}); }
    if (vidCam2) { vidCam2.currentTime = _replayElapsed / 1000; vidCam2.play().catch(() => {}); }

    function tick() {
      if (_replayPaused) return;
      const elapsed = performance.now() - _replayStartWall;
      _syncUI(elapsed);
      if (elapsed >= dur) {
        _replayElapsed = 0;
        if (vidCam1) { vidCam1.pause(); vidCam1.currentTime = 0; }
        if (vidCam2) { vidCam2.pause(); vidCam2.currentTime = 0; }
        seekEl && (seekEl.value = 0);
        timeEl && (timeEl.textContent = `00:00 / ${durStr}`);
        // Reset ikon tombol play
        const playBtn = document.getElementById("rv-play");
        if (playBtn) playBtn.innerHTML = `<i class="fa-solid fa-play"></i>`;
        _replayPaused = true;
        return; // stop loop
      }
      _replayAnim = requestAnimationFrame(tick);
    }
    _replayAnim = requestAnimationFrame(tick);
  }

  function _pauseReplayPlayback() {
    _replayPaused = true;
    _replayElapsed = performance.now() - _replayStartWall;
    if (_replayAnim) cancelAnimationFrame(_replayAnim);
    if (vidCam1) vidCam1.pause();
    if (vidCam2) vidCam2.pause();
  }

  document.getElementById("rv-play").onclick  = _startReplayPlayback;
  document.getElementById("rv-pause").onclick = _pauseReplayPlayback;

  document.getElementById("rv-back").onclick = () => {
    _pauseReplayPlayback();
    _replayElapsed = 0;
    _syncUI(0);
  };
  document.getElementById("rv-fwd").onclick = () => {
    _pauseReplayPlayback();
    _replayElapsed = dur;
    _syncUI(dur);
  };

  // Seekbar drag
  seekEl?.addEventListener("input", () => {
    _pauseReplayPlayback();
    _replayElapsed = Number(seekEl.value);
    _syncUI(_replayElapsed);
  });

  // Inisialisasi tampilan ke t=0
  _syncUI(0);
}

// Hentikan animasi replay (jika modal ditutup)
function _stopReplayPlayback() {
  _replayPaused = true;
  if (_replayAnim) { cancelAnimationFrame(_replayAnim); _replayAnim = null; }
}

// Seekbar di panel luar (replay-panel .progress input) — sync ke modal jika terbuka
document.querySelector(".replay-panel .progress input[type=range]")?.addEventListener("input", function () {
  const modal = document.getElementById("rov-replay-modal");
  if (!modal || !replayData) return;
  const seekEl = document.getElementById("rv-seek");
  if (!seekEl) return;
  const ratio = Number(this.value) / 100;
  const ms = Math.round(ratio * replayData.duration);
  seekEl.value = ms;
  seekEl.dispatchEvent(new Event("input"));
});

// ---- Button bindings ----
// Tombol REPLAY di panel Controls → buka modal
document.querySelector(".btn.replay")?.addEventListener("click", openReplayModal);
// Tombol media di panel Replay Controls → buka modal (kontrol detail ada di dalam modal)
document.querySelectorAll(".replay-panel .media-controls button")
  .forEach(b => b.addEventListener("click", openReplayModal));

// ============================================================
// 8c. INJECT STYLES — recording + replay modal
// ============================================================
function _injectReplayStyles() {
  if (document.getElementById("rp-styles")) return;
  const st = document.createElement("style");
  st.id = "rp-styles";
  st.textContent = `
    /* ---- MODAL WRAPPER ---- */
    #rov-replay-modal {
      position:fixed;inset:0;z-index:9999;display:flex;
      align-items:center;justify-content:center;
    }
    .rp-overlay {
      position:absolute;inset:0;
      background:rgba(1,8,18,0.88);backdrop-filter:blur(5px);
    }
    .rp-box {
      position:relative;z-index:1;
      width:min(540px,96vw);max-height:92vh;overflow-y:auto;
      background:linear-gradient(135deg,#060d1c,#0a1726);
      border:1px solid rgba(34,211,238,0.28);border-radius:14px;
      padding:18px;color:#e5f7ff;font-family:"Segoe UI",Arial,sans-serif;
      scrollbar-width:thin;
    }
    .rp-wide { width:min(820px,97vw); }

    /* ---- HEADER ---- */
    .rp-header {
      display:flex;justify-content:space-between;align-items:center;
      margin-bottom:12px;font-size:13px;font-weight:700;
      color:#22d3ee;letter-spacing:2px;
    }
    #rp-close {
      background:none;border:1px solid rgba(239,68,68,0.4);color:#ef4444;
      border-radius:6px;width:28px;height:28px;cursor:pointer;font-size:14px;
    }
    #rp-close:hover { background:rgba(239,68,68,0.18); }

    /* ---- NO DATA ---- */
    .rp-no-data {
      text-align:center;padding:30px;font-size:13px;color:#64748b;line-height:2;
    }
    .rp-no-data i { font-size:28px;color:#22d3ee;display:block;margin-bottom:10px; }
    .rp-no-data b { color:#e5f7ff; }

    /* ---- STAT ROW ---- */
    .rp-stat-row {
      display:flex;gap:8px;margin-bottom:12px;
    }
    .rp-stat {
      flex:1;background:rgba(14,23,42,0.8);border:1px solid rgba(34,211,238,0.18);
      border-radius:8px;padding:7px 10px;display:flex;flex-direction:column;gap:2px;
      align-items:center;
    }
    .rp-stat span { font-size:9px;color:#64748b;letter-spacing:1px;font-weight:700; }
    .rp-stat b    { font-size:15px;color:#22d3ee;font-family:Consolas,monospace; }

    /* ---- VIDEO ROW ---- */
    .rp-video-row {
      display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px;
    }
    .rp-vid-wrap {
      display:flex;flex-direction:column;gap:5px;
    }
    .rp-vid-wrap span {
      font-size:10px;color:#94a3b8;letter-spacing:1.5px;font-weight:700;
    }
    .rp-vid-wrap video {
      width:100%;border-radius:8px;border:1px solid rgba(34,211,238,0.2);
      background:#000;max-height:200px;object-fit:contain;
    }
    .rp-no-cam {
      background:rgba(14,23,42,0.6);border:1px solid rgba(34,211,238,0.12);
      border-radius:8px;align-items:center;justify-content:center;
      min-height:100px;gap:8px;color:#475569;font-size:11px;
    }
    .rp-no-cam i { font-size:24px; }

    /* ---- TRAJECTORY SNAPSHOT ---- */
    .rp-traj-row {
      display:flex;flex-direction:column;gap:5px;margin-bottom:10px;
    }
    .rp-traj-row img {
      width:100%;max-height:160px;object-fit:contain;
      border:1px solid rgba(34,211,238,0.2);border-radius:8px;background:#010812;
    }

    /* ---- LOG SECTION ---- */
    .rp-sect-lbl {
      font-size:10px;color:#94a3b8;letter-spacing:1.5px;font-weight:700;
      display:block;margin-bottom:5px;
    }
    .rp-log-section { margin-bottom:10px; }
    .rp-log-console {
      height:90px;overflow-y:auto;
      background:rgba(1,8,18,0.9);border:1px solid rgba(34,211,238,0.15);
      border-radius:7px;padding:6px 8px;
      font-size:10px;font-family:Consolas,monospace;color:#94a3b8;
      scrollbar-width:thin;
    }
    .rp-log-console div { margin-bottom:1px; }

    /* ---- CONTROLS ---- */
    .rp-ctrl-bar {
      display:flex;align-items:center;gap:8px;margin-bottom:8px;
    }
    .rp-ctrl-bar button {
      background:rgba(14,23,42,0.8);border:1px solid rgba(34,211,238,0.25);
      color:#22d3ee;border-radius:7px;width:34px;height:34px;cursor:pointer;font-size:14px;
      display:flex;align-items:center;justify-content:center;transition:background .15s;
    }
    .rp-ctrl-bar button:hover { background:rgba(34,211,238,0.15); }
    .rv-play-btn {
      background:rgba(34,211,238,0.12)!important;
      border-color:#22d3ee!important;
    }
    .rv-time {
      margin-left:auto;font-size:11px;font-family:Consolas,monospace;color:#22d3ee;
    }

    /* ---- SEEKBAR ---- */
    .rp-progress-row { margin-bottom:12px; }
    .rp-progress-row input[type=range] {
      width:100%;accent-color:#22d3ee;cursor:pointer;height:4px;
    }

    /* ---- EXPORT ROW ---- */
    .rp-export-row {
      display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap;
    }
    .rp-export-row button {
      flex:1;min-width:120px;padding:8px 10px;border-radius:8px;cursor:pointer;
      font-size:11px;font-weight:600;
      background:rgba(34,211,238,0.07);border:1px solid rgba(34,211,238,0.22);
      color:#22d3ee;display:flex;align-items:center;gap:7px;transition:background .15s;
    }
    .rp-export-row button:hover { background:rgba(34,211,238,0.18); }

    /* ---- FOLDER ROW ---- */
    .rp-folder-row {
      display:flex;align-items:center;justify-content:space-between;gap:10px;
      background:rgba(15,25,45,0.8);border:1px solid rgba(34,211,238,0.2);
      border-radius:9px;padding:9px 13px;
    }
    .rp-folder-info { display:flex;flex-direction:column;gap:3px;min-width:0; }
    .rp-folder-label { font-size:9px;color:#475569;letter-spacing:1.5px;font-weight:700; }
    #rp-folder-name {
      font-size:11px;font-family:Consolas,monospace;
      white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:280px;
    }
    #rp-pick-folder {
      flex-shrink:0;padding:7px 12px;border-radius:7px;cursor:pointer;
      font-size:11px;font-weight:700;white-space:nowrap;
      background:rgba(34,211,238,0.1);border:1px solid rgba(34,211,238,0.3);color:#22d3ee;
    }
    #rp-pick-folder:hover { background:rgba(34,211,238,0.22); }

    /* ---- RECORD BUTTON ACTIVE ---- */
    .btn.record.recording-active {
      background:rgba(239,68,68,0.18)!important;
      border-color:#ef4444!important;color:#ef4444!important;
      animation:recPulse 1s infinite;
    }
    @keyframes recPulse {
      0%,100%{box-shadow:0 0 0 0 rgba(239,68,68,0.4)}
      50%{box-shadow:0 0 0 6px rgba(239,68,68,0)}
    }
  `;
  document.head.appendChild(st);
}
// Inject styles langsung saat load
_injectReplayStyles();

// ============================================================
// 9. FULLSCREEN
// ============================================================
function toggleFullscreen(box) {
  if (!document.fullscreenElement) box.requestFullscreen().catch(()=>{});
  else document.exitFullscreen();
}
document.querySelector(".cam1 .fullscreen-btn")?.addEventListener("click", () => toggleFullscreen(videoBox1));
document.querySelector(".cam2 .fullscreen-btn")?.addEventListener("click", () => toggleFullscreen(videoBox2));

// ============================================================
// 10. TRAJECTORY MODULE
// ============================================================
const TRAJ_MAX    = 500;
const TRAJ_TAIL   = 80;
const DEPTH_WARN  = 2.5;
const MIN_MOVE_NED = 0.05;
const MIN_MOVE_DR  = 0.015;

let trajPoints  = [];
let trajStartX  = null, trajStartY = null;
let trajCanvas  = null, trajCtx = null;
let trajPaused  = false;
let trajPosMode = "WAITING";

let _liveYaw = 0, _liveDepth = 0, _livePosValid = false;
let _drX = 0, _drY = 0, _drLastYaw = null, _drLastT = null;

function _drawCompass(ctx, W, H) {
  const yr = (_liveYaw * Math.PI) / 180;
  const cx = W - 24, cy = 24, r = 16;
  ctx.save();
  ctx.beginPath(); ctx.arc(cx,cy,r,0,Math.PI*2);
  ctx.fillStyle = "rgba(1,8,18,0.75)"; ctx.fill();
  ctx.strokeStyle = "rgba(34,211,238,0.3)"; ctx.lineWidth = 0.8; ctx.stroke();
  ctx.font = "6px Consolas,monospace"; ctx.fillStyle = "rgba(34,211,238,0.55)"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
  ctx.fillText("N",cx,cy-r+4); ctx.fillText("S",cx,cy+r-4);
  ctx.fillText("E",cx+r-4,cy); ctx.fillText("W",cx-r+4,cy);
  const nl = r-4, nx = Math.sin(yr), ny = -Math.cos(yr);
  ctx.beginPath(); ctx.moveTo(cx,cy); ctx.lineTo(cx+nx*nl,cy+ny*nl);
  ctx.strokeStyle = "#ef4444"; ctx.lineWidth = 1.5; ctx.lineCap = "round"; ctx.stroke();
  ctx.beginPath(); ctx.moveTo(cx,cy); ctx.lineTo(cx-nx*nl*0.6,cy-ny*nl*0.6);
  ctx.strokeStyle = "rgba(255,255,255,0.35)"; ctx.lineWidth = 1; ctx.stroke();
  ctx.beginPath(); ctx.arc(cx,cy,2,0,Math.PI*2); ctx.fillStyle = "#38bdf8"; ctx.fill();
  ctx.font = "7px Consolas,monospace"; ctx.fillStyle = "#22d3ee"; ctx.textAlign = "center"; ctx.textBaseline = "top";
  ctx.fillText(`${Math.round((((_liveYaw%360)+360)%360))}°`, cx, cy+r+2);
  ctx.restore();
}

function initTrajectory() {
  const container = document.querySelector(".trajectory-status");
  if (!container) return;
  container.querySelector(".trajectory-graph")?.remove();

  const wrap = document.createElement("div");
  wrap.className = "trajectory-graph status-trajectory";
  Object.assign(wrap.style, {
    position:"relative", flex:"1", minHeight:"0", borderRadius:"8px",
    overflow:"hidden", background:"rgba(1,8,18,0.88)",
    border:"1px solid rgba(65,166,255,0.15)"
  });

  trajCanvas = document.createElement("canvas");
  trajCanvas.style.cssText = "width:100%;height:100%;display:block;";
  wrap.appendChild(trajCanvas);

  const overlay = document.createElement("div");
  overlay.id = "traj-info";
  Object.assign(overlay.style, {
    position:"absolute", top:"7px", left:"9px", fontSize:"10px",
    fontFamily:"Consolas,monospace", color:"#22d3ee", pointerEvents:"none",
    lineHeight:"1.7", textShadow:"0 0 8px rgba(0,0,0,.9)"
  });
  overlay.textContent = "WAITING FOR PIXHAWK…";
  wrap.appendChild(overlay);

  const btnBar = document.createElement("div");
  btnBar.style.cssText = "position:absolute;top:7px;right:8px;display:flex;gap:5px;";
  const mkBtn = (lbl, title, fn) => {
    const b = document.createElement("button");
    b.textContent = lbl; b.title = title;
    b.style.cssText = "padding:2px 9px;font-size:10px;border-radius:5px;cursor:pointer;background:#081320;border:1px solid rgba(34,211,238,.28);color:#22d3ee;font-family:Consolas,monospace;";
    b.addEventListener("click", fn); btnBar.appendChild(b);
  };
  mkBtn("CLR", "Clear trajectory", clearTrajectory);
  mkBtn("⏸",  "Pause / Resume",   toggleTrajPause);
  mkBtn("PNG", "Simpan PNG",       () => saveTrajectoryImage(nowStamp()));
  wrap.appendChild(btnBar);

  const infoDiv = container.querySelector(".trajectory-info");
  if (infoDiv) container.insertBefore(wrap, infoDiv);
  else         container.appendChild(wrap);

  if (infoDiv) infoDiv.innerHTML = `
    <div><span>TOTAL DIST</span><strong id="traj-dist">0.00 m</strong></div>
    <div><span>MAX DEPTH</span><strong id="traj-maxdepth">0.00 m</strong></div>
    <div><span>WAYPOINTS</span><strong id="traj-pts">0</strong></div>`;

  new ResizeObserver(resizeTrajCanvas).observe(wrap);
  resizeTrajCanvas();
  requestAnimationFrame(drawTraj);
}

function resizeTrajCanvas() {
  if (!trajCanvas) return;
  const rect = trajCanvas.getBoundingClientRect();
  const dpr  = devicePixelRatio || 1;
  trajCanvas.width  = rect.width  * dpr;
  trajCanvas.height = rect.height * dpr;
  trajCtx = trajCanvas.getContext("2d");
  trajCtx.scale(dpr, dpr);
}

function recordTrajPoint(x, y, depth, yawDeg, posValid) {
  if (trajPaused) return;
  _liveYaw = yawDeg; _liveDepth = depth;
  _livePosValid = posValid; trajPosMode = posValid ? "NED" : "DR";
  if (posValid) {
    if (trajStartX === null) { trajStartX = x; trajStartY = y; }
    const rx = x - trajStartX, ry = y - trajStartY;
    const last = trajPoints[trajPoints.length-1];
    if (last && Math.hypot(rx-last.x, ry-last.y) < MIN_MOVE_NED) return;
    trajPoints.push({x:rx, y:ry, depth, yaw:yawDeg, t:Date.now()});
    if (trajPoints.length > TRAJ_MAX) trajPoints.shift();
  }
}

function _drUpdate(now) {
  if (_livePosValid || trajPaused) return;
  if (_drLastT === null) { _drLastT = now; _drLastYaw = _liveYaw; return; }
  const dt = (now - _drLastT) / 1000; _drLastT = now;
  let dy = _liveYaw - (_drLastYaw||_liveYaw);
  if (dy>180) dy-=360; if (dy<-180) dy+=360;
  _drLastYaw = _liveYaw;
  const yr = (_liveYaw*Math.PI)/180;
  _drX += Math.cos(yr)*0.08*dt; _drY += Math.sin(yr)*0.08*dt;
  if (trajStartX===null) { trajStartX=_drX; trajStartY=_drY; }
  const rx=_drX-trajStartX, ry=_drY-trajStartY;
  const last = trajPoints[trajPoints.length-1];
  if (last && Math.hypot(rx-last.x,ry-last.y) < MIN_MOVE_DR) return;
  trajPoints.push({x:rx, y:ry, depth:_liveDepth, yaw:_liveYaw, t:now});
  if (trajPoints.length > TRAJ_MAX) trajPoints.shift();
}

function clearTrajectory() {
  trajPoints=[]; trajStartX=null; trajStartY=null;
  appendLog("Trajectory cleared.");
}
function toggleTrajPause() {
  trajPaused=!trajPaused;
  appendLog(trajPaused?"Trajectory PAUSED.":"Trajectory RESUMED.");
}

function drawTraj(now) {
  requestAnimationFrame(drawTraj);
  if (!trajCtx||!trajCanvas) return;
  _drUpdate(now);
  const dpr=devicePixelRatio||1, W=trajCanvas.width/dpr, H=trajCanvas.height/dpr;
  const ctx=trajCtx;
  ctx.clearRect(0,0,W,H);

  ctx.save(); ctx.strokeStyle="rgba(34,211,238,0.07)"; ctx.lineWidth=0.5;
  for(let gx=0;gx<=W;gx+=36){ctx.beginPath();ctx.moveTo(gx,0);ctx.lineTo(gx,H);ctx.stroke();}
  for(let gy=0;gy<=H;gy+=36){ctx.beginPath();ctx.moveTo(0,gy);ctx.lineTo(W,gy);ctx.stroke();}
  ctx.restore();

  if (trajPoints.length<2) {
    ctx.save(); ctx.fillStyle="rgba(34,211,238,0.28)"; ctx.font="10px Consolas,monospace"; ctx.textAlign="center";
    ctx.fillText(trajPosMode==="WAITING"?"WAITING FOR PIXHAWK IMU DATA…":`${trajPosMode} MODE — MOVE ROV TO START TRACE`,W/2,H/2);
    ctx.restore(); _drawCompass(ctx,W,H); return;
  }

  const PAD=28;
  let minX=Infinity,maxX=-Infinity,minY=Infinity,maxY=-Infinity;
  for(const p of trajPoints){if(p.x<minX)minX=p.x;if(p.x>maxX)maxX=p.x;if(p.y<minY)minY=p.y;if(p.y>maxY)maxY=p.y;}
  const rX=Math.max(maxX-minX,0.5), rY=Math.max(maxY-minY,0.5);
  const sc=Math.min((W-PAD*2)/rX,(H-PAD*2)/rY);
  const ox=PAD+(W-PAD*2-rX*sc)/2-minX*sc, oy=PAD+(H-PAD*2-rY*sc)/2-minY*sc;
  const s2c=p=>[ox+p.x*sc,oy+p.y*sc];

  const tailI=Math.max(0,trajPoints.length-TRAJ_TAIL);
  if(tailI>1){
    ctx.beginPath(); ctx.strokeStyle="rgba(34,211,238,0.13)"; ctx.lineWidth=1; ctx.setLineDash([3,5]);
    const[sx,sy]=s2c(trajPoints[0]); ctx.moveTo(sx,sy);
    for(let i=1;i<tailI;i++){const[px,py]=s2c(trajPoints[i]);ctx.lineTo(px,py);}
    ctx.stroke(); ctx.setLineDash([]);
  }

  const tail=trajPoints.slice(tailI);
  for(let i=1;i<tail.length;i++){
    const p0=tail[i-1],p1=tail[i];
    const alpha=0.35+0.65*(i/tail.length);
    const dr=Math.min(p1.depth/(DEPTH_WARN*1.5),1);
    const r=Math.round(34+(220-34)*dr), g=Math.round(211+(50-211)*dr), b=Math.round(238+(80-238)*dr);
    const[x0,y0]=s2c(p0),[x1,y1]=s2c(p1);
    ctx.beginPath(); ctx.strokeStyle=`rgba(${r},${g},${b},${alpha})`; ctx.lineWidth=1.8; ctx.lineCap="round";
    ctx.moveTo(x0,y0); ctx.lineTo(x1,y1); ctx.stroke();
  }

  const[ax,ay]=s2c(trajPoints[0]);
  ctx.beginPath(); ctx.arc(ax,ay,4,0,Math.PI*2);
  ctx.fillStyle="#22c55e"; ctx.shadowColor="#22c55e"; ctx.shadowBlur=9; ctx.fill(); ctx.shadowBlur=0;
  ctx.save(); ctx.font="8px Consolas,monospace"; ctx.fillStyle="#22c55e"; ctx.fillText("START",ax+7,ay+3); ctx.restore();

  const cur=trajPoints[trajPoints.length-1],[cx,cy]=s2c(cur);
  const pulse=0.5+0.5*Math.sin(Date.now()/280);
  ctx.beginPath(); ctx.arc(cx,cy,9+pulse*3,0,Math.PI*2);
  ctx.strokeStyle=`rgba(56,189,248,${0.18+pulse*0.25})`; ctx.lineWidth=1.2; ctx.stroke();
  ctx.beginPath(); ctx.arc(cx,cy,5,0,Math.PI*2);
  ctx.fillStyle="#38bdf8"; ctx.shadowColor="#38bdf8"; ctx.shadowBlur=14; ctx.fill(); ctx.shadowBlur=0;

  if(trajPoints.length>=4){
    const prev=trajPoints[trajPoints.length-4],[px,py]=s2c(prev);
    const dx=cx-px,dy=cy-py,len=Math.sqrt(dx*dx+dy*dy);
    if(len>3){const ang=Math.atan2(dy,dx),hl=8;
      ctx.beginPath(); ctx.moveTo(cx,cy);
      ctx.lineTo(cx-hl*Math.cos(ang-0.45),cy-hl*Math.sin(ang-0.45));
      ctx.lineTo(cx-hl*Math.cos(ang+0.45),cy-hl*Math.sin(ang+0.45));
      ctx.closePath(); ctx.fillStyle="#38bdf8"; ctx.fill();}
  }

  const dc=trajPoints.filter(p=>p.depth>=DEPTH_WARN).length;
  if(dc>0){ctx.font="9px Consolas,monospace";ctx.fillStyle="#ef4444";ctx.textAlign="left";ctx.fillText(`⚠ ${dc} pts ≥ ${DEPTH_WARN}m`,7,H-7);}
  ctx.save(); ctx.font="9px Consolas,monospace"; ctx.textAlign="right";
  ctx.fillStyle=trajPosMode==="NED"?"#22c55e":"#f59e0b";
  ctx.fillText(`● ${trajPosMode}`,W-7,H-7); ctx.restore();

  _drawCompass(ctx,W,H);

  const infoEl=document.getElementById("traj-info");
  if(infoEl) infoEl.textContent=
    `[${trajPosMode}] X ${cur.x.toFixed(2)}m  Y ${cur.y.toFixed(2)}m  D ${cur.depth.toFixed(2)}m`+
    (trajPaused?"  ⏸":"");

  let tot=0;
  for(let i=1;i<trajPoints.length;i++){const dx=trajPoints[i].x-trajPoints[i-1].x,dy=trajPoints[i].y-trajPoints[i-1].y;tot+=Math.sqrt(dx*dx+dy*dy);}
  const mx=Math.max(...trajPoints.map(p=>p.depth));
  document.getElementById("traj-dist")  ;
  document.getElementById("traj-maxdepth");
  document.getElementById("traj-pts")   ;
  const dEl=document.getElementById("traj-dist");
  const dpEl=document.getElementById("traj-maxdepth");
  const ptEl=document.getElementById("traj-pts");
  if(dEl)dEl.textContent=tot.toFixed(2)+" m";
  if(dpEl)dpEl.textContent=mx.toFixed(2)+" m";
  if(ptEl)ptEl.textContent=trajPoints.length;
}

// ============================================================
// 11. INIT
// ============================================================
initTrajectory();
appendLog(`GCS online — backend: ${BACKEND_URL}`);
appendLog(`Sesi: ROV_${SESSION_ID}__*`);