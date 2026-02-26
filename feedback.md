# Bot-Friendly Shop: LLM-Friendliness Analysis

Based on an analysis of the `checks/` directory, the project is extremely forward-looking and addresses a critical emerging need: how autonomous AI agents, shopping bots, and LLM-based search engines interact with e-commerce sites.

Here is an evaluation of whether the current checks make sense and how the valid ones can be improved.

---

## 1. Do the checks make sense? (Are any nonsensical?)

**The short answer is yes, the vast majority make perfect sense.** The distinction between human accessibility (UX) and machine readability (DOM parsing, JSON-LD, `llms.txt`) is handled very well. The exhaustive mapping of modern AI agents in `robots.py` (e.g., *NovaAct*, *Operator*, *Gemini-Deep-Research*) is particularly impressive.

However, there are a few checks that are either nonsensical for an LLM or too brittle:

*   **Nonsensical: `_check_skip_navigation` (in `accessibility.py`)**
    *   *Why:* Checking for "Skip to content" anchor links (`href="#main"`) is a relic of linear screen-reader accessibility. LLM agents do not simulate pressing the `Tab` key to bypass repetitive navigation menus; instead, they parse the DOM as a tree and extract nodes directly (e.g., using `soup.find('main')`). An LLM does not need "skip links."
    *   *Recommendation:* Remove this check entirely from the LLM-friendliness score. Focus purely on semantic wrappers (`<main>`, `<article>`).
*   **Brittle/Vendor-Specific: Hardcoded Feed Paths (in `feeds.py`)**
    *   *Why:* The check currently looks specifically for `/products.json` and `/feeds/products.atom`. These are highly specific to **Shopify**. If the tool checks a WooCommerce, Magento, or custom-built store, it will penalize them for not having Shopify's proprietary feed paths.
    *   *Recommendation:* Do not hardcode vendor-specific paths. Instead, solely rely on parsing the homepage's `<link rel="alternate" type="application/rss+xml">` or `application/atom+xml` tags to discover standard feeds natively.
*   **Questionable: Hardcoded API Paths (in `api_surface.py`)**
    *   *Why:* Probing `/api/v1` and `/api/v2` blindly often results in 403s, 404s, or false positives. Modern APIs are rarely discoverable simply by hitting the root `/api/v1` path without authentication or a specific endpoint.

---

## 2. How could the valid checks be improved?

Here are several highly actionable ways to improve the existing, valid checks to better reflect how LLM agents behave today.

### A. Refine Bot Classifications (`robots.py`)
Currently, `robots.py` groups bots into two tiers: `"agent"` (e.g., AmazonBuyForMe) and `"crawler"` (e.g., GPTBot, PerplexityBot).
*   **Improvement:** Split `"crawler"` into two distinct categories: **`training_crawler`** (e.g., *CCBot*, *GPTBot*, *ClaudeBot*) and **`search_indexer`** (e.g., *OAI-SearchBot*, *PerplexityBot*).
*   **Why it matters:** E-commerce owners have vastly different incentives here. Most want to block their proprietary product data from being scraped for free foundational model training (`training_crawler`), but they *desperately want* to be indexed by Perplexity and SearchGPT to drive sales traffic (`search_indexer`). Treating them as the same "crawler" tier gives shop owners incomplete actionable advice.

### B. YAML Support & Plugin Discovery (`api_surface.py` & `discovery.py`)
*   **Improvement (API):** `api_surface.py` only checks for `/openapi.json` and `/swagger.json`. You must add support for **`.yaml`** extensions (e.g., `/openapi.yaml`). YAML is heavily favored by LLMs because it is significantly more token-efficient than JSON.
*   **Improvement (Discovery):** Expand `discovery.py` beyond `llms.txt` and `mcp.json` to include **`/.well-known/ai-plugin.json`** (OpenAI Plugins) and **`/.well-known/openai.yaml`** (Custom GPT Actions). These are currently the most widespread standards for exposing shop APIs to ChatGPT.

### C. Client-Side Rendering (CSR) Trap Detection (`semantic_html.py`)
*   **Improvement:** Add a check that evaluates the **text-to-code ratio** or detects pure Single Page Applications (SPAs). If the initial HTML response body only contains `<div id="root"></div>` and a massive `<script>` tag, flag it as a "CSR Trap."
*   **Why it matters:** Many lightweight, pure-HTTP LLM fetchers do not run headless browsers (like Playwright). If a shop relies entirely on JavaScript to render its products, it is completely invisible to a large subset of AI agents.

### D. Action-Oriented Structured Data (`structured_data.py`)
*   **Improvement:** Checking for `Product` schema is great, but autonomous shopping agents (like OpenAI's Operator) don't just read; they *do*. Enhance the JSON-LD checks to specifically look for **`PotentialAction`**, **`SearchAction`**, or **`BuyAction`** schemas.
*   **Why it matters:** This tells an agent exactly *how* to construct a URL to search the site or add an item to the cart, shifting the shop from being merely "readable" to genuinely "agentic."

### E. (New Check Idea) WAF / Bot Protection Interference
*   **Improvement:** The biggest real-world barrier to LLM shopping agents isn't bad HTML; it's getting blocked by Web Application Firewalls (WAF) like Cloudflare, Datadome, or PerimeterX.
*   **Implementation:** Add a check that specifically looks for WAF challenge fingerprints in the initial fetch (e.g., `<title>Just a moment...</title>`, `<div id="cf-please-wait">`, or a `403 Forbidden` with JS challenges). If an LLM gets stopped at the front door by a CAPTCHA, all other semantic optimizations are useless.