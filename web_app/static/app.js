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
  let skeletonCard = null;

  const severityColor = {
    pass: "#306230",
    partial: "#92820A",
    fail: "#b91c1c",
    inconclusive: "#6b7280",
  };

  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

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
      return `<li>${escapeHtml(emptyText)}</li>`;
    }
    return items.map((item) => `<li>${escapeHtml(item)}</li>`).join("");
  }

  function severityBadge(severity) {
    const normalized = String(severity || "inconclusive").toLowerCase();
    return normalized in severityColor ? normalized : "inconclusive";
  }

  function boolLabel(value) {
    return value ? "Yes" : "No";
  }

  function renderRobotsSignals(payload) {
    const details = payload.details || {};
    const tiers = details.tiers || {};
    const blockedOperators = details.blocked_operators || [];
    const order = ["agent", "search_indexer", "training_crawler"];
    const tierRows = [];

    order.forEach((tierKey) => {
      const stats = tiers[tierKey];
      if (!stats) return;
      const label = escapeHtml(stats.label || tierKey);
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
      ? `<span class="signal-fail">${blockedOperators.map((operator) => escapeHtml(operator)).join(", ")}</span>`
      : `<span class="signal-pass">None</span>`;
    tierRows.push(`<li><span class="tier-label">Blocked operators:</span> ${blockedLine}</li>`);
    return tierRows.join("");
  }

  function summarizeDetails(payload) {
    const category = payload.category;
    const details = payload.details || {};

    if (category === "robots") {
      const overall = details.overall || {};
      const total = Number(overall.total || 0);
      return [
        `Coverage: ${overall.allowed || 0}/${total || 0} bots allowed`,
        `Blocked bots: ${overall.blocked || 0}`,
        `Not mentioned: ${overall.not_mentioned || 0}`,
        details.status_code ? `robots.txt status: ${details.status_code}` : "robots.txt status unavailable",
      ];
    }

    if (category === "discovery") {
      const paths = details.paths || details;
      const entries = Object.entries(paths).filter(([, value]) => value && typeof value === "object");
      const reachable = entries.filter(([, value]) => value.reachable !== false).length;
      const found = entries.filter(([, value]) => Number(value.status_code) === 200).length;
      return [
        `Discovery files found: ${found}/${entries.length}`,
        `Reachable endpoints: ${reachable}/${entries.length}`,
        ...entries.slice(0, 3).map(([path, value]) => `${path}: status ${value.status_code ?? "n/a"}`),
      ];
    }

    if (category === "sitemap") {
      return [
        `sitemap.xml status: ${details.status_code ?? "n/a"}`,
        `Sitemap URLs: ${details.url_count ?? 0}`,
        `Nested sitemaps: ${details.sitemap_count ?? 0}`,
        `Fresh lastmod (<=30 days): ${boolLabel(!!details.fresh_lastmod)}`,
        `Declared in robots.txt: ${boolLabel(!!details.robots_sitemap_directive)}`,
      ];
    }

    if (category === "structured_data") {
      const schemaTypes = details.schema_types || [];
      const actionTypes = details.action_schema_types || [];
      return [
        `JSON-LD blocks: ${details.json_ld_block_count ?? 0}`,
        `Schema types: ${schemaTypes.length ? schemaTypes.join(", ") : "none found"}`,
        `Agent action types: ${actionTypes.length ? actionTypes.join(", ") : "none"}`,
        `Open Graph tags found: ${(details.open_graph_tags || []).length}`,
        `Malformed JSON-LD blocks: ${details.malformed_json_ld_blocks ?? 0}`,
      ];
    }

    if (category === "seo_meta") {
      return [
        `Title length: ${details.title_length ?? 0}`,
        `Description length: ${details.description_length ?? 0}`,
        `Canonical tag present: ${boolLabel(!!details.canonical)}`,
        `HTML lang present: ${boolLabel(!!details.language)}`,
        `Viewport meta present: ${boolLabel(!!details.viewport)}`,
        `H1 count: ${details.h1_count ?? 0}`,
      ];
    }

    if (category === "feeds") {
      const feeds = details.alternate_feed_hrefs || [];
      const structured = details.structured_feed_hrefs || [];
      return [
        `Alternate feed links: ${feeds.length}`,
        `Product-oriented feed hints: ${structured.length}`,
        `Google Shopping hints in HTML: ${boolLabel(!!details.google_shopping_hint)}`,
        ...feeds.slice(0, 2).map((href) => `Feed URL: ${href}`),
      ];
    }

    if (category === "api_surface") {
      const specFound = details.spec_found || {};
      const foundSpecs = Object.values(specFound).filter(Boolean).length;
      const totalSpecs = Object.keys(specFound).length;
      return [
        `OpenAPI/Swagger specs found: ${foundSpecs}/${totalSpecs}`,
        `GraphQL OPTIONS status: ${details.graphql_options_status ?? "n/a"}`,
        `API/doc links on page: ${(details.doc_links || []).length}`,
      ];
    }

    if (category === "product_parseability") {
      return [
        `Schema includes Product: ${boolLabel((details.schema_types || []).includes("Product"))}`,
        `JSON-LD product fields complete: ${boolLabel(!!details.jsonld_name && !!details.jsonld_price && !!details.jsonld_availability)}`,
        `Price consistency: ${boolLabel(!!details.price_consistent)}`,
        `H1 count: ${details.h1_count ?? 0}`,
        `Price elements in HTML: ${details.price_element_count ?? 0}`,
      ];
    }

    if (category === "semantic_html") {
      const heading = details.heading_hierarchy || {};
      const nav = details.semantic_navigation_lists || {};
      const csr = details.csr_trap || {};
      const waf = details.waf_interference || {};
      return [
        `Semantic elements used: ${(details.semantic_elements_used || []).length}/7`,
        `Heading structure: ${heading.summary || "n/a"}`,
        `Navigation semantics: ${nav.summary || "n/a"}`,
        `CSR shell likely: ${boolLabel(!!csr.likely_csr_shell)}`,
        `WAF/challenge detected: ${boolLabel(!!waf.blocked_or_challenged)}`,
      ];
    }

    if (category === "accessibility") {
      const alt = details.image_alt_text || {};
      const landmarks = details.landmarks || {};
      const forms = details.form_labels || {};
      const links = details.link_quality || {};
      const tables = details.table_accessibility || {};
      return [
        `Image alt coverage: ${alt.with_alt ?? 0}/${alt.total_images ?? 0}`,
        `Landmarks present: ${landmarks.present_count ?? 0}/4`,
        `Labeled form inputs: ${forms.labeled_inputs ?? 0}/${forms.total_inputs ?? 0}`,
        `Descriptive links: ${links.descriptive_links ?? 0}/${links.total_links ?? 0}`,
        `Accessible tables: ${tables.accessible_tables ?? 0}/${tables.table_count ?? 0}`,
      ];
    }

    return (payload.signals || []).map((sig) => {
      const value = typeof sig.value === "object" ? JSON.stringify(sig.value) : String(sig.value);
      return `${sig.name}: ${value}`;
    });
  }

  function renderCheckCard(payload) {
    const score = clampScore(payload.score);
    const scorePercent = Math.round(score * 100);
    const severity = severityBadge(payload.severity);

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

    const details = summarizeDetails(payload);
    const detailsList = makeList(details, "No details available");

    const robotsTotal =
      payload.details && payload.details.overall && Number(payload.details.overall.total)
        ? Number(payload.details.overall.total)
        : 23;

    const infoCta = `<a class="subtle-link" href="/results/info/${encodeURIComponent(payload.category)}">What this check means &rarr;</a>`;
    const botsCta =
      payload.category === "robots"
        ? `<a class="subtle-link" href="/bots">View all ${robotsTotal} bots we check &rarr;</a>`
        : "";

    const card = document.createElement("article");
    card.className = "check-card";
    card.innerHTML = `
      <div class="check-top">
        <h3 class="check-title">${escapeHtml(categoryLabel(payload.category, payload.category_label))}</h3>
        <span class="badge ${severity}">${escapeHtml(severity)}</span>
      </div>
      <div class="tiny-track">
        <div class="tiny-fill" style="background: ${severityColor[severity]}; width: 0%;"></div>
      </div>
      <p class="list-label">Details</p>
      <ul class="detail-list">${detailsList}</ul>
      <p class="list-label">Signals</p>
      <ul class="signal-list">${signals}</ul>
      ${infoCta}
      ${botsCta}
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
    if (typeof score !== "number" || Number.isNaN(score)) {
      gradeEl.textContent = grade || "N/A";
      gradeEl.classList.remove("pending");
      overallScoreBar.style.width = "0%";
      overallScoreText.textContent = "Inconclusive (could not fetch enough data)";
      return;
    }
    const normalized = clampScore(score);
    const scorePercent = Math.round(normalized * 100);
    gradeEl.textContent = grade || "N/A";
    gradeEl.classList.remove("pending");
    overallScoreBar.style.width = `${scorePercent}%`;
    overallScoreText.textContent = `${scorePercent}% overall readiness`;
  }

  function setError(message) {
    removeSkeletonCard();
    loadingState.classList.add("hidden");
    errorBox.classList.remove("hidden");
    errorBox.textContent = message;
  }

  function ensureSkeletonCard() {
    if (skeletonCard) {
      checkGrid.appendChild(skeletonCard);
      return;
    }

    skeletonCard = document.createElement("article");
    skeletonCard.className = "check-card skeleton-card";
    skeletonCard.innerHTML = `
      <div class="skeleton-line skeleton-header" style="width: 80%;"></div>
      <div class="skeleton-line" style="width: 60%;"></div>
      <div class="skeleton-line" style="width: 80%;"></div>
      <div class="skeleton-line" style="width: 40%;"></div>
      <div class="skeleton-line" style="width: 70%; margin-bottom: 0;"></div>
    `;
    checkGrid.appendChild(skeletonCard);
  }

  function removeSkeletonCard() {
    if (!skeletonCard) {
      return;
    }
    skeletonCard.remove();
    skeletonCard = null;
  }

  if (context.preloadedComplete) {
    (context.preloadedResults || []).forEach((eventPayload) => renderCheckCard(eventPayload));
    updateOverall(context.preloadedOverall, context.preloadedGrade);
    loadingState.classList.add("hidden");
    return;
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
      ensureSkeletonCard();
      return;
    }

    if (payload.type === "check") {
      renderCheckCard(payload);
      if (skeletonCard) {
        checkGrid.appendChild(skeletonCard);
      }
      return;
    }

    if (payload.type === "complete") {
      removeSkeletonCard();
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
