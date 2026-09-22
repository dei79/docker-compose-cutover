import json
import os
import socket
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

MAX_SLOW_SECONDS = 120

PAGE = b"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Blue/Green Demo</title>
<style>
  :root { color-scheme: dark; }
  body {
    margin: 0; height: 100vh; display: flex; align-items: center; justify-content: center;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: #1a1a1a; color: #f5f5f5; transition: background-color 0.4s ease;
  }
  body.slot-blue { background: #0b3d91; }
  body.slot-green { background: #0b6e2f; }
  .card { text-align: center; }
  .slot { font-size: 4rem; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; }
  .version { font-size: 1.75rem; margin-top: 0.25rem; opacity: 0.95; }
  .service { font-size: 1rem; opacity: 0.75; margin-top: 0.75rem; }
  .hostname, .updated { font-size: 0.85rem; opacity: 0.6; margin-top: 0.25rem; }
  .stats { margin-top: 1.5rem; font-size: 0.95rem; opacity: 0.9; }
  .stats .fail-count { font-weight: 700; }
  .stats .fail-count.ok { color: #82e0a0; }
  .stats .fail-count.bad { color: #ff5252; }
  .ring-wrap { display: flex; justify-content: center; margin: 1rem 0; }
  #progress-ring { transform: rotate(-90deg); }
  #progress-ring-fg {
    stroke: rgba(255, 255, 255, 0.85);
    transition: stroke-dashoffset linear;
  }
  #progress-ring-fg.error { stroke: #ff5252; }
  .long-request { margin-top: 1.5rem; }
  #long-request-btn {
    font: inherit; font-size: 0.9rem; padding: 0.5rem 1rem; border-radius: 999px;
    border: 1px solid rgba(255, 255, 255, 0.4); background: rgba(255, 255, 255, 0.1);
    color: inherit; cursor: pointer;
  }
  #long-request-btn:hover:not(:disabled) { background: rgba(255, 255, 255, 0.2); }
  #long-request-btn:disabled { opacity: 0.6; cursor: default; }
  #long-request-status { display: block; margin-top: 0.5rem; font-size: 0.85rem; opacity: 0.8; min-height: 1.2em; }
</style>
</head>
<body>
  <div class="card">
    <div class="service" id="service">-</div>
    <div class="slot" id="slot">-</div>
    <div class="version" id="version">-</div>
    <div class="ring-wrap">
      <svg id="progress-ring" width="48" height="48" viewBox="0 0 48 48">
        <circle cx="24" cy="24" r="20" fill="none" stroke="rgba(255,255,255,0.15)" stroke-width="4"/>
        <circle id="progress-ring-fg" cx="24" cy="24" r="20" fill="none" stroke-width="4" stroke-linecap="round"/>
      </svg>
    </div>
    <div class="hostname" id="hostname"></div>
    <div class="updated" id="updated">connecting...</div>
    <div class="stats">
      <span id="req-count">0</span> requests fired |
      <span class="fail-count ok" id="fail-count">0</span> failures
    </div>
    <div class="long-request">
      <button id="long-request-btn">Start 60s long request</button>
      <span id="long-request-status"></span>
    </div>
  </div>
<script>
const REFRESH_MS = 2500;
const ring = document.getElementById("progress-ring-fg");
const RING_CIRCUMFERENCE = 2 * Math.PI * 20;
ring.style.strokeDasharray = String(RING_CIRCUMFERENCE);

function startProgress() {
  ring.classList.remove("error");
  ring.style.transitionDuration = "0s";
  ring.style.strokeDashoffset = "0"; // full ring
  ring.getBoundingClientRect(); // force reflow so the next transition restarts
  ring.style.transitionDuration = `${REFRESH_MS}ms`;
  ring.style.strokeDashoffset = String(RING_CIRCUMFERENCE); // drains to empty, like a countdown
}

async function refresh() {
  startProgress();
  try {
    const response = await fetch("/health", { cache: "no-store" });
    if (!response.ok) throw new Error("HTTP " + response.status);
    const data = await response.json();
    document.getElementById("service").textContent = data.service;
    document.getElementById("slot").textContent = data.slot;
    document.getElementById("version").textContent = "v" + data.version;
    document.getElementById("hostname").textContent = data.hostname;
    document.getElementById("updated").textContent = "updated " + new Date().toLocaleTimeString();
    document.body.classList.remove("slot-blue", "slot-green");
    document.body.classList.add("slot-" + data.slot);
  } catch (error) {
    document.getElementById("updated").textContent = "unavailable: " + error;
    ring.classList.add("error");
  }
}
let refreshTimer = null;
function startAutoRefresh() {
  if (refreshTimer === null) refreshTimer = setInterval(refresh, REFRESH_MS);
}
function stopAutoRefresh() {
  clearInterval(refreshTimer);
  refreshTimer = null;
}

refresh();
startAutoRefresh();

// "Long request" button: pauses the auto-refresh above and fires a single
// request that the server deliberately holds open for 60s (see /slow). This
// mirrors what a deploy's worker-drain has to wait out: the old NGINX worker
// serving this request must survive until it finishes before the old
// container is stopped. Meanwhile the hammer workers below keep proving
// ordinary traffic stays at zero failures throughout.
const longRequestBtn = document.getElementById("long-request-btn");
const longRequestStatus = document.getElementById("long-request-status");

async function startLongRequest() {
  const DURATION = 60;
  stopAutoRefresh();
  longRequestBtn.disabled = true;
  let remaining = DURATION;
  longRequestStatus.textContent = `running... ${remaining}s left (an NGINX worker must stay up until this returns)`;
  const countdown = setInterval(() => {
    remaining -= 1;
    if (remaining >= 0) {
      longRequestStatus.textContent = `running... ${remaining}s left (an NGINX worker must stay up until this returns)`;
    }
  }, 1000);

  const startedAt = performance.now();
  try {
    const response = await fetch(`/slow?seconds=${DURATION}`, { cache: "no-store" });
    if (!response.ok) throw new Error("HTTP " + response.status);
    const data = await response.json();
    const elapsed = ((performance.now() - startedAt) / 1000).toFixed(1);
    longRequestStatus.textContent =
      `done after ${elapsed}s, served by ${data.slot} v${data.version} (${data.hostname})`;
  } catch (error) {
    longRequestStatus.textContent = "failed: " + error;
  } finally {
    clearInterval(countdown);
    longRequestBtn.disabled = false;
    startAutoRefresh();
  }
}
longRequestBtn.addEventListener("click", startLongRequest);

// Load test: several parallel workers hammer /health continuously so you can
// watch the request/failure counters while deploying and see nothing fail.
const HAMMER_WORKERS = 6;
const HAMMER_DELAY_MS = 20;
let requestsFired = 0;
let requestsFailed = 0;
const reqCountEl = document.getElementById("req-count");
const failCountEl = document.getElementById("fail-count");

function isValidRelease(data) {
  return data && typeof data === "object"
    && (data.slot === "blue" || data.slot === "green")
    && !!data.version && !!data.hostname;
}

function updateStats() {
  reqCountEl.textContent = requestsFired;
  failCountEl.textContent = requestsFailed;
  failCountEl.classList.toggle("ok", requestsFailed === 0);
  failCountEl.classList.toggle("bad", requestsFailed > 0);
}

async function hammer() {
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  while (true) {
    requestsFired++;
    try {
      const response = await fetch("/health", { cache: "no-store" });
      const data = await response.json();
      if (!response.ok || !isValidRelease(data)) throw new Error("unexpected response");
    } catch {
      requestsFailed++;
    }
    updateStats();
    await sleep(HAMMER_DELAY_MS);
  }
}
for (let worker = 0; worker < HAMMER_WORKERS; worker++) hammer();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    # Default is HTTP/1.0 (a fresh TCP connection per request). Under the many
    # concurrent requests the demo page fires, that connection churn through
    # the Docker network stack causes spurious resets/timeouts. HTTP/1.1
    # enables keep-alive (Content-Length is always sent below), reusing
    # connections instead.
    protocol_version = "HTTP/1.1"

    def _release_info(self, **extra):
        return {
            "service": "demo-service",
            "version": os.environ.get("VERSION", "1.0.0"),
            "slot": os.environ["SLOT"],
            "hostname": socket.gethostname(),
            **extra,
        }

    def _send_json(self, payload):
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlsplit(self.path)
        if parsed.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(PAGE)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(PAGE)
            return
        if parsed.path == "/health":
            self._send_json(self._release_info())
            return
        if parsed.path == "/slow":
            # Deliberately holds this request (and the NGINX worker proxying it)
            # open for a while, to demo a deploy draining a long-running request.
            try:
                seconds = float(parse_qs(parsed.query).get("seconds", ["60"])[0])
            except ValueError:
                seconds = 60.0
            seconds = max(0.0, min(seconds, MAX_SLOW_SECONDS))
            time.sleep(seconds)
            self._send_json(self._release_info(slept=seconds))
            return
        self.send_error(404)


ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
