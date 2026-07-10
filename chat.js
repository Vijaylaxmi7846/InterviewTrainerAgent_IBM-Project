/**
 * chat.js — Full chat UI with session management, timer, upload
 */

// ── marked.js configuration ──────────────────────────────────────────────────
if (typeof marked !== "undefined") {
  marked.setOptions({
    breaks: true,
    gfm: true,
    headerIds: false,
    mangle: false,
  });
}

// ── State ─────────────────────────────────────────────────────────────────────
const State = {
  sessionActive:  false,
  isLoading:      false,
  timerInterval:  null,
  timerSeconds:   120,
  timerRunning:   false,
  mockMode:       false,
  totalQuestions: 5,    // Updated from server
};

// ── DOM refs ──────────────────────────────────────────────────────────────────
const el = {
  chatMessages:   document.getElementById("chatMessages"),
  chatWelcome:    document.getElementById("chatWelcome"),
  startSessionBtn:document.getElementById("startSessionBtn"),
  chatInput:      document.getElementById("chatInput"),
  sendBtn:        document.getElementById("sendBtn"),
  typingIndicator:document.getElementById("typingIndicator"),
  sidebarToggle:  document.getElementById("sidebarToggle"),
  chatSidebar:    document.getElementById("chatSidebar"),
  progressFill:   document.getElementById("progressFill"),
  progressPct:    document.getElementById("progressPct"),
  scoreTimeline:  document.getElementById("scoreTimeline"),
  siRole:         document.getElementById("siRole"),
  siExp:          document.getElementById("siExp"),
  siQCount:       document.getElementById("siQCount"),
  siScore:        document.getElementById("siScore"),
  topbarRole:     document.getElementById("topbarRole"),
  ragPill:        document.getElementById("ragPill"),
  demoPill:       document.getElementById("demoPill"),
  agentTagline:   document.getElementById("agentTagline"),
  agentStatusDot: document.getElementById("agentStatusDot"),
  mockTimer:      document.getElementById("mockTimer"),
  timerSection:   document.getElementById("timerSection"),
  timerStart:     document.getElementById("timerStart"),
  timerReset:     document.getElementById("timerReset"),
  mockModeToggle: document.getElementById("mockModeToggle"),
  clearChat:      document.getElementById("clearChat"),
  uploadTrigger:  document.getElementById("uploadTrigger"),
  chatFileInput:  document.getElementById("chatFileInput"),
  uploadToast:    document.getElementById("uploadToast"),
  uploadToastMsg: document.getElementById("uploadToastMsg"),
};

// ═════════════════════════════════════════════════════════════════════════════
//  Initialise
// ═════════════════════════════════════════════════════════════════════════════
document.addEventListener("DOMContentLoaded", () => {
  checkStatus();
  bindEvents();
});

function checkStatus() {
  fetch("/api/status")
    .then(r => r.json())
    .then(data => {
      if (data.demo_mode && el.demoPill) {
        el.demoPill.classList.remove("d-none");
      }
      if (!data.rag_ready && el.ragPill) {
        el.ragPill.style.opacity = ".4";
        el.ragPill.title = "RAG building...";
      }
    })
    .catch(() => {});
}

