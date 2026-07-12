# Journey Detection Architecture

**Status:** active  
**Scope:** shared shell for all frameworks — plugins plug in; parsers stay layered.

React Router details: [`journey-react-router.md`](./journey-react-router.md)  
Expo Router details: [`journey-expo-router.md`](./journey-expo-router.md) (live Phase 1–3)  
TanStack Router details: [`journey-tanstack-router.md`](./journey-tanstack-router.md) (live Phase 1–3)  
Popularity / ship order: [`framework-popularity-report.md`](./framework-popularity-report.md)

## Goal

Deterministic **route + navigation** graphs from source — no runtime, no LLM in the extract path.

Every framework plugin returns the same shape: `JourneyGraph` (routes, edges, gaps, confidence).

## Design principles

1. **One shell, many plugins** — framework id → extractor; no giant `if/elif` forever.
2. **Shared JS/TS hybrid** — tree-sitter (A) hot path + TypeScript binder (B) miss-path only; lives in `parse_js`, not inside each plugin.
3. **SFC parsers stay in plugins** — Vue (`.vue`) and Svelte (`.svelte`) never go in `parse_js`.
4. **Filesystem-first where the framework is file-based** — Next, SvelteKit, Expo, Remix, TanStack routes dirs; AST supplements nav/redirects.
5. **Gaps over silent wrongness** — unresolved routes/edges become `JourneyGap` with confidence.
6. **Graphify supplements** — import/component graph for resolve; not the route DSL parser.

## Module layout

```
src/deterministic_kit/
  journey.py                 # CLI mode: registry dispatch + print
  journeys/
    types.py                 # JourneyGraph, RouteNode, NavEdge, JourneyGap, Confidence
    base.py                  # JourneyExtractor protocol
    parse_js.py              # shared hybrid A+B for .ts/.tsx/.js/.jsx
    registry.py              # framework id → extractor instance
    react_router.py          # live plugin
    expo_router.py           # live plugin (filesystem + nav)
    tanstack_router.py       # live plugin (gen/FS + nav)
    vue_router.py            # stub (SFC + router TS later)
    sveltekit.py             # stub (filesystem + Svelte parser later)
```

Add a framework: new module implementing `JourneyExtractor` + one line in `EXTRACTORS`.

## Pipeline (per detected project)

```
FrameworkDetection
        │
        ▼
 get_extractor(framework) ── none → "not registered"
        │
        ▼
 plugin.extract(project_dir, detection, ast?)
        │
        ├─ config / JSX / FS routes ──► RouteNode[]
        ├─ Link / navigate / nav cfg ─► NavEdge[]
        ├─ parse_js (if JS/TS) ───────► syntax (+ B on miss)
        ├─ Graphify imports ──────────► component → file
        └─ unresolved ────────────────► JourneyGap[]
        │
        ▼
   JourneyGraph
```

## Hybrid parse (A + B)

| Layer | Role | When |
|-------|------|------|
| **A — tree-sitter** | Fast syntax extract | Default for every JS/TS candidate |
| **B — TypeScript API** | Binder / symbol resolve | Only unresolved vars, spreads, re-exports |
| **Never by default** | Full-project typecheck | Scale bomb on monorepos |

`parse_js.parse_js_ts()` is the single entry; backends swap behind it.

## Plugin map

| Framework id | Route strategy | Parser extras | Status |
|--------------|----------------|---------------|--------|
| `react-router` | Config AST / JSX | `parse_js` | Live (tree-sitter + nav + journeys) |
| `next` | Filesystem `app/` `pages/` | `parse_js` for Link / redirects | Planned |
| `tanstack-router` | FS + `routeTree.gen.ts` + virtual | `parse_js` | Live (Phase 1–3) — see [`journey-tanstack-router.md`](./journey-tanstack-router.md) |
| `expo-router` | Filesystem `app/` | `parse_js` for Link / router.* | Live (Phase 1–3) — see [`journey-expo-router.md`](./journey-expo-router.md) |
| `remix` | Filesystem | `parse_js` for nav | Planned |
| `angular` | TS `Routes` arrays | `parse_js` | Planned |
| `vite-react` | Often no router | Thin / delegate if RR present | Planned |
| `vue-router` | Router TS + `.vue` | Vue SFC compiler + `parse_js` | Stub |
| `sveltekit` | `src/routes` + `.svelte` | Svelte parser + `parse_js` for hooks | Stub |

## Shared types (contract)

- **`RouteNode`** — `url_path`, component, source location, layout?, confidence, `RouteSource` (`config_ast` | `filesystem` | `generated`)
- **`NavEdge`** — from/to path, kind (`link` | `navigate` | `nav_config` | `redirect` | …), confidence
- **`JourneyGap`** — what we could not resolve
- **`JourneyGraph`** — framework, root, routes, edges, gaps, meta

Plugins must not invent a parallel final API.

## Production rules

- Deterministic: same tree → same graph.
- Cost bounded: O(candidate files), not O(whole monorepo × typecheck).
- Pin parser versions; golden fixtures per framework major.
- Registry is the extension point — Vue/Svelte/Next land without rewriting React Router.

## Ship order

1. Harden `react-router` on `parse_js` (tree-sitter) + nav edges  
2. Wire TypeScript miss-path behind `parse_js`  
3. File-based plugins (`next`, then `tanstack-router`)  
4. Fill `vue_router` / `sveltekit` stubs  
