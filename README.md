# RunCplus Web — Cloud IDE, Compilation Sandbox API & Downloads

RunCplus Web provides a full-featured web-based IDE, C/C++ compilation sandbox, and ecosystem download portal for the RunCplus developer suite.

## Features

- **Live Web IDE & Playground:** Split-pane editor matching the Qt desktop workspace, real-time output terminal, execution timing, stdin feeding, and dark theme.
- **C/C++ Compilation Sandbox API:**
  - `POST /api/run`: Compiles and runs C++20, C++17, C++23, C11, C17 with GCC.
  - `GET /api/status`: Real-time system health, uptime, and execution telemetry.
- **Watchdog Protection:** Strict 2.0-second infinite loop execution watchdog (terminates with `Time Limit Exceeded`).
- **Smart SHA-256 Binary Caching:** Instant zero-latency execution on unchanged code.
- **Diagnostic Extraction:** Inline line/column error and warning parsing.
- **Official Downloads Hub:** Linux Desktop application package and Android Mobile APK.

## Deployment

Deployable via Docker or directly on any Linux environment with GCC and Python 3.

```bash
docker build -t runcplus-web .
docker run -p 8080:8080 runcplus-web
```
