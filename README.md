# Rhumb

> Constant-bearing journeys through your app.

Static **user journey** graphs from frontend source — routes, navigation edges, and concrete paths. No runtime. No LLM in the extract path.

## Framework support

| Framework | Status | Notes |
|-----------|--------|-------|
| React Router | **Supported** | Config / JSX routes + Link / navigate / redirect |
| TanStack Router | **Supported** | FS + `routeTree.gen.ts` + virtual routes + nav |
| Expo Router | **Supported** | Filesystem `app/` + Link / `router.*` |
| Vue Router | Coming soon | Stub registered — SFC + router TS planned |
| SvelteKit | Coming soon | Stub registered — `src/routes` + Svelte nav planned |
| Next.js | Coming soon | `app/` / `pages/` filesystem + Link / redirects |
| Remix | Coming soon | Filesystem routes + nav |
| Angular | Coming soon | TS `Routes` arrays |
| Vite + React (no router) | Coming soon | Thin / delegate when React Router present |

Detection already recognizes several of the “coming soon” stacks from `package.json`; journey extraction ships only for the **Supported** rows today.

## Prerequisites

| Tool | Version | Why |
|------|---------|-----|
| [Python](https://www.python.org/downloads/) | **3.11+** | Runtime (`requires-python = ">=3.11"`) |
| [Git](https://git-scm.com/) | any recent | Clone / install from GitHub |
| [uv](https://docs.astral.sh/uv/) | latest | Recommended — sync deps + run CLI without a global `pip install` |

Optional: Node.js only if you later use the TypeScript binder miss-path against a project that needs it; the default tree-sitter path does not require Node.

Install uv (if needed):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Install

Not on PyPI yet. Use the GitHub repo.

### A — Install from repo URL (into your env / project)

```bash
# with uv (preferred)
uv pip install git+https://github.com/satnam-sandhu/rhumb.git

# or with pip
pip install git+https://github.com/satnam-sandhu/rhumb.git
```

Then:

```bash
rhumb ./my-app --journey
```

```python
from rhumb import extract_end_routes
print(extract_end_routes("./my-app"))
```

### B — Clone and run locally (no PyPI, no global package install)

```bash
git clone https://github.com/satnam-sandhu/rhumb.git
cd rhumb
uv sync --group dev          # creates .venv + installs deps
```

Run CLI / tests via `uv run` (uses the project venv; you do not need `pip install -e .`):

```bash
uv run rhumb ./path/to/my-app --journey
uv run rhumb ./path/to/my-app --journey -v
uv run pytest -q
```

Library import from this checkout:

```bash
uv run python -c 'from rhumb import extract_end_routes; print(extract_end_routes("./path/to/my-app"))'
```

Or open a shell in the synced env:

```bash
uv run python
>>> from rhumb import extract_end_routes
>>> extract_end_routes("./path/to/my-app")
```

---

## CLI

```bash
# Journey JSON on stdout (pipe-friendly) — includes ends + gaps
rhumb ./my-app --journey

# Same JSON + end-grouped journeys / routes / edges / gaps on stderr
rhumb ./my-app --journey --verbose

# Write to a file
rhumb ./my-app --journey > journeys.json

# PostHog instrumentation (stub)
rhumb ./my-app --instrument
```

Stdout is only the JSON envelope when you use `--journey` (verbose detail goes to stderr).

---

## Library (programmatic)

### Preferred: ends + gaps envelope

`extract_end_routes` returns a **JSON-serializable `dict`** (not a string). Same shape as the CLI.

```python
from rhumb import extract_end_routes
import json

result = extract_end_routes("./my-app")

for project in result["projects"]:
    print(project["framework"], project["root"])
    for end_route, paths in project["ends"].items():
        print(end_route, len(paths))
    for gap in project["gaps"]:
        print("gap:", gap["message"])

# need a JSON string / HTTP body / file?
payload = json.dumps(result, indent=2)
json.dump(result, open("journeys.json", "w"), indent=2)
```

### Reuse detection across calls

```python
from rhumb import analyze, extract_end_routes

ctx = analyze("./my-app")   # detect frameworks once
result = extract_end_routes(ctx)
```

### Lower-level: full journey graphs

```python
from rhumb import extract_journeys

for graph in extract_journeys("./my-app"):
    print(graph.framework)       # e.g. "tanstack-router"
    print(len(graph.routes), "routes")
    print(len(graph.edges), "edges")
    print(len(graph.journeys), "journeys")
    for gap in graph.gaps:
        print("gap:", gap.message)
```

### Per-framework extractors

```python
from pathlib import Path
from rhumb import detect_all_frameworks, get_extractor

root = Path("./my-app")
for detection in detect_all_frameworks(root):
    extractor = get_extractor(detection.framework)
    if extractor is None:
        continue
    graph = extractor.extract(root, detection)
```

---

## Output format

Always one envelope (single app or monorepo):

```json
{
  "projects": [
    {
      "framework": "tanstack-router",
      "root": "shop",
      "ends": {
        "/checkout": [
          ["/search", "/product-details", "/cart", "/checkout"],
          ["/search", "/cart", "/checkout"]
        ],
        "/profile": [
          ["/", "/profile"]
        ]
      },
      "gaps": [
        {
          "message": "nav target not in route tree: /legacy",
          "source_file": "src/layout/AppSidebar.tsx",
          "source_line": 48,
          "confidence": "medium"
        }
      ]
    }
  ]
}
```

| Field | Meaning |
|-------|---------|
| `ends` | End screen → all inbound journey paths that terminate there |
| `gaps` | What we could **not** resolve (same rows `-v` prints) |

Monorepo = multiple objects inside `projects`.

### CLI sample session

```bash
$ rhumb ./shop --journey
{
  "projects": [
    {
      "framework": "react-router",
      "root": "shop",
      "ends": {
        "/cart": [
          ["/search", "/product-details", "/cart"]
        ],
        "/checkout": [
          ["/search", "/product-details", "/cart", "/checkout"],
          ["/search", "/cart", "/checkout"]
        ]
      },
      "gaps": []
    }
  ]
}
```

With `--verbose`, stderr mirrors ends (grouped by destination) and lists gaps:

```text
  journeys: 3 → 2 ends
    /cart:
      /search → /product-details → /cart
    /checkout:
      /search → /product-details → /cart → /checkout
      /search → /cart → /checkout
  gaps: 1
    - nav target not in route tree: /legacy  (src/layout/AppSidebar.tsx:48)
```

---

## What it cannot do (gaps & limits)

Rhumb prefers a **flagged gap** over a silent wrong edge. Incomplete `ends` + non-empty `gaps` is expected — not a crash.

**Not covered today (typical gap sources):**

| Limit | Why |
|-------|-----|
| Runtime-only routes | Paths built only after fetch / feature flags / CMS |
| Fully dynamic targets | `navigate(variable)`, `to={href}` with no static string |
| Cross-package deep links | Nav in one package to a route owned by another (unless both scanned) |
| Non-JS / coming-soon frameworks | Detected sometimes; extract may be stub or skipped |
| Auth / permission branches | Who *may* open a screen is not modeled — only static graph edges |
| Full TypeScript project typecheck | Miss-path binder is opt-in; default is tree-sitter syntax only |
| Pixel / UX “screens” | We map **URL routes**, not visual screen names or analytics events |

**Also not claimed:**

- 100% of sidebar / marketing links will resolve
- Parity with the running app after every deploy (re-run extract after route changes)
- Replacement for E2E tests — this is static structure, not behavior

Read `gaps[].message` + `source_file` to see what to fix or ignore. Empty `gaps` means extract had nothing to flag — not that the product has no dark corners.

---

## Core types

| Type | Role |
|------|------|
| `JourneyGraph` | routes, edges, gaps, journeys, meta |
| `RouteNode` | one URL path + source file |
| `NavEdge` | link / navigate / redirect transition |
| `JourneyPath` | ordered URL steps (`/a → /b → /c`) |
| `JourneyGap` | unresolved target or conflict |

```python
from rhumb import JourneyGraph, RouteNode, NavEdge, Confidence
```

## How it works

1. Detect frontend framework(s) from `package.json`
2. Extract routes (config AST, filesystem, or generated route tree)
3. Scan navigation (`Link`, `navigate`, `redirect`, …) via tree-sitter (+ TypeScript binder on miss)
4. Enumerate journey paths, group by **end route**, attach **gaps** → JSON envelope

See `docs/journey-architecture.md` for the plugin model.

## License

MIT