// ═════════════════════════════════════════════════════════════════════════════
//  Event Binding
// ═════════════════════════════════════════════════════════════════════════════
function bindEvents() {
  // Start session
  el.startSessionBtn?.addEventListener("click", startSession);

  // Send message
  el.sendBtn?.addEventListener("click", sendMessage);
  el.chatInput?.addEventListener("keydown", e => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  // Auto-resize textarea
  el.chatInput?.addEventListener("input", () => {
    el.chatInput.style.height = "auto";
    el.chatInput.style.height = Math.min(el.chatInput.scrollHeight, 160) + "px";
    updateSendBtn();
  });

  // Sidebar toggle
  el.sidebarToggle?.addEventListener("click", toggleSidebar);

  // Quick commands
  document.querySelectorAll(".qcmd-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const cmd = btn.dataset.cmd;
      if (cmd && State.sessionActive) sendUserMessage(cmd);
    });
  });

  // Mock mode toggle
  el.mockModeToggle?.addEventListener("click", toggleMockMode);

  // Timer
  el.timerStart?.addEventListener("click", toggleTimer);
  el.timerReset?.addEventListener("click", resetTimer);

  // Clear chat
  el.clearChat?.addEventListener("click", () => {
    if (confirm("Clear chat messages? Session data is preserved.")) {
      const msgs = el.chatMessages.querySelectorAll(".message");
      msgs.forEach(m => m.remove());
    }
  });

  // Upload
  el.uploadTrigger?.addEventListener("click", () => el.chatFileInput?.click());
  el.chatFileInput?.addEventListener("change", () => {
    const file = el.chatFileInput.files[0];
    if (file) uploadDocument(file);
  });

  // Mobile sidebar close on overlay click
  document.addEventListener("click", e => {
    if (window.innerWidth < 992
      && el.chatSidebar?.classList.contains("mobile-open")
      && !el.chatSidebar.contains(e.target)
      && e.target !== el.sidebarToggle) {
      el.chatSidebar.classList.remove("mobile-open");
    }
  });
}

// ═════════════════════════════════════════════════════════════════════════════
//  Session Start
// ═════════════════════════════════════════════════════════════════════════════
async function startSession() {
  el.startSessionBtn.disabled = true;
  el.startSessionBtn.innerHTML = '<span class="spin me-2">⚙</span>Starting...';

  try {
    const res  = await fetch("/api/start", { method: "POST" });
    const data = await res.json();

    if (data.status === "ok") {
      State.sessionActive = true;
      el.chatWelcome?.remove();

      // Enable input
      el.chatInput.disabled = false;
      el.sendBtn.disabled   = false;
      el.chatInput.focus();

      // Render greeting
      appendMessage("assistant", data.message);
      el.agentTagline.textContent = "Interviewing you now...";
    }
  } catch (err) {
    console.error(err);
    el.startSessionBtn.disabled = false;
    el.startSessionBtn.innerHTML = '<i class="bi bi-play-circle-fill me-2"></i>Start Session';
    showToast("Failed to start session. Please try again.", "danger");
  }
}

// ═════════════════════════════════════════════════════════════════════════════
//  Send Message
// ═════════════════════════════════════════════════════════════════════════════
function sendMessage() {
  const text = el.chatInput.value.trim();
  if (!text || State.isLoading || !State.sessionActive) return;
  sendUserMessage(text);
  el.chatInput.value = "";
  el.chatInput.style.height = "auto";
  updateSendBtn();
}

async function sendUserMessage(text) {
  if (State.isLoading) return;

  // Stop timer on answer
  if (State.timerRunning) stopTimer();

  appendMessage("user", text);
  showTyping(true);
  State.isLoading = true;
  updateSendBtn();

  try {
    const res  = await fetch("/api/chat", {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ message: text }),
    });
    const data = await res.json();

    showTyping(false);
    State.isLoading = false;
    updateSendBtn();

    if (data.status === "ok") {
      appendMessage("assistant", data.message);
      updateProgress(data.progress);

      // Auto-start timer in mock mode for next question
      if (State.mockMode) {
        resetTimer();
        startTimerCountdown();
      }
    } else {
      appendMessage("assistant", "⚠️ Something went wrong. Please try again.");
    }
  } catch (err) {
    console.error(err);
    showTyping(false);
    State.isLoading = false;
    updateSendBtn();
    appendMessage("assistant", "❌ Connection error. Check the server and try again.");
  }
}

