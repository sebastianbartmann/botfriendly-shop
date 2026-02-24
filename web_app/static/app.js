(function () {
  const context = window.SCAN_CONTEXT;
  if (!context || !context.scanId) {
    return;
  }

  const gradeEl = document.getElementById("grade");
  const overallScoreBar = document.getElementById("overall-score-bar");
  const overallScoreText = document.getElementById("overall-score-text");
  const checkGrid = document.getElementById("check-grid");
  const loadingState = document.getElementById("loading-state");
  const errorBox = document.getElementById("error-box");

  const severityColor = {
    pass: "#22c55e",
    partial: "#eab308",
    fail: "#ef4444",
    inconclusive: "#6b7280",
  };

  function clampScore(score) {
    if (typeof score !== "number" || Number.isNaN(score)) return 0;
    if (score < 0) return 0;
    if (score > 1) return 1;
    return score;
  }

  function categoryLabel(category, fallback) {
    return fallback || context.labels[category] || category.replaceAll("_", " ");
  }

  function makeList(items, emptyText) {
    if (!items || !items.length) {
      return `<li>${emptyText}</li>`;
    }
    return items.map((item) => `<li>${item}</li>`).join("");
  }

  function renderRobotsSignals(payload) {
    const details = payload.details || {};
    const tiers = details.tiers || {};
    const blockedOperators = details.blocked_operators || [];
    const order = ["agent", "crawler"];
    const tierRows = [];

    order.forEach((tierKey) => {
      const stats = tiers[tierKey];
      if (!stats) return;
      const label = stats.label || tierKey;
      const allowed = Number(stats.allowed || 0);
      const blocked = Number(stats.blocked || 0);
      const notMentioned = Number(stats.not_mentioned || 0);
      const total = Number(stats.total || 0);
      tierRows.push(
        `<li><span class="tier-label">${label}:</span> ` +
          `<span class="signal-pass">${allowed}/${total} allowed</span> ` +
          `<span class="signal-fail">${blocked} blocked</span> ` +
          `<span class="signal-muted">${notMentioned} not mentioned</span></li>`
      );
    });

    if (!tierRows.length) {
      return makeList([], "No signal details provided");
    }

    const blockedLine = blockedOperators.length
      ? `<span class="signal-fail">${blockedOperators.join(", ")}</span>`
      : `<span class="signal-pass">None</span>`;
    tierRows.push(`<li><span class="tier-label">Blocked operators:</span> ${blockedLine}</li>`);
    return tierRows.join("");
  }

  function renderCheckCard(payload) {
    const score = clampScore(payload.score);
    const scorePercent = Math.round(score * 100);
    const severity = (payload.severity || "inconclusive").toLowerCase();

    const signals =
      payload.category === "robots"
        ? renderRobotsSignals(payload)
        : makeList(
            (payload.signals || []).slice(0, 3).map((sig) => {
              const value = typeof sig.value === "object" ? JSON.stringify(sig.value) : String(sig.value);
              return `${sig.name}: ${value}`;
            }),
            "No signal details provided"
          );

    const card = document.createElement("article");
    card.className = "check-card";
    card.innerHTML = `
      <div class="check-top">
        <h3 class="check-title">${categoryLabel(payload.category, payload.category_label)}</h3>
        <span class="badge ${severity}">${severity}</span>
      </div>
      <div class="tiny-track">
        <div class="tiny-fill" style="background: ${severityColor[severity] || severityColor.inconclusive}; width: 0%;"></div>
      </div>
      <ul class="signal-list">${signals}</ul>
      <ul class="reco-list">${makeList(payload.recommendations || [], "No recommendations")}</ul>
    `;
    checkGrid.appendChild(card);

    requestAnimationFrame(() => {
      const bar = card.querySelector(".tiny-fill");
      if (bar) {
        bar.style.width = `${scorePercent}%`;
      }
    });
  }

  function updateOverall(score, grade) {
    const normalized = clampScore(score);
    const scorePercent = Math.round(normalized * 100);
    gradeEl.textContent = grade;
    gradeEl.classList.remove("pending");
    overallScoreBar.style.width = `${scorePercent}%`;
    overallScoreText.textContent = `${scorePercent}% overall readiness`;
  }

  function setError(message) {
    loadingState.classList.add("hidden");
    errorBox.classList.remove("hidden");
    errorBox.textContent = message;
  }

  const stream = new EventSource(`/api/stream/${context.scanId}`);

  stream.onmessage = function (event) {
    let payload;
    try {
      payload = JSON.parse(event.data);
    } catch (_) {
      setError("Received malformed scan event.");
      stream.close();
      return;
    }

    if (payload.type === "start") {
      overallScoreText.textContent = `Starting ${payload.check_count} checks...`;
      return;
    }

    if (payload.type === "check") {
      renderCheckCard(payload);
      return;
    }

    if (payload.type === "complete") {
      updateOverall(payload.overall_score, payload.grade);
      loadingState.classList.add("hidden");
      stream.close();
      return;
    }

    if (payload.type === "error") {
      setError(payload.message || "Scan failed.");
      stream.close();
    }
  };

  stream.onerror = function () {
    setError("Connection lost while streaming results. Reload to retry.");
    stream.close();
  };
})();
