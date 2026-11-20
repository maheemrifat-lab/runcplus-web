/**
 * RunCplus Live Web IDE Application
 * Handles code editing, 500ms auto-run debounce, syntax samples,
 * stdin/stdout execution streaming, and compiler diagnostics.
 */

const TEMPLATES = {
  hello: `// RunCplus Live — C++20 Standard Library Demo
#include <iostream>
#include <vector>
#include <numeric>
#include <string>

int main() {
    std::cout << "=========================================\\n";
    std::cout << " ⚡ Welcome to RunCplus Cloud Playground! \\n";
    std::cout << "=========================================\\n\\n";

    std::vector<int> numbers = {10, 20, 30, 40, 50};
    int total = std::accumulate(numbers.begin(), numbers.end(), 0);

    std::cout << "• Numbers in vector: ";
    for (int n : numbers) {
        std::cout << n << " ";
    }
    std::cout << "\\n• Sum of elements: " << total << "\\n\\n";

    std::cout << "[RunCplus]: 500ms debounced live compilation active.\\n";
    std::cout << "[RunCplus]: Execution completed cleanly.\\n";
    return 0;
}`,

  watchdog: `// ⏱️ RunCplus Watchdog Demonstration
// Accidental infinite loops are forcefully terminated
// after exceeding the 2.0-second execution threshold.
#include <iostream>
#include <chrono>
#include <thread>

int main() {
    std::cout << "[Watchdog Demo] Initiating intentional infinite loop...\\n";
    std::cout << "[Watchdog Demo] Process will be killed after 2.0 seconds.\\n";
    std::cout.flush();

    long long counter = 0;
    while (true) {
        counter++;
        if (counter % 500000000 == 0) {
            std::cout << "Working... tick=" << counter << "\\n";
            std::cout.flush();
        }
    }

    return 0;
}`,

  cache: `// 🧠 Smart Binary Cache Test
// Once compiled, subsequent executions with identical code
// bypass the compiler entirely via cryptographic SHA-256 caching.
#include <iostream>
#include <chrono>

int main() {
    auto start = std::chrono::high_resolution_clock::now();

    long long sum = 0;
    for (int i = 1; i <= 1000000; ++i) {
        sum += i;
    }

    auto end = std::chrono::high_resolution_clock::now();
    std::chrono::duration<double, std::milli> duration = end - start;

    std::cout << "[Smart Cache]: Arithmetic test sum = " << sum << "\\n";
    std::cout << "[Smart Cache]: Calculation completed in " << duration.count() << " ms\\n";
    std::cout << "[Smart Cache]: Notice 'Cache: Hit (0ms compile)' on subsequent runs!\\n";
    return 0;
}`,

  interactive: `// ⌨️ Interactive stdin Demo
// Supply custom input in the 'Custom Input (stdin)' pane above!
#include <iostream>
#include <string>

int main() {
    std::string name;
    int age;

    std::cout << "Enter your name and age: ";
    if (std::cin >> name >> age) {
        std::cout << "\\nHello, " << name << "! Next year you will be " << (age + 1) << " years old.\\n";
    } else {
        std::cout << "\\n(No custom input provided. Enter 'Alex 24' in stdin pane and re-run!)\\n";
    }
    return 0;
}`,

  matrix: `// 📊 Matrix Multiply Benchmark
#include <iostream>
#include <vector>
#include <chrono>

int main() {
    const int N = 120;
    std::vector<std::vector<int>> A(N, std::vector<int>(N, 1));
    std::vector<std::vector<int>> B(N, std::vector<int>(N, 2));
    std::vector<std::vector<int>> C(N, std::vector<int>(N, 0));

    auto t1 = std::chrono::high_resolution_clock::now();

    for (int i = 0; i < N; ++i) {
        for (int k = 0; k < N; ++k) {
            for (int j = 0; j < N; ++j) {
                C[i][j] += A[i][k] * B[k][j];
            }
        }
    }

    auto t2 = std::chrono::high_resolution_clock::now();
    double ms = std::chrono::duration<double, std::milli>(t2 - t1).count();

    std::cout << "Multiplying two " << N << "x" << N << " matrices...\\n";
    std::cout << "Top-left cell C[0][0] = " << C[0][0] << "\\n";
    std::cout << "Matrix Multiplication Benchmark Duration: " << ms << " ms\\n";
    return 0;
}`
};

