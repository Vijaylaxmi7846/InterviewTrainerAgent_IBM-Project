/**
 * app.js — Global utilities: theme toggle, shared helpers
 */

// ── Theme Toggle ──────────────────────────────────────────────────────────────
(function () {
  const THEME_KEY = "it-theme";
  const htmlEl    = document.documentElement;
  const saved     = localStorage.getItem(THEME_KEY) || "dark";

  function applyTheme(theme) {
    htmlEl.setAttribute("data-bs-theme", theme);
    const icon = document.getElementById("themeIcon");
    if (icon) {
      icon.className = theme === "dark" ? "bi bi-sun-fill" : "bi bi-moon-stars-fill";
    }
    localStorage.setItem(THEME_KEY, theme);
  }

  applyTheme(saved);

  document.addEventListener("DOMContentLoaded", () => {
    const btn = document.getElementById("themeToggle");
    if (btn) {
      btn.addEventListener("click", () => {
        const current = htmlEl.getAttribute("data-bs-theme");
        applyTheme(current === "dark" ? "light" : "dark");
      });
    }
  });
})();

// ── Shared upload helper (landing page) ──────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  const zone      = document.getElementById("uploadZone");
  const input     = document.getElementById("fileInput");
  const statusDiv = document.getElementById("uploadStatus");
  const barFill   = document.getElementById("uploadBar");
  const msgDiv    = document.getElementById("uploadMessage");

  if (!zone || !input) return;

  // Drag & drop
  ["dragenter", "dragover"].forEach(ev => {
    zone.addEventListener(ev, e => { e.preventDefault(); zone.classList.add("drag-over"); });
  });
  ["dragleave", "drop"].forEach(ev => {
    zone.addEventListener(ev, e => { e.preventDefault(); zone.classList.remove("drag-over"); });
  });
  zone.addEventListener("drop", e => {
    const file = e.dataTransfer.files[0];
    if (file) uploadFile(file);
  });

  input.addEventListener("change", () => {
    if (input.files[0]) uploadFile(input.files[0]);
  });

  function uploadFile(file) {
    const allowed = ["txt", "pdf", "docx", "md"];
    const ext = file.name.split(".").pop().toLowerCase();
    if (!allowed.includes(ext)) {
      showMsg("❌ File type not supported. Use TXT, PDF, DOCX, or MD.", "text-danger");
      return;
    }
    statusDiv.classList.remove("d-none");
    barFill.style.animation = "progress-anim 2s ease forwards";

    const fd = new FormData();
    fd.append("file", file);

    fetch("/api/upload", { method: "POST", body: fd })
      .then(r => r.json())
      .then(data => {
        if (data.status === "ok") {
          showMsg(`✅ ${data.message}`, "text-success");
        } else {
          showMsg(`❌ ${data.message}`, "text-danger");
        }
      })
      .catch(() => showMsg("❌ Upload failed. Check your connection.", "text-danger"));
  }

  function showMsg(text, cls) {
    if (!msgDiv) return;
    msgDiv.textContent = text;
    msgDiv.className = `upload-msg mt-2 ${cls}`;
  }
});
