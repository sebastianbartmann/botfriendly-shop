# Ecom LLM Checker

Fast scanner for how ready an ecommerce site is for LLM and agent access.

## Install

```bash
uv venv && uv pip install -e . && playwright install chromium
```

## Usage

```bash
python cli.py <url>
```

JSON output:

```bash
python cli.py <url> --json
```

## Example Output

```text
Ecom LLM Readiness Report
URL: https://example.com
Overall: Grade: B (0.67)

● robots                  █████████░  0.90  PASS
   Top signals: GPTBot=allowed, ClaudeBot=allowed, Google-Extended=allowed
   Recommendations: none

● discovery               ████░░░░░░  0.40  FAIL
   Top signals: /llms.txt=not_found, /llms-full.txt=not_found, /.well-known/agent.json=found
   Recommendations: Publish /llms.txt; Add /.well-known/mcp.json

● structured_data         ███████░░░  0.73  PARTIAL
   Top signals: product_jsonld_count=12, offer_fields_complete=no
   Recommendations: Add missing priceCurrency and availability fields
```

## Check Modules

| Module | What it checks |
| --- | --- |
| `robots` | Whether important AI crawlers are allowed in `robots.txt`. |
| `discovery` | Agent/LLM discovery files like `llms.txt` and well-known manifests. |
| `sitemap` | Presence and validity of `sitemap.xml` plus URL coverage basics. |
| `structured_data` | JSON-LD and schema quality for product understanding. |
| `feeds` | Product feed endpoints and machine-readable catalog hints. |
| `api_surface` | Public API signals that help agents query catalog/order data. |
| `product_parseability` | How consistently product pages can be parsed into key fields. |

## Testing

```bash
make test
```

## License

MIT
