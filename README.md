# Tributary

Static **user journey** graphs from frontend source — routes, navigation edges, and concrete paths. No runtime. No LLM in the extract path.

Supports React Router, TanStack Router, Expo Router (more frameworks on the way).

## Install

One install → **CLI** and **Python import**:

```bash
pip install tributary
```

```bash
tributary ./my-app --journey
```

```python
from tributary import extract_journeys

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
tributary ./my-app --journey
tributary ./my-app --instrument   # PostHog detection (stub)
```

## Library (programmatic)

```python
from tributary import extract_journeys

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
from tributary import analyze, extract_journeys

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
from tributary import JourneyGraph, RouteNode, NavEdge, Confidence
```

### Per-framework extractors

```python
from tributary import detect_all_frameworks, get_extractor
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