// ═════════════════════════════════════════════════════════════════════════════
//  Message Rendering
// ═════════════════════════════════════════════════════════════════════════════
function appendMessage(role, content) {
  const isAI   = role === "assistant";
  const time   = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  const msgDiv = document.createElement("div");
  msgDiv.className = `message ${isAI ? "ai" : "user"}`;

  const rendered = isAI && typeof marked !== "undefined"
    ? marked.parse(content)
    : escapeHtml(content).replace(/\n/g, "<br>");

  msgDiv.innerHTML = `
    <div class="msg-avatar ${isAI ? "ai-av" : "user-av"}">
      <i class="bi ${isAI ? "bi-robot" : "bi-person-fill"}"></i>
    </div>
    <div class="msg-content">
      <div class="msg-sender">${isAI ? "Interview Trainer AI" : "You"}</div>
      <div class="msg-bubble">${rendered}</div>
      <div class="msg-time">${time}</div>
    </div>
  `;

  el.chatMessages.appendChild(msgDiv);
  scrollToBottom();

  // Highlight code blocks
  if (typeof hljs !== "undefined") {
    msgDiv.querySelectorAll("pre code").forEach(block => hljs.highlightElement(block));
  }
}

function escapeHtml(text) {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function scrollToBottom() {
  el.chatMessages.scrollTo({ top: el.chatMessages.scrollHeight, behavior: "smooth" });
}

// ═════════════════════════════════════════════════════════════════════════════
//  Typing Indicator
// ═════════════════════════════════════════════════════════════════════════════
function showTyping(show) {
  if (!el.typingIndicator) return;
  if (show) {
    el.typingIndicator.classList.remove("d-none");
    scrollToBottom();
  } else {
    el.typingIndicator.classList.add("d-none");
  }
}

// ═════════════════════════════════════════════════════════════════════════════
//  Progress Update
// ═════════════════════════════════════════════════════════════════════════════
function updateProgress(progress) {
  if (!progress) return;

  const { questions_asked, total, scores, avg_score } = progress;
  State.totalQuestions = total || 5;

  // Sidebar counters
  if (el.siQCount)   el.siQCount.textContent   = questions_asked || 0;
  if (el.siScore)    el.siScore.textContent     = avg_score ? `${avg_score}/5` : "—";

  // Progress bar
  const pct = Math.round((questions_asked / State.totalQuestions) * 100);
  if (el.progressFill) el.progressFill.style.width = `${pct}%`;
  if (el.progressPct)  el.progressPct.textContent  = pct;

  // Score timeline badges
  if (el.scoreTimeline && scores?.length) {
    el.scoreTimeline.innerHTML = "";
    scores.forEach(s => {
      const badge = document.createElement("div");
      badge.className = `score-badge score-${s}`;
      badge.title = `Score: ${s}/5`;
      badge.textContent = s;
      el.scoreTimeline.appendChild(badge);
    });
  }

  // Fetch session info for role/level
  fetchSessionInfo();
}

async function fetchSessionInfo() {
  try {
    const res  = await fetch("/api/session");
    const data = await res.json();
    if (el.siRole)  el.siRole.textContent  = truncate(data.target_role || "—", 14);
    if (el.siExp)   el.siExp.textContent   = truncate(data.experience_level || "—", 10);
    if (el.topbarRole) el.topbarRole.textContent = data.target_role || "Interview Practice";
  } catch {}
}

// ═════════════════════════════════════════════════════════════════════════════
//  Send Button State
// ═════════════════════════════════════════════════════════════════════════════
function updateSendBtn() {
  const hasText = el.chatInput.value.trim().length > 0;
  el.sendBtn.disabled = !hasText || State.isLoading || !State.sessionActive;
}

// ═════════════════════════════════════════════════════════════════════════════
//  Sidebar
// ═════════════════════════════════════════════════════════════════════════════
function toggleSidebar() {
  if (window.innerWidth < 992) {
    el.chatSidebar.classList.toggle("mobile-open");
  } else {
    el.chatSidebar.classList.toggle("collapsed");
  }
}

// ═════════════════════════════════════════════════════════════════════════════
//  Mock Timer
// ═════════════════════════════════════════════════════════════════════════════
function toggleMockMode() {
  State.mockMode = !State.mockMode;
  el.timerSection.style.display = State.mockMode ? "block" : "none";
  el.mockModeToggle.classList.toggle("text-warning", State.mockMode);
  el.mockModeToggle.title = State.mockMode ? "Mock Mode ON — click to disable" : "Enable Mock Interview Mode";
}

function toggleTimer() {
  if (State.timerRunning) {
    stopTimer();
  } else {
    startTimerCountdown();
  }
}

function startTimerCountdown() {
  if (State.timerRunning) return;
  State.timerRunning = true;
  el.timerStart.textContent = "Pause";
  el.timerStart.className = "btn btn-sm btn-warning";

  State.timerInterval = setInterval(() => {
    State.timerSeconds--;
    updateTimerDisplay();
    if (State.timerSeconds <= 0) {
      clearInterval(State.timerInterval);
      State.timerRunning = false;
      el.timerStart.textContent = "Start";
      el.timerStart.className   = "btn btn-sm btn-timer-start";
      el.mockTimer.style.color  = "var(--accent-red)";
      appendMessage("assistant", "⏰ **Time's up!** In a real interview, you'd need to wrap up. What would your final answer be?");
    }
  }, 1000);
}

function stopTimer() {
  clearInterval(State.timerInterval);
  State.timerRunning = false;
  el.timerStart.textContent = "Resume";
  el.timerStart.className   = "btn btn-sm btn-timer-start";
}

function resetTimer() {
  clearInterval(State.timerInterval);
  State.timerRunning = false;
  State.timerSeconds = 120;
  updateTimerDisplay();
  el.timerStart.textContent = "Start";
  el.timerStart.className   = "btn btn-sm btn-timer-start";
  if (el.mockTimer) el.mockTimer.style.color = "";
}

function updateTimerDisplay() {
  const m = Math.floor(State.timerSeconds / 60);
  const s = State.timerSeconds % 60;
  el.mockTimer.textContent = `${m}:${s.toString().padStart(2, "0")}`;
  if (State.timerSeconds <= 20) {
    el.mockTimer.style.color = "var(--accent-red)";
  } else if (State.timerSeconds <= 40) {
    el.mockTimer.style.color = "var(--accent-orange)";
  }
}

// ═════════════════════════════════════════════════════════════════════════════
//  Document Upload
// ═════════════════════════════════════════════════════════════════════════════
async function uploadDocument(file) {
  const allowed = ["txt", "pdf", "docx", "md"];
  const ext = file.name.split(".").pop().toLowerCase();
  if (!allowed.includes(ext)) {
    showToast("File type not supported.", "danger");
    return;
  }

  appendMessage("assistant", `📎 Uploading **${file.name}** to knowledge base...`);

  const fd = new FormData();
  fd.append("file", file);

  try {
    const res  = await fetch("/api/upload", { method: "POST", body: fd });
    const data = await res.json();
    if (data.status === "ok") {
      appendMessage("assistant", `✅ **${file.name}** added! Indexed ${data.chunks_added} new chunks. Total knowledge base: ${data.total_chunks} chunks.`);
    } else {
      appendMessage("assistant", `❌ Upload failed: ${data.message}`);
    }
  } catch {
    appendMessage("assistant", "❌ Upload error. Please try again.");
  }

  el.chatFileInput.value = "";
}

// ═════════════════════════════════════════════════════════════════════════════
//  Helpers
// ═════════════════════════════════════════════════════════════════════════════
function showToast(msg, type = "success") {
  if (!el.uploadToast) return;
  el.uploadToastMsg.textContent = msg;
  el.uploadToast.className = `toast align-items-center text-bg-${type} border-0`;
  const bsToast = new bootstrap.Toast(el.uploadToast, { delay: 3500 });
  bsToast.show();
}

function truncate(str, len) {
  return str && str.length > len ? str.slice(0, len) + "…" : str;
}
