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
# End-route JSON on stdout (pipe-friendly)
rhumb ./my-app --journey

# Same JSON + end-grouped journeys / routes / edges on stderr
rhumb ./my-app --journey --verbose

# Write to a file
rhumb ./my-app --journey > journeys.json

# PostHog instrumentation (stub)
rhumb ./my-app --instrument
```

Stdout is only the JSON map when you use `--journey` without `--verbose` noise on stdout (verbose detail goes to stderr).

---

## Library (programmatic)

### Preferred: end route → inbound paths

`extract_end_routes` returns a **JSON-serializable `dict`** (not a string). Same shape as the CLI.

```python
from rhumb import extract_end_routes
import json

ends = extract_end_routes("./my-app")

# use as a dict
for end_route, paths in ends.items():
    print(end_route, len(paths))

# need a JSON string / HTTP body / file?
payload = json.dumps(ends, indent=2)
json.dump(ends, open("journeys.json", "w"), indent=2)
```

### Reuse detection across calls

```python
from rhumb import analyze, extract_end_routes

ctx = analyze("./my-app")   # detect frameworks once
ends = extract_end_routes(ctx)
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

### Single app

Keys = **end screens / routes**. Values = **all inbound journey paths** that terminate there (each path is an ordered list of URL steps).

```json
{
  "/checkout": [
    ["/search", "/product-details", "/cart", "/checkout"],
    ["/search", "/cart", "/checkout"]
  ],
  "/profile": [
    ["/", "/profile"]
  ],
  "/about": [
    ["/", "/about"]
  ]
}
```

Meaning: every listed path is a concrete funnel that ends on that screen. Shared for every framework — plugins only supply routes + nav edges; this map is built once.

### Monorepo (multiple detected apps)

```json
{
  "web:tanstack-router": {
    "/about": [["/", "/about"]],
    "/posts": [["/", "/posts"]]
  },
  "mobile:expo-router": {
    "/settings": [["/", "/settings"]]
  }
}
```

### CLI sample session

```bash
$ rhumb ./shop --journey
{
  "/cart": [
    ["/search", "/product-details", "/cart"]
  ],
  "/checkout": [
    ["/search", "/product-details", "/cart", "/checkout"],
    ["/search", "/cart", "/checkout"]
  ]
}
```

With `--verbose`, stderr mirrors that structure (human-readable):

```text
  journeys: 3 → 2 ends
    /cart:
      /search → /product-details → /cart
    /checkout:
      /search → /product-details → /cart → /checkout
      /search → /cart → /checkout
```

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
4. Enumerate journey paths and group by **end route** → JSON map

See `docs/journey-architecture.md` for the plugin model.

## License

MIT
