import re

with open('web_app/routes.py', 'r') as f:
    content = f.read()

# Instead of parsing python, let's just do a string replacement for CATEGORY_INFO_GUIDES
# Actually, I can just rewrite the whole dictionary using regex or simply dump a new dict.

new_dict = """CATEGORY_INFO_GUIDES: dict[str, dict[str, Any]] = {
    "robots": {
        "overview": "Checks whether major AI shopping agents, AI search indexers, and AI training crawlers are allowed in robots.txt.",
        "faqs": [
            {
                "q": "What is an AI Bot Access Policy in robots.txt?",
                "a": "It's the set of rules in your site's robots.txt file that specifically allow or block user-agents associated with AI services, such as ChatGPT-User, Anthropic-ai, or Google-Extended."
            },
            {
                "q": "Why should I allow AI shopping agents?",
                "a": "AI shopping agents actively browse the web to find products for users. Blocking them means your products won't be recommended when users ask chatbots for purchasing advice."
            }
        ],
        "comparison": {
            "title": "Traditional Crawlers vs AI Agents",
            "headers": ["Feature", "Traditional Search Bots", "AI Shopping Agents"],
            "rows": [
                ["Primary Goal", "Index pages for search results", "Extract specific facts and answers"],
                ["Traffic Impact", "Drives clicks to your site", "Often provides zero-click answers, but highly qualified leads"],
                ["Robots.txt Group", "Googlebot, Bingbot", "ChatGPT-User, ClaudeBot, PerplexityBot"]
            ]
        },
        "checklist": [
            "Audit your current robots.txt file.",
            "Identify which AI agents you want to allow (e.g., search indexers) vs block (e.g., pure scrapers).",
            "Add explicit Allow or Disallow directives for major AI user-agents.",
            "Regularly monitor server logs to discover new AI bots."
        ],
        "fields": [
            {"name": "tiers.*.allowed/blocked/not_mentioned", "meaning": "Per bot tier: how many bots are explicitly allowed, blocked, or not mentioned."},
            {"name": "overall", "meaning": "Totals across all tracked bots."},
            {"name": "blocked_operators", "meaning": "Provider names where one or more bots are blocked."},
            {"name": "status_code", "meaning": "HTTP response status for robots.txt."},
            {"name": "reason", "meaning": "Why the result is fail/inconclusive when robots.txt could not be evaluated."}
        ]
    },
    "discovery": {
        "overview": "Checks common machine-readable discovery files like llms.txt and well-known AI plugin/MCP specs.",
        "faqs": [
            {
                "q": "What is an llms.txt file?",
                "a": "An llms.txt file is a markdown-formatted document placed in the root of your site (similar to robots.txt) that provides LLMs with a clean, concise summary of your site's purpose, structure, and key data."
            },
            {
                "q": "How do AI discovery files help my store?",
                "a": "They act as a roadmap for AI agents, pointing them directly to your product feeds, API documentation, or structured data, avoiding the need for them to guess or randomly crawl your site."
            }
        ],
        "checklist": [
            "Create an llms.txt file summarizing your store and catalog.",
            "Host it at the root of your domain (e.g., yourstore.com/llms.txt).",
            "Link to your main product feeds or sitemaps within the file.",
            "Keep the content concise and machine-readable."
        ],
        "fields": [
            {"name": "<path>.status_code", "meaning": "HTTP status returned for that discovery path."},
            {"name": "<path>.content_type", "meaning": "Returned content type; must match the expected format."},
            {"name": "<path>.final_url", "meaning": "Final URL after redirects; path should stay correct."},
            {"name": "<path>.reachable", "meaning": "Whether the endpoint could be reached at all."},
            {"name": "<path>.preview", "meaning": "Short preview of the response body when found."}
        ]
    },
    "sitemap": {
        "overview": "Validates sitemap presence, structure quality, freshness signals, and robots.txt linkage.",
        "faqs": [
            {
                "q": "What is Sitemap Quality in the context of AI?",
                "a": "While traditional search engines are forgiving, AI agents often rely on perfectly structured sitemaps with accurate <lastmod> dates to quickly find new products without doing a full site crawl."
            },
            {
                "q": "Why is the lastmod attribute so critical now?",
                "a": "AI agents have limited token windows and execution time. A fresh, accurate lastmod attribute allows them to only fetch products that have recently changed."
            }
        ],
        "comparison": {
            "title": "Basic vs AI-Optimized Sitemap",
            "headers": ["Aspect", "Basic Sitemap", "AI-Optimized Sitemap"],
            "rows": [
                ["Structure", "Flat list of URLs", "Organized via sitemap index by category/type"],
                ["Lastmod", "Often missing or hardcoded", "Dynamically updated accurately on product change"],
                ["Discovery", "Submitted via Search Console", "Linked explicitly in robots.txt"]
            ]
        },
        "fields": [
            {"name": "status_code/content_type/final_url", "meaning": "Fetch result metadata for sitemap.xml."},
            {"name": "url_count", "meaning": "Number of <url> entries in sitemap files."},
            {"name": "sitemap_count", "meaning": "Number of child sitemaps in a sitemap index."},
            {"name": "has_lastmod", "meaning": "Whether lastmod fields are present."},
            {"name": "fresh_lastmod", "meaning": "Whether newest lastmod appears fresh (<=30 days old)."},
            {"name": "robots_sitemap_directive", "meaning": "Whether robots.txt declares a Sitemap: directive."}
        ]
    },
    "structured_data": {
        "overview": "Detects JSON-LD schema and Open Graph metadata used by AI and rich result systems.",
        "faqs": [
            {
                "q": "What is Structured Data for ecommerce?",
                "a": "It is standardized code (usually JSON-LD) embedded in your HTML that explicitly tells machines what a page is about—like specifying exactly what the price, currency, and availability of a product are."
            },
            {
                "q": "Why do AI agents prefer JSON-LD over HTML parsing?",
                "a": "HTML layouts change and are visually oriented. JSON-LD provides a guaranteed, stable data structure that AI can extract with 100% accuracy without guessing."
            }
        ],
        "checklist": [
            "Implement standard Product schema on all product detail pages.",
            "Ensure critical fields (name, price, currency, availability) are populated.",
            "Add Offer schema to describe purchasing conditions.",
            "Validate your JSON-LD using Google's Rich Results Testing Tool."
        ],
        "fields": [
            {"name": "json_ld_block_count", "meaning": "How many JSON-LD script blocks were found."},
            {"name": "schema_types", "meaning": "All parsed schema.org types from JSON-LD."},
            {"name": "action_schema_types", "meaning": "Action-oriented schema types like SearchAction/BuyAction."},
            {"name": "open_graph_tags", "meaning": "Detected Open Graph product-related tags."},
            {"name": "malformed_json_ld_blocks", "meaning": "Count of JSON-LD blocks that failed to parse."},
            {"name": "status_code", "meaning": "Homepage HTTP status used for this check."}
        ]
    },
    "seo_meta": {
        "overview": "Checks SEO-critical metadata quality that also helps AI systems interpret storefront pages.",
        "faqs": [
            {
                "q": "Does traditional SEO metadata still matter for AI?",
                "a": "Yes. Before an AI uses advanced parsing, it often checks the <title> and <meta description> to quickly determine if a page is relevant to the user's prompt."
            }
        ],
        "fields": [
            {"name": "title_length", "meaning": "Length of the <title> text."},
            {"name": "description_length", "meaning": "Length of the meta description text."},
            {"name": "canonical", "meaning": "Canonical URL value if present."},
            {"name": "language", "meaning": "Value of the html lang attribute."},
            {"name": "viewport", "meaning": "Viewport meta value for mobile rendering support."},
            {"name": "h1_count", "meaning": "Number of <h1> headings found."}
        ]
    },
    "feeds": {
        "overview": "Looks for alternate feed links and product feed hints useful for commerce indexing.",
        "faqs": [
            {
                "q": "What are Product Feeds in this context?",
                "a": "XML or JSON feeds (like Google Merchant Center feeds) that contain your entire product catalog in a machine-readable format."
            },
            {
                "q": "How do agents discover my feeds?",
                "a": "Through <link rel='alternate'> tags in your HTML `<head>` or via explicit links in your discovery files (like llms.txt)."
            }
        ],
        "fields": [
            {"name": "alternate_feed_hrefs", "meaning": "Feed URLs exposed via <link rel='alternate'> in HTML."},
            {"name": "structured_feed_hrefs", "meaning": "Feed URLs with product/catalog naming hints."},
            {"name": "google_shopping_hint", "meaning": "Whether page text hints at Merchant Center/shopping feed usage."}
        ]
    },
    "api_surface": {
        "overview": "Probes for OpenAPI/Swagger specs, GraphQL endpoint hints, and API doc links.",
        "faqs": [
            {
                "q": "What is an API Surface?",
                "a": "It's the publicly discoverable set of APIs (like REST endpoints or GraphQL) that a bot can interact with directly, instead of parsing HTML."
            },
            {
                "q": "Why expose API docs to bots?",
                "a": "Advanced agents (like ChatGPT with browsing) can read OpenAPI specs and dynamically construct API calls to query your inventory in real-time."
            }
        ],
        "fields": [
            {"name": "spec_found", "meaning": "Per known path, whether an API spec was validly discovered."},
            {"name": "probe_status", "meaning": "Per probe result: found, not_found, or unknown."},
            {"name": "graphql_options_status", "meaning": "HTTP status returned by OPTIONS /graphql probe."},
            {"name": "doc_links", "meaning": "Homepage links that look like API/developer docs."}
        ]
    },
    "product_parseability": {
        "overview": "Measures whether product facts are complete and consistent across schema, metadata, and visible HTML.",
        "faqs": [
            {
                "q": "What is Product Parseability?",
                "a": "It's a measure of how easily and accurately a machine can extract core product facts (name, price, stock) from your pages."
            },
            {
                "q": "Why does price consistency matter?",
                "a": "If your HTML says $10 but your JSON-LD says $15, an AI agent will lose confidence in the data and may refuse to recommend your product."
            }
        ],
        "checklist": [
            "Ensure JSON-LD price matches the visible HTML price exactly.",
            "Verify Open Graph meta tags align with JSON-LD data.",
            "Use clear, semantic HTML elements (like <span itemprop='price'>) around visible prices."
        ],
        "fields": [
            {"name": "schema_types", "meaning": "Schema types detected in JSON-LD."},
            {"name": "jsonld_name/jsonld_price/jsonld_availability", "meaning": "Core Product JSON-LD fields extracted from offers."},
            {"name": "og_title/og_price/og_currency", "meaning": "Core Open Graph product metadata values."},
            {"name": "h1_count", "meaning": "Count of top-level headings."},
            {"name": "price_element_count", "meaning": "Count of visible price-like elements in HTML."},
            {"name": "price_consistent", "meaning": "Whether JSON-LD and OG prices numerically match."},
            {"name": "malformed_json_ld_blocks", "meaning": "Count of invalid JSON-LD blocks encountered."}
        ]
    },
    "semantic_html": {
        "overview": "Evaluates semantic page structure, heading order, navigation semantics, CSR shell risk, and WAF interference.",
        "faqs": [
            {
                "q": "What is Semantic HTML?",
                "a": "Using proper HTML tags (<nav>, <main>, <article>) according to their intended meaning, rather than just using <div> tags for everything."
            },
            {
                "q": "Why do AI agents care about HTML tags?",
                "a": "When an agent strips away CSS and Javascript, it relies entirely on semantic tags to understand which part of the page is the main content vs navigation or footer."
            }
        ],
        "comparison": {
            "title": "Non-Semantic vs Semantic Layout",
            "headers": ["Element Purpose", "Non-Semantic", "Semantic"],
            "rows": [
                ["Main Content", "<div class='content'>", "<main>"],
                ["Navigation Menu", "<div id='menu'>", "<nav>"],
                ["Product Title", "<div class='big-text'>", "<h1>"]
            ]
        },
        "fields": [
            {"name": "semantic_elements_used", "meaning": "Which semantic tags (header/nav/main/footer/etc.) were found."},
            {"name": "heading_hierarchy", "meaning": "Heading level order, h1 count, skip count, and summary message."},
            {"name": "semantic_navigation_lists", "meaning": "Navigation region count and how many use semantic lists."},
            {"name": "csr_trap", "meaning": "Signals that page may be mostly JS shell with little server-rendered content."},
            {"name": "waf_interference", "meaning": "Signals of challenge/blocked pages that can affect bots."}
        ]
    },
    "accessibility": {
        "overview": "Checks practical accessibility markers tied to parseability for humans and machines.",
        "faqs": [
            {
                "q": "How are accessibility and AI-readiness related?",
                "a": "Screen readers for visually impaired users operate very similarly to AI agents. Both rely on clear labels, alt text, and logical document structure to 'read' a page without seeing it visually."
            }
        ],
        "checklist": [
            "Provide descriptive alt text for all product images.",
            "Ensure all form inputs (like search or quantity boxes) have explicit <label> elements.",
            "Use descriptive link text instead of generic 'click here' links.",
            "Use standard HTML data tables (<th> and <td>) for product specifications."
        ],
        "fields": [
            {"name": "image_alt_text", "meaning": "Image alt coverage totals and ratio."},
            {"name": "landmarks", "meaning": "Presence of key landmarks: banner, navigation, main, contentinfo."},
            {"name": "form_labels", "meaning": "Count and ratio of labeled form inputs."},
            {"name": "link_quality", "meaning": "Count and ratio of links with descriptive text."},
            {"name": "table_accessibility", "meaning": "Data table accessibility summary (headers/structure)."}
        ]
    }
}"""

# Replace the block from `CATEGORY_INFO_GUIDES: dict[str, dict[str, Any]] = {` to the next unindented block
start_idx = content.find("CATEGORY_INFO_GUIDES: dict[str, dict[str, Any]] = {")
end_idx = content.find("scans: dict[str, dict[str, Any]] = {}", start_idx)

if start_idx != -1 and end_idx != -1:
    new_content = content[:start_idx] + new_dict + "\n\n" + content[end_idx:]
    with open('web_app/routes.py', 'w') as f:
        f.write(new_content)
    print("Updated routes.py")
else:
    print("Could not find the block to replace")
