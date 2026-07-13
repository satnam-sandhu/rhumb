# Rhumb

> Constant-bearing journeys through your app.

Static **user journey** graphs from frontend source — routes, navigation edges, and concrete paths. No runtime. No LLM in the extract path.

Supports React Router, TanStack Router, Expo Router (more frameworks on the way).

## Install

One install → **CLI** and **Python import**:

```bash
pip install rhumb
```

```bash
rhumb ./my-app --journey
```

```python
from rhumb import extract_journeys

for graph in extract_journeys("./my-app"):
    print(graph.framework, list(graph.journeys))
```

From this repo (editable):

```bash
uv sync
# or
pip install -e .
```

## CLI

```bash
rhumb ./my-app --journey
rhumb ./my-app --instrument   # PostHog detection (stub)
```

## Library (programmatic)

```python
from rhumb import extract_journeys

graphs = extract_journeys("./my-app")

for graph in graphs:
    print(graph.framework)          # e.g. "tanstack-router"
    print(len(graph.routes), "routes")
    print(len(graph.edges), "edges")
    for journey in graph.journeys:
        print(" → ".join(journey.steps))
    for gap in graph.gaps:
        print("gap:", gap.message)
```

Reuse detection/AST context across calls:

```python
from rhumb import analyze, extract_journeys

ctx = analyze("./my-app")
graphs = extract_journeys(ctx)
```

### Core types

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

### Per-framework extractors

```python
from rhumb import detect_all_frameworks, get_extractor
from pathlib import Path

root = Path("./my-app")
for detection in detect_all_frameworks(root):
    extractor = get_extractor(detection.framework)
    if extractor is None:
        continue
    graph = extractor.extract(root, detection, ast_result=None)
```

## How it works

1. Detect frontend framework(s) from `package.json`
2. Extract routes (config AST, filesystem, or generated route tree)
3. Scan navigation (`Link`, `navigate`, `redirect`, …) via tree-sitter
4. Enumerate journey path sequences

See `docs/journey-architecture.md` for the plugin model.

## License

MIT

## Publish to PyPI

Trusted Publishing is configured for GitHub Actions (`.github/workflows/workflow.yml`, environment `uv`).

1. On PyPI: save the GitHub publisher (project `rhumb`, repo `satnam-sandhu/rhumb`, workflow `workflow.yml`, env `uv`).
2. On GitHub → **Settings → Environments** → create environment named exactly `uv`.
3. Bump version in `pyproject.toml` / `rhumb.__version__`, commit, tag, create a GitHub **Release**.
4. The workflow runs tests, `uv build`, then `uv publish` via OIDC (no API token).

```bash
# after pip install from PyPI
pip install rhumb
rhumb ./app --journey
```

```python
from rhumb import extract_journeys
```
