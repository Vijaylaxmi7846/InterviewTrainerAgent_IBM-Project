/**
 * dashboard.js — Progress dashboard with Chart.js visualizations
 */
document.addEventListener("DOMContentLoaded", () => {
  loadStatus();
  loadSession();
  bindDashUpload();
});

// ─────────────────────────────────────────────────────────────────────────────
//  System Status
// ─────────────────────────────────────────────────────────────────────────────
async function loadStatus() {
  try {
    const res  = await fetch("/api/status");
    const data = await res.json();

    const ragEl    = document.getElementById("ragStatus");
    const wxEl     = document.getElementById("watsonxStatus");
    const chunkEl  = document.getElementById("ragChunks");
    const modelEl  = document.getElementById("modelId");

    if (ragEl) {
      ragEl.textContent = data.rag_ready ? "Online" : "Building";
      ragEl.className   = `sys-badge ${data.rag_ready ? "ok" : "warning"}`;
    }
    if (wxEl) {
      wxEl.textContent = data.watsonx_live ? "Connected" : "Demo Mode";
      wxEl.className   = `sys-badge ${data.watsonx_live ? "ok" : "warning"}`;
    }
    if (chunkEl) {
      chunkEl.textContent = data.rag_chunks + " chunks";
    }
    if (modelEl) {
      const shortModel = (data.model || "").split("/").pop();
      modelEl.textContent = shortModel || "—";
    }

    // Demo mode banner
    if (data.demo_mode) {
      const banner = document.getElementById("statusBanner");
      const bannerText = document.getElementById("statusBannerText");
      if (banner && bannerText) {
        bannerText.textContent =
          "Running in Demo Mode. Add your IBM Cloud API Key to .env to activate Watsonx.ai.";
        banner.classList.remove("d-none");
      }
    }
  } catch {}
}

// ─────────────────────────────────────────────────────────────────────────────
//  Session Data
// ─────────────────────────────────────────────────────────────────────────────
async function loadSession() {
  try {
    const res  = await fetch("/api/session");
    const data = await res.json();
    renderDashboard(data);
  } catch {}
}

function renderDashboard(data) {
  const {
    questions_asked = 0,
    avg_score       = 0,
    target_role     = "—",
    experience_level= "—",
    scores          = [],
    question_types  = {},
    phase           = "—",
  } = data;

  // ── KPI Cards ──────────────────────────────────────────────────────────────
  setText("kpiQuestions", questions_asked);
  setText("kpiAvgScore",  avg_score ? `${avg_score} / 5` : "—");
  setText("kpiRole",      truncate(target_role, 16));
  setText("kpiLevel",     capitalize(experience_level));

  if (questions_asked > 0) {
    setText("kpiQTrend",  `${questions_asked} answered`);
  }
  if (avg_score >= 4) {
    const t = document.getElementById("kpiScoreTrend");
    if (t) { t.textContent = "🔥 Strong performance!"; t.style.color = "var(--accent-green)"; }
  } else if (avg_score > 0) {
    const t = document.getElementById("kpiScoreTrend");
    if (t) { t.textContent = "Keep practicing!"; }
  }

  // Phase labels
  setText("sessionPhase",  capitalize(phase));
  setText("sessionPhase2", capitalize(phase));

  // Performance breakdown
  const best   = scores.length ? Math.max(...scores)        : null;
  const latest = scores.length ? scores[scores.length - 1]  : null;
  const left   = Math.max(0, 5 - questions_asked);

  setText("bestScore",   best   ? `${best} / 5`   : "—");
  setText("latestScore", latest ? `${latest} / 5` : "—");
  setText("qLeft",       left > 0 ? left : "Done! 🎉");

  // ── Gauge ─────────────────────────────────────────────────────────────────
  const readiness = Math.round((avg_score / 5) * 100);
  const gaugeEl   = document.getElementById("gaugeFill");
  const gaugeVal  = document.getElementById("gaugeVal");
  if (gaugeEl) {
    const maxDash = 251;
    const offset  = maxDash - (readiness / 100) * maxDash;
    gaugeEl.style.strokeDashoffset = offset;

    const color = readiness >= 80 ? "var(--accent-green)"
                : readiness >= 60 ? "var(--accent-teal)"
                : readiness >= 40 ? "var(--accent-yellow)"
                : "var(--accent-orange)";
    gaugeEl.style.stroke = color;
  }
  if (gaugeVal) gaugeVal.textContent = `${readiness}%`;

  // ── Charts ────────────────────────────────────────────────────────────────
  renderScoreChart(scores);
  renderQTypeChart(question_types);
  renderScoreDistribution(scores);

  // ── Tips ──────────────────────────────────────────────────────────────────
  renderTips(avg_score, scores, question_types);
}