// DOM References
const codeEditor = document.getElementById("code-editor");
const lineNumbers = document.getElementById("line-numbers");
const stdinEditor = document.getElementById("stdin-editor");
const terminalOutput = document.getElementById("terminal-output");
const runBtn = document.getElementById("run-btn");
const templateSelect = document.getElementById("template-select");
const stdSelect = document.getElementById("std-select");
const optSelect = document.getElementById("opt-select");
const autorunCheck = document.getElementById("autorun-check");
const typingIndicator = document.getElementById("typing-indicator");
const lineColCounter = document.getElementById("line-col-counter");

// Metric Pills
const metricStatus = document.getElementById("metric-status");
const metricCompile = document.getElementById("metric-compile");
const metricExec = document.getElementById("metric-exec");
const metricCache = document.getElementById("metric-cache");

// Diagnostics Drawer
const diagBar = document.getElementById("diagnostics-bar");
const diagList = document.getElementById("diag-list");
const diagClose = document.getElementById("diag-close");

let debounceTimer = null;
let isExecuting = false;

// Update line numbers gutter
function updateLineNumbers() {
  const lines = codeEditor.value.split("\n").length;
  let nums = "";
  for (let i = 1; i <= lines; i++) {
    nums += i + "\n";
  }
  lineNumbers.textContent = nums;
}

// Update cursor position Ln/Col
function updateCursorPosition() {
  const text = codeEditor.value.substring(0, codeEditor.selectionStart);
  const lines = text.split("\n");
  const line = lines.length;
  const col = lines[lines.length - 1].length + 1;
  lineColCounter.textContent = `Ln ${line}, Col ${col}`;
}

// Sync scrolling between line numbers and textarea
codeEditor.addEventListener("scroll", () => {
  lineNumbers.scrollTop = codeEditor.scrollTop;
});

// Tab indentation handling
codeEditor.addEventListener("keydown", (e) => {
  if (e.key === "Tab") {
    e.preventDefault();
    const start = codeEditor.selectionStart;
    const end = codeEditor.selectionEnd;
    codeEditor.value = codeEditor.value.substring(0, start) + "    " + codeEditor.value.substring(end);
    codeEditor.selectionStart = codeEditor.selectionEnd = start + 4;
    updateLineNumbers();
    triggerAutoRun();
  } else if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
    e.preventDefault();
    runCode();
  }
});

// Input event with 500ms debounce
codeEditor.addEventListener("input", () => {
  updateLineNumbers();
  updateCursorPosition();
  triggerAutoRun();
});

codeEditor.addEventListener("click", updateCursorPosition);
codeEditor.addEventListener("keyup", updateCursorPosition);

function triggerAutoRun() {
  if (!autorunCheck.checked) return;

  typingIndicator.textContent = "typing...";
  typingIndicator.className = "editor-indicator running";

  if (debounceTimer) clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => {
    typingIndicator.textContent = "compiling...";
    runCode();
  }, 500); // Exactly 500ms matching Desktop RunCplus!
}

// Template selection handler
templateSelect.addEventListener("change", (e) => {
  const key = e.target.value;
  if (TEMPLATES[key]) {
    codeEditor.value = TEMPLATES[key];
    updateLineNumbers();
    updateCursorPosition();
    if (key === "interactive") {
      stdinEditor.value = "Mahim 23";
    }
    runCode();
  }
});

// Run Code function
async function runCode() {
  if (isExecuting) return;
  isExecuting = true;

  runBtn.disabled = true;
  runBtn.innerHTML = `<span>Building...</span>`;
  metricStatus.textContent = "Running...";
  metricStatus.className = "metric tle";

  const payload = {
    code: codeEditor.value,
    stdin: stdinEditor.value,
    standard: stdSelect.value,
    optimization: optSelect.value
  };

  try {
    const sendRun = (token) => {
      const headers = { "Content-Type": "application/json" };
      if (token) headers["X-RunCplus-Token"] = token;
      return fetch("/api/run", {
        method: "POST",
        headers,
        body: JSON.stringify(payload)
      });
    };

    let res = await sendRun(localStorage.getItem("runcplus_token") || "");

    if (res.status === 401) {
      const entered = window.prompt(
        "This sandbox requires an access token.\n\nPaste your RunCplus token to continue:"
      );
      if (entered && entered.trim()) {
        localStorage.setItem("runcplus_token", entered.trim());
        res = await sendRun(entered.trim());
      }
    }

    if (res.status === 401) {
      terminalOutput.innerHTML = `<span style="color: #f85149;">[Unauthorized] Missing or invalid sandbox token. Click the 🔒 button to set it.</span>`;
      metricStatus.textContent = "Locked";
      metricStatus.className = "metric error";
      return;
    }

    if (res.status === 429 || res.status === 503) {
      const info = await res.json().catch(() => ({}));
      terminalOutput.innerHTML = `<span style="color: #d29922;">[${res.status === 429 ? "Rate Limited" : "Sandbox Busy"}] ${info.error || "Please retry shortly."}</span>`;
      metricStatus.textContent = res.status === 429 ? "Throttled" : "Busy";
      metricStatus.className = "metric tle";
      return;
    }

    const data = await res.json();
    renderOutput(data);
  } catch (err) {
    terminalOutput.innerHTML = `<span style="color: #f85149;">[Network / API Error]: ${err.message}</span>`;
    metricStatus.textContent = "Error";
    metricStatus.className = "metric error";
  } finally {
    isExecuting = false;
    runBtn.disabled = false;
    runBtn.innerHTML = `
      <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
      <span>Run Code</span>
      <kbd class="shortcut">Ctrl+↵</kbd>
    `;
    typingIndicator.textContent = "idle";
    typingIndicator.className = "editor-indicator done";
  }
}

