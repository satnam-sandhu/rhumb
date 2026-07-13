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

## Install

```bash
pip install rhumb
```

From this repo (editable):

```bash
uv sync
# or
pip install -e .
```

One install → **CLI** and **Python import**.

---

## CLI

```bash
# End-route JSON on stdout (pipe-friendly)
rhumb ./my-app --journey

# Same JSON + detection / route / edge detail on stderr
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

## Publish to PyPI

Trusted Publishing is configured for GitHub Actions (`.github/workflows/workflow.yml`, environment `uv`).

1. On PyPI: save the GitHub publisher (project `rhumb`, repo `satnam-sandhu/rhumb`, workflow `workflow.yml`, env `uv`).
2. On GitHub → Settings → Environments → create environment named exactly `uv`.
3. Bump version in `pyproject.toml` / `rhumb.__version__`, commit, tag, create a GitHub **Release**.
4. The workflow runs tests, `uv build`, then `uv publish` via OIDC (no API token).