// ─────────────────────────────────────────────────────────────────────────────
//  Score Progression Chart
// ─────────────────────────────────────────────────────────────────────────────
let scoreChartInstance = null;

function renderScoreChart(scores) {
  const canvas  = document.getElementById("scoreChart");
  const empty   = document.getElementById("chartEmpty");
  if (!canvas) return;

  if (!scores || scores.length === 0) {
    canvas.style.display = "none";
    empty?.classList.remove("d-none");
    return;
  }

  empty?.classList.add("d-none");
  canvas.style.display = "";

  const labels = scores.map((_, i) => `Q${i + 1}`);
  const isDark = document.documentElement.getAttribute("data-bs-theme") === "dark";
  const gridColor = isDark ? "rgba(255,255,255,.07)" : "rgba(0,0,0,.07)";
  const textColor = isDark ? "#8b949e" : "#57606a";

  if (scoreChartInstance) scoreChartInstance.destroy();

  scoreChartInstance = new Chart(canvas, {
    type: "line",
    data: {
      labels,
      datasets: [{
        label: "Score",
        data: scores,
        borderColor: "#3b82f6",
        backgroundColor: "rgba(59,130,246,.15)",
        borderWidth: 2.5,
        pointBackgroundColor: scores.map(s =>
          s >= 4 ? "#22c55e" : s === 3 ? "#eab308" : "#ef4444"
        ),
        pointRadius: 6,
        pointHoverRadius: 8,
        fill: true,
        tension: 0.4,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: ctx => ` Score: ${ctx.parsed.y} / 5`,
          },
        },
      },
      scales: {
        y: {
          min: 0, max: 5,
          ticks: { stepSize: 1, color: textColor },
          grid:  { color: gridColor },
        },
        x: {
          ticks: { color: textColor },
          grid:  { color: gridColor },
        },
      },
    },
  });
}

// ─────────────────────────────────────────────────────────────────────────────
//  Question Type Donut Chart
// ─────────────────────────────────────────────────────────────────────────────
let qTypeChartInstance = null;

function renderQTypeChart(qt) {
  const canvas = document.getElementById("qTypeChart");
  const empty  = document.getElementById("qTypeEmpty");
  const legend = document.getElementById("qTypeLegend");
  if (!canvas) return;

  const total = (qt.technical || 0) + (qt.behavioral || 0) + (qt.situational || 0);

  if (total === 0) {
    canvas.style.display = "none";
    empty?.classList.remove("d-none");
    return;
  }

  empty?.classList.add("d-none");
  canvas.style.display = "";

  const labels = ["Technical", "Behavioral", "Situational"];
  const values = [qt.technical || 0, qt.behavioral || 0, qt.situational || 0];
  const colors = ["#3b82f6", "#8b5cf6", "#14b8a6"];

  if (qTypeChartInstance) qTypeChartInstance.destroy();

  qTypeChartInstance = new Chart(canvas, {
    type: "doughnut",
    data: {
      labels,
      datasets: [{
        data: values,
        backgroundColor: colors,
        borderWidth: 0,
        hoverOffset: 6,
      }],
    },
    options: {
      responsive: false,
      cutout: "65%",
      plugins: {
        legend: { display: false },
      },
    },
  });

  // Legend
  if (legend) {
    legend.innerHTML = labels.map((lbl, i) => `
      <div class="qtype-leg-item">
        <div class="qtype-dot" style="background:${colors[i]}"></div>
        <span>${lbl}: ${values[i]}</span>
      </div>
    `).join("");
  }
}

// ─────────────────────────────────────────────────────────────────────────────
//  Score Distribution Bars
// ─────────────────────────────────────────────────────────────────────────────
function renderScoreDistribution(scores) {
  const container = document.getElementById("scoreDist");
  const empty     = document.getElementById("distEmpty");
  if (!container) return;

  if (!scores || scores.length === 0) {
    container.innerHTML = "";
    empty?.classList.remove("d-none");
    return;
  }
  empty?.classList.add("d-none");

  const counts = { 5: 0, 4: 0, 3: 0, 2: 0, 1: 0 };
  scores.forEach(s => { if (counts[s] !== undefined) counts[s]++; });
  const max = Math.max(...Object.values(counts), 1);

  const colors = {
    5: "var(--accent-green)",
    4: "var(--accent-teal)",
    3: "var(--accent-yellow)",
    2: "var(--accent-orange)",
    1: "var(--accent-red)",
  };

  container.innerHTML = [5, 4, 3, 2, 1].map(s => `
    <div class="sdb-row">
      <div class="sdb-label">${s}★</div>
      <div class="sdb-bar-wrap">
        <div class="sdb-bar" style="width:${Math.round((counts[s]/max)*100)}%;background:${colors[s]}"></div>
      </div>
      <div class="sdb-count">${counts[s]}</div>
    </div>
  `).join("");
}

