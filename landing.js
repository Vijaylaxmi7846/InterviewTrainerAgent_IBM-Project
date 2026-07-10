/**
 * landing.js — Landing page animations and interactions
 */
document.addEventListener("DOMContentLoaded", () => {

  // ── Intersection Observer for reveal animations ──────────────────────────
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add("slide-up");
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.12, rootMargin: "0px 0px -40px 0px" });

  document.querySelectorAll(
    ".feature-card, .step-card, .kpi-card, .section-title, .section-subtitle"
  ).forEach(el => observer.observe(el));

  // ── Check system status and show RAG badge ────────────────────────────────
  fetch("/api/status")
    .then(r => r.json())
    .then(data => {
      // Could update a live indicator on landing if desired
      if (data.demo_mode) {
        const banner = document.createElement("div");
        banner.className = "alert alert-warning alert-dismissible fade show m-3";
        banner.style.cssText = "position:fixed;bottom:1rem;right:1rem;z-index:9999;max-width:380px;font-size:.85rem;";
        banner.innerHTML = `
          <strong>🔧 Demo Mode Active</strong><br>
          IBM Watsonx credentials not configured. Add them to <code>.env</code> for live AI responses.
          <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        `;
        document.body.appendChild(banner);
        setTimeout(() => banner.remove(), 8000);
      }
    })
    .catch(() => {});
});