runBtn.addEventListener("click", runCode);

const tokenBtn = document.getElementById("token-btn");
if (tokenBtn) {
  const syncTokenUi = () => {
    const hasToken = Boolean(localStorage.getItem("runcplus_token"));
    tokenBtn.textContent = hasToken ? "🔓" : "🔒";
    tokenBtn.classList.toggle("locked", !hasToken);
    tokenBtn.title = hasToken
      ? "Sandbox token set — click to replace"
      : "Set sandbox access token";
  };

  tokenBtn.addEventListener("click", () => {
    const current = localStorage.getItem("runcplus_token") || "";
    const entered = prompt(
      "RunCplus sandbox access token:\n(leave empty to clear the saved token)",
      current
    );
    if (entered === null) return;
    const trimmed = entered.trim();
    if (trimmed) localStorage.setItem("runcplus_token", trimmed);
    else localStorage.removeItem("runcplus_token");
    syncTokenUi();
  });

  syncTokenUi();
}

function renderOutput(data) {
  // Update Metrics
  if (data.status === "success") {
    metricStatus.textContent = `Exit Code 0`;
    metricStatus.className = "metric success";
  } else if (data.status === "time_limit_exceeded") {
    metricStatus.textContent = `Watchdog TLE (2s)`;
    metricStatus.className = "metric tle";
  } else if (data.status === "compile_error") {
    metricStatus.textContent = `Build Error`;
    metricStatus.className = "metric error";
  } else {
    metricStatus.textContent = `Error (${data.exit_code || -1})`;
    metricStatus.className = "metric error";
  }

  metricCompile.textContent = `Comp: ${data.compile_duration_ms}ms`;
  metricExec.textContent = `Exec: ${data.execution_duration_ms}ms`;
  metricCache.textContent = data.cached ? "Cache: Hit (0ms)" : "Cache: Miss";

  // Build terminal output
  let out = "";
  if (data.stdout) {
    out += escapeHtml(data.stdout);
  }
  if (data.stderr) {
    if (out) out += "\n\n";
    out += `<span style="color: #ff7b72;">${escapeHtml(data.stderr)}</span>`;
  }
  if (!out) {
    out = `<span class="terminal-dim">[Program exited cleanly with no output]</span>`;
  }

  terminalOutput.innerHTML = out;
  terminalOutput.scrollTop = terminalOutput.scrollHeight;

  // Diagnostics Drawer
  if (data.diagnostics && data.diagnostics.length > 0) {
    let diagHtml = "";
    data.diagnostics.forEach((d) => {
      diagHtml += `<div class="diag-item"><span class="diag-line">Line ${d.line}:${d.column}</span> [${d.type}] ${escapeHtml(d.message)}</div>`;
    });
    diagList.innerHTML = diagHtml;
    diagBar.style.display = "block";
  } else {
    diagBar.style.display = "none";
  }
}

diagClose.addEventListener("click", () => {
  diagBar.style.display = "none";
});

function escapeHtml(str) {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// Fetch backend status
async function checkBackendStatus() {
  try {
    const res = await fetch("/api/status");
    const data = await res.json();
    if (data.compiler) {
      document.getElementById("status-compiler").querySelector(".label").textContent = data.compiler.split(" (")[0] + " (C++20)";
    }
  } catch (e) {
    console.warn("Could not retrieve backend status:", e);
  }
}

// Initialize on page load
window.addEventListener("DOMContentLoaded", () => {
  codeEditor.value = TEMPLATES.hello;
  updateLineNumbers();
  updateCursorPosition();
  checkBackendStatus();
  runCode();
});
