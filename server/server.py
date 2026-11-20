#!/usr/bin/env python3
"""
RunCplus Cloud Sandbox & Web API Server
Serves the RunCplus Web Playground, compilation API, and download binaries.
Features:
- Live C++20/C++17/C++23/C11 compilation with GCC
- 2.0-second Infinite Loop Watchdog timer (TLE detection)
- Smart SHA-256 binary caching
- Real-time inline compiler diagnostic parsing
- Downloads for RunCplus Desktop (Linux) and RunCplus Mobile (Android APK)
"""

import os
import sys
import json
import time
import socket
import re
import hmac
import secrets
import hashlib
import tempfile
import threading
import subprocess
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse

PORT = int(os.environ.get("PORT", 8080))
GRPC_PORT = int(os.environ.get("GRPC_PORT", 50051))
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(BASE_DIR, "static")
DOWNLOADS_DIR = os.path.join(BASE_DIR, "downloads")
CACHE_DIR = os.path.join(BASE_DIR, "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Security configuration
# ---------------------------------------------------------------------------
BIND_HOST = os.environ.get("BIND_HOST", "0.0.0.0")

TOKEN_PATH = os.path.join(BASE_DIR, ".token")
MAX_CONCURRENT_RUNS = int(os.environ.get("MAX_CONCURRENT_RUNS", 4))
RATE_WINDOW_SEC = 60
RATE_MAX_RUNS = int(os.environ.get("RATE_MAX_RUNS", 40))
REQUIRE_AUTH = os.environ.get("REQUIRE_AUTH", "false").lower() in ("true", "1", "yes")


def load_or_create_token():
    """Load the sandbox API token if configured."""
    env_token = os.environ.get("RUNCPLUS_TOKEN", "").strip()
    if env_token:
        return env_token
    try:
        if os.path.exists(TOKEN_PATH):
            with open(TOKEN_PATH, "r", encoding="utf-8") as fh:
                existing = fh.read().strip()
            if existing:
                return existing
    except Exception:
        pass
    if REQUIRE_AUTH:
        new_token = secrets.token_urlsafe(24)
        try:
            with open(TOKEN_PATH, "w", encoding="utf-8") as fh:
                fh.write(new_token + "\n")
        except Exception:
            pass
        return new_token
    return ""


AUTH_TOKEN = load_or_create_token()

_exec_sem = threading.Semaphore(MAX_CONCURRENT_RUNS)
_rl_lock = threading.Lock()
_rl_log = {}


def rate_limited(client_ip):
    """Sliding-window limiter per client IP."""
    now = time.time()
    with _rl_lock:
        bucket = _rl_log.setdefault(client_ip, [])
        while bucket and now - bucket[0] > RATE_WINDOW_SEC:
            bucket.pop(0)
        if len(bucket) >= RATE_MAX_RUNS:
            return True
        bucket.append(now)
        if len(_rl_log) > 4096:
            for stale in [ip for ip, hits in _rl_log.items() if not hits or now - hits[-1] > RATE_WINDOW_SEC]:
                _rl_log.pop(stale, None)
    return False

START_TIME = time.time()
STATS = {
    "total_runs": 0,
    "cache_hits": 0,
    "compile_errors": 0,
    "tle_watchdogs": 0,
    "success_runs": 0
}
STATS_LOCK = threading.Lock()

def check_grpc_status(host="127.0.0.1", port=GRPC_PORT):
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except Exception:
        return False

def get_gcc_version():
    try:
        res = subprocess.run(["g++", "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        first_line = res.stdout.strip().splitlines()[0] if res.stdout else "GCC (installed)"
        return first_line
    except Exception as e:
        return f"Unknown GCC: {e}"

GCC_VERSION_STR = get_gcc_version()

def parse_gcc_diagnostics(stderr_text):
    diagnostics = []
    pattern = re.compile(r"^([^:\n]+):(\d+):(\d+):\s+(error|warning|note|fatal error):\s+(.*)$", re.MULTILINE)
    for match in pattern.finditer(stderr_text):
        diagnostics.append({
            "file": match.group(1),
            "line": int(match.group(2)),
            "column": int(match.group(3)),
            "type": match.group(4),
            "message": match.group(5)
        })
    return diagnostics

def execute_code(code: str, stdin_data: str = "", standard: str = "c++20", optimization: str = "-O2"):
    global STATS
    with STATS_LOCK:
        STATS["total_runs"] += 1

    if standard not in ("c++17", "c++20", "c++23", "c11", "c17"):
        standard = "c++20"
    if optimization not in ("-O0", "-O1", "-O2", "-O3", "-Os"):
        optimization = "-O2"

    is_c = standard.startswith("c") and not standard.startswith("c++")
    compiler = "gcc" if is_c else "g++"

    # Compute hash for smart binary cache
    cache_payload = f"{compiler}|{standard}|{optimization}|{code}".encode("utf-8")
    binary_hash = hashlib.sha256(cache_payload).hexdigest()
    cached_bin = os.path.join(CACHE_DIR, f"bin_{binary_hash}")

    is_cached = os.path.isfile(cached_bin)
    compile_duration_ms = 0.0

    if is_cached:
        with STATS_LOCK:
            STATS["cache_hits"] += 1
        bin_path = cached_bin
    else:
        # Need compilation
        with tempfile.TemporaryDirectory() as tmpdir:
            src_file = os.path.join(tmpdir, "main.c" if is_c else "main.cpp")
            out_bin = os.path.join(tmpdir, "main.out")
            with open(src_file, "w", encoding="utf-8") as f:
                f.write(code)

            compile_cmd = [
                compiler,
                f"-std={standard}",
                optimization,
                "-Wall",
                "-Wextra",
                "-pthread",
                src_file,
                "-o",
                out_bin
            ]

            comp_start = time.perf_counter()
            try:
                comp_res = subprocess.run(
                    compile_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=10.0
                )
                compile_duration_ms = round((time.perf_counter() - comp_start) * 1000, 2)
            except subprocess.TimeoutExpired:
                with STATS_LOCK:
                    STATS["compile_errors"] += 1
                return {
                    "status": "compile_timeout",
                    "stdout": "",
                    "stderr": "Compilation timed out after 10.0 seconds.",
                    "exit_code": -1,
                    "compile_duration_ms": 10000.0,
                    "execution_duration_ms": 0.0,
                    "cached": False,
                    "diagnostics": []
                }

            if comp_res.returncode != 0:
                with STATS_LOCK:
                    STATS["compile_errors"] += 1
                diagnostics = parse_gcc_diagnostics(comp_res.stderr)
                return {
                    "status": "compile_error",
                    "stdout": comp_res.stdout,
                    "stderr": comp_res.stderr,
                    "exit_code": comp_res.returncode,
                    "compile_duration_ms": compile_duration_ms,
                    "execution_duration_ms": 0.0,
                    "cached": False,
                    "diagnostics": diagnostics
                }

            # Cache compiled binary
            try:
                with open(out_bin, "rb") as sf, open(cached_bin, "wb") as df:
                    df.write(sf.read())
                os.chmod(cached_bin, 0o755)
            except Exception:
                pass
            bin_path = cached_bin

    # Execute with 2.0-second Infinite Loop Watchdog timer
    exec_start = time.perf_counter()
    try:
        exec_proc = subprocess.Popen(
            [bin_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            preexec_fn=os.setsid
        )
        try:
            stdout_data, stderr_data = exec_proc.communicate(input=stdin_data, timeout=2.0)
            exec_duration_ms = round((time.perf_counter() - exec_start) * 1000, 2)
            exit_code = exec_proc.returncode

            # Output truncation safety cap (512 KB)
            MAX_CHARS = 500000
            if len(stdout_data) > MAX_CHARS:
                stdout_data = stdout_data[:MAX_CHARS] + "\n\n[RunCplus Watchdog: Output truncated at 500KB]"
            if len(stderr_data) > MAX_CHARS:
                stderr_data = stderr_data[:MAX_CHARS] + "\n\n[RunCplus Watchdog: Output truncated at 500KB]"

            if exit_code == 0:
                with STATS_LOCK:
                    STATS["success_runs"] += 1

            return {
                "status": "success" if exit_code == 0 else "runtime_error",
                "stdout": stdout_data,
                "stderr": stderr_data,
                "exit_code": exit_code,
                "compile_duration_ms": compile_duration_ms,
                "execution_duration_ms": exec_duration_ms,
                "cached": is_cached,
                "diagnostics": []
            }
        except subprocess.TimeoutExpired:
            # Terminate process group (SIGKILL)
            import signal
            try:
                os.killpg(os.getpgid(exec_proc.pid), signal.SIGKILL)
            except Exception:
                pass
            exec_proc.kill()
            with STATS_LOCK:
                STATS["tle_watchdogs"] += 1
            return {
                "status": "time_limit_exceeded",
                "stdout": "",
                "stderr": "Execution terminated by RunCplus Watchdog: Time Limit Exceeded (2.0s limit).",
                "exit_code": 137,
                "compile_duration_ms": compile_duration_ms,
                "execution_duration_ms": 2000.0,
                "cached": is_cached,
                "diagnostics": []
            }
    except Exception as e:
        return {
            "status": "internal_error",
            "stdout": "",
            "stderr": f"Runtime execution error: {str(e)}",
            "exit_code": -1,
            "compile_duration_ms": compile_duration_ms,
            "execution_duration_ms": 0.0,
            "cached": is_cached,
            "diagnostics": []
        }

class RunCplusHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=STATIC_DIR, **kwargs)

    def log_message(self, format, *args):
        # Format custom log line
        sys.stderr.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {self.address_string()} - {format % args}\n")

    def _json_error(self, code, message, extra=None):
        payload = {"error": message, "status": code}
        if extra:
            payload.update(extra)
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/status":
            uptime_sec = round(time.time() - START_TIME, 1)
            with STATS_LOCK:
                stats_copy = dict(STATS)
            res = {
                "service": "RunCplus Cloud Sandbox",
                "status": "operational",
                "version": "2.4.0",
                "uptime_seconds": uptime_sec,
                "compiler": GCC_VERSION_STR,
                "supported_standards": ["c++17", "c++20", "c++23", "c11", "c17"],
                "grpc_sandbox_active": check_grpc_status(),
                "watchdog_timeout_ms": 2000,
                "cache_size_entries": len(os.listdir(CACHE_DIR)),
                "stats": stats_copy,
                "auth_required": bool(REQUIRE_AUTH and AUTH_TOKEN)
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(res, indent=2).encode("utf-8"))
            return

        if path.startswith("/downloads/"):
            filename = os.path.basename(path)
            file_path = os.path.join(DOWNLOADS_DIR, filename)
            if os.path.isfile(file_path):
                file_size = os.path.getsize(file_path)
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
                self.send_header("Content-Length", str(file_size))
                self.end_headers()
                with open(file_path, "rb") as f:
                    while chunk := f.read(65536):
                        self.wfile.write(chunk)
                return
            else:
                self.send_error(404, f"File {filename} not found.")
                return

        # Default static file handler
        return super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path in ("/api/run", "/api/compile"):
            client_ip = (
                self.headers.get("cf-connecting-ip")
                or self.headers.get("x-forwarded-for", "").split(",")[0].strip()
                or self.client_address[0]
            )

            # Authorization if configured
            if REQUIRE_AUTH and AUTH_TOKEN:
                provided = self.headers.get("X-RunCplus-Token", "")
                if not provided:
                    auth_header = self.headers.get("Authorization", "")
                    if auth_header.lower().startswith("bearer "):
                        provided = auth_header[7:].strip()
                if not provided or not hmac.compare_digest(provided, AUTH_TOKEN):
                    self._json_error(
                        401,
                        "Unauthorized: missing or invalid sandbox token",
                        {"hint": "Send the token in the X-RunCplus-Token header."},
                    )
                    return

            if rate_limited(client_ip):
                self._json_error(
                    429,
                    "Too many executions. Please wait before retrying.",
                    {"limit_per_minute": RATE_MAX_RUNS},
                )
                return

            if not _exec_sem.acquire(timeout=5):
                self._json_error(
                    503,
                    "Sandbox is at capacity. Please retry shortly.",
                    {"max_concurrent_runs": MAX_CONCURRENT_RUNS},
                )
                return

            try:
                content_len = int(self.headers.get("Content-Length", 0))
                if content_len > 2 * 1024 * 1024:  # 2MB max code size
                    self.send_error(413, "Payload Too Large")
                    return

                body = self.rfile.read(content_len).decode("utf-8", errors="replace")
                try:
                    data = json.loads(body)
                except Exception:
                    self.send_error(400, "Invalid JSON")
                    return

                code = data.get("code", "")
                stdin_data = data.get("stdin", "")
                standard = data.get("standard", "c++20")
                optimization = data.get("optimization", "-O2")

                if not code.strip():
                    self.send_error(400, "Field 'code' cannot be empty")
                    return

                result = execute_code(code, stdin_data, standard, optimization)

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(result, indent=2).encode("utf-8"))
            finally:
                _exec_sem.release()
            return

        self.send_error(404, "Endpoint Not Found")

def main():
    print(f"[RunCplus Web Server] Starting HTTP server on {BIND_HOST}:{PORT}...")
    print(f"[RunCplus Web Server] Serving static from: {STATIC_DIR}")
    print(f"[RunCplus Web Server] Serving downloads from: {DOWNLOADS_DIR}")
    print(f"[RunCplus Web Server] Compiler: {GCC_VERSION_STR}")

    server = ThreadingHTTPServer((BIND_HOST, PORT), RunCplusHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[RunCplus Web Server] Shutting down...")
    finally:
        server.server_close()

if __name__ == "__main__":
    main()