// ─────────────────────────────────────────────────────────────────────────────
//  Tips
// ─────────────────────────────────────────────────────────────────────────────
function renderTips(avg, scores, qt) {
  const grid  = document.getElementById("tipsGrid");
  const empty = document.getElementById("tipsEmpty");
  if (!grid) return;

  if (!scores || scores.length === 0) return;

  const tips = [];

  if (avg < 3) {
    tips.push({
      color: "var(--accent-orange)",
      title: "📚 Focus on STAR Method",
      body:  "Your scores suggest answers need more structure. Practice the Situation-Task-Action-Result framework for every behavioral question.",
    });
    tips.push({
      color: "var(--accent-blue)",
      title: "🔧 Review Fundamentals",
      body:  "For technical questions, revisit core concepts. Use the Quick Commands to generate a hint before answering.",
    });
  } else if (avg < 4) {
    tips.push({
      color: "var(--accent-teal)",
      title: "📊 Add Quantified Results",
      body:  "Your answers are good but need specific numbers. Instead of 'improved performance', say 'improved by 35%'.",
    });
    tips.push({
      color: "var(--accent-purple)",
      title: "🎤 Practice Out Loud",
      body:  "Enable Mock Mode and practice speaking your answers aloud within 2 minutes. Articulation matters as much as content.",
    });
  } else {
    tips.push({
      color: "var(--accent-green)",
      title: "🌟 Excellent Performance!",
      body:  "You're scoring well. Focus on making answers even more specific with concrete business impact and leadership examples.",
    });
    tips.push({
      color: "var(--accent-blue)",
      title: "🚀 Level Up with Advanced Topics",
      body:  "Push into system design, cross-functional leadership, and strategic thinking questions to prepare for senior interviews.",
    });
  }

  if ((qt.technical || 0) < (qt.behavioral || 0)) {
    tips.push({
      color: "var(--accent-yellow)",
      title: "⚡ Increase Technical Practice",
      body:  "You've answered more behavioral than technical questions. Balance your practice by focusing on technical depth in your role.",
    });
  }

  tips.push({
    color: "var(--accent-pink)",
    title: "🔄 Keep Practicing",
    body:  `You've completed ${scores.length} question${scores.length !== 1 ? "s" : ""}. Aim for at least 20 to build real confidence. Start a new session!`,
  });

  empty?.remove();
  grid.innerHTML = tips.map(t => `
    <div class="col-md-6">
      <div class="tip-card" style="border-left-color:${t.color}">
        <div class="tip-title">${t.title}</div>
        <div class="tip-body">${t.body}</div>
      </div>
    </div>
  `).join("");
}

// ─────────────────────────────────────────────────────────────────────────────
//  Dashboard Upload
// ─────────────────────────────────────────────────────────────────────────────
function bindDashUpload() {
  const zone   = document.getElementById("dashUploadZone");
  const input  = document.getElementById("dashFileInput");
  const msgDiv = document.getElementById("dashUploadMsg");

  if (!zone || !input) return;

  zone.addEventListener("click", () => input.click());
  input.addEventListener("change", async () => {
    const file = input.files[0];
    if (!file) return;

    msgDiv.textContent = "Uploading...";
    msgDiv.className   = "upload-msg mt-2 text-muted";
    msgDiv.classList.remove("d-none");

    const fd = new FormData();
    fd.append("file", file);

    try {
      const res  = await fetch("/api/upload", { method: "POST", body: fd });
      const data = await res.json();
      if (data.status === "ok") {
        msgDiv.textContent = `✅ ${data.message}`;
        msgDiv.className   = "upload-msg mt-2 text-success";
        // Refresh status
        setTimeout(loadStatus, 1000);
      } else {
        msgDiv.textContent = `❌ ${data.message}`;
        msgDiv.className   = "upload-msg mt-2 text-danger";
      }
    } catch {
      msgDiv.textContent = "❌ Upload failed.";
      msgDiv.className   = "upload-msg mt-2 text-danger";
    }
    input.value = "";
  });
}

// ─────────────────────────────────────────────────────────────────────────────
//  Utils
// ─────────────────────────────────────────────────────────────────────────────
function setText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

function truncate(str, len) {
  return str && str.length > len ? str.slice(0, len) + "…" : str || "—";
}

function capitalize(str) {
  if (!str) return "—";
  return str.charAt(0).toUpperCase() + str.slice(1).replace(/_/g, " ");
}
