# Journey Detection: TanStack Router

**Status:** live (Phase 1–3) — `TanStackRouterExtractor` in `journeys/tanstack_router.py`  
**Framework id:** `tanstack-router` (detected via `dependency: @tanstack/react-router`; signals: `src/routes/`, `src/routeTree.gen.ts`)  
**Shared shell:** [`journey-architecture.md`](./journey-architecture.md) — registry, `JourneyGraph`, hybrid `parse_js`, path enumeration  
**Related:** [`journey-expo-router.md`](./journey-expo-router.md) (filesystem peer); [`journey-react-router.md`](./journey-react-router.md) (code-based sibling)

This doc is **TanStack Router only**. Cross-framework rules live in the architecture doc.

## Goal

Deterministic **route + navigation** graphs from a TanStack Router app — no runtime, no LLM in the extract path.

Output: `JourneyGraph` via `TanStackRouterExtractor` (same contract as every other plugin).

TanStack Router is **hybrid**:

1. **Preferred:** file-based routes under `src/routes/` (+ generated `routeTree.gen.ts`)
2. **Also:** code-based `createRoute` / `createRootRoute` trees (less common in new apps)

Architecture principle #4: **filesystem / generated tree first**, then `parse_js` for nav. Prefer `routeTree.gen.ts` when present (authoritative, typed, `RouteSource.GENERATED`).

## Why TanStack differs from Expo / React Router

| Concern | React Router | Expo Router | TanStack Router |
|---------|--------------|-------------|-----------------|
| Route source | Config AST / JSX `<Route>` | Files under `app/` | Files under `routes/` **or** `routeTree.gen.ts` **or** `createRoute` |
| Path literals | `path: "/about"` | File name → URL | `createFileRoute('/about')` path arg + file layout |
| Dynamic params | `:id` / `[id]` | `[id].tsx` | `$postId` in path / filename |
| Layouts | Pathless parent routes | `_layout.tsx` | `_layout` / pathless layout routes / `__root` |
| Generated artifact | — | optional typed routes | **`routeTree.gen.ts`** (first-class) |
| Nav APIs | `Link to`, `navigate()` | `Link href`, `router.push` | `Link to`, `navigate({ to })`, `redirect({ to })` |

## Route discovery strategy (priority)

```
┌─────────────────────┐
│ routeTree.gen.ts?   │──yes──▶ parse generated tree (high confidence)
└──────────┬──────────┘
           │ no
           ▼
┌─────────────────────┐
│ src/routes/ (or     │──yes──▶ FS walk + createFileRoute('/path') args
│ configured routes   │
│ dir)                │
└──────────┬──────────┘
           │ no / thin
           ▼
┌─────────────────────┐
│ createRoute /       │──────▶ code-based AST (parse_js), like RR objects
│ createRootRoute     │
└─────────────────────┘
```

If gen file **and** FS both present: trust gen for `url_path` list; use FS files as `component` / `source_file`. Cross-check mismatches → `JourneyGap`.

## File notation to support

See [TanStack file-based routing](https://tanstack.com/router/latest/docs/routing/file-based-routing).

| Pattern | Example | URL / role |
|---------|---------|------------|
| Index | `routes/index.tsx` | `/` |
| Static | `routes/about.tsx` | `/about` |
| Nested dir | `routes/posts/index.tsx` | `/posts` |
| Dynamic | `routes/posts/$postId.tsx` | `/posts/$postId` (record TanStack `$` form) |
| Splat | `routes/$.tsx` / `$` segments | catch-all |
| Layout | `routes/_pathlessLayout.tsx`, `routes/posts/route.tsx` | wraps children; not always a leaf URL |
| Root | `routes/__root.tsx` | app shell — layout only |
| Private | `routes/-components/...` | `-` prefix — **not** a route |
| Flat dots | `routes/posts.$postId.tsx` | `/posts/$postId` (flat file convention) |

Also honor plugin config overrides when cheap to read (`tsr.config.json` / Vite plugin `routesDirectory`, `generatedRouteTree`) — else defaults: `src/routes`, `src/routeTree.gen.ts`.

### Example tree → routes

```text
src/routes/
  __root.tsx
  index.tsx              → /
  about.tsx              → /about
  posts/
    index.tsx            → /posts
    $postId.tsx          → /posts/$postId
  _authenticated/
    settings.tsx         → /settings   (pathless layout prefix)
```

**`RouteSource`:** `generated` when from `routeTree.gen.ts`; `filesystem` when FS-only; `config_ast` for pure `createRoute` trees.

**Canonical dynamic form:** prefer TanStack `$param` (not `:param` / `[param]`). Document in `meta.dynamic_form=tanstack`.

## Navigation to extract (`parse_js`)

| API | Extract | `NavEdge.kind` |
|-----|---------|----------------|
| `<Link to="...">` | static string `to` | `link` |
| `<Link to="/posts/$postId" params={...}>` | static `to` path | `link` |
| `navigate({ to: "..." })` | static `to` | `navigate` |
| `router.navigate({ to: "..." })` | static `to` | `navigate` |
| `redirect({ to: "..." })` / `throw redirect(...)` | static `to` | `redirect` |
| `<Navigate to="...">` | static `to` | `redirect` |

Dynamic `to={expr}` / `` to={`/posts/${id}`} `` → soft-match against known `$param` routes when possible (same policy as Expo template soften); else `JourneyGap`.

Search params (`search:`) — ignore for journey path identity (URL path only), same as Expo query strip.

## What Graphify gives / does not

**Useful:**

- Import graph under `src/routes/`
- Detect `@tanstack/react-router` usage

**Missing (expected):**

- No automatic mapping of `createFileRoute('/x')` → journey nodes without `parse_js` / gen parse
- No `Link to` edges without `parse_js`

**Conclusion:** gen file or FS + `createFileRoute` builds `RouteNode[]`; `parse_js` builds `NavEdge[]`; Graphify optional for component resolve.

## Proposed pipeline

```
┌──────────────────┐     ┌──────────────────────┐     ┌─────────────────┐
│ Find routes dir  │────▶│ Prefer routeTree.gen │────▶│ Attach layouts  │
│ + gen file       │     │ else FS / createRoute│     │ (__root, pathless)│
└──────────────────┘     └──────────────────────┘     └────────┬────────┘
                                                                │
┌──────────────────┐     ┌──────────────────────┐               │
│ JourneyGraph     │◀────│ parse_js nav scan    │◀──────────────┘
│ + build_journeys │     │ Link / navigate /    │
└──────────────────┘     │ redirect             │
                         └──────────────────────┘
```

## Module layout

```
src/deterministic_kit/journeys/
  tanstack_router.py       # TanStackRouterExtractor (live)
  registry.py              # "tanstack-router" → TanStackRouterExtractor()
  parse_js.py              # shared
  paths.py                 # shared
```

Registered: `"tanstack-router" → TanStackRouterExtractor()` in `registry.py`.

## Implementation phases

### Phase 0 — Spike

- [x] Confirm detection on a sample (`@tanstack/react-router` + `src/routes`)
- [x] Inspect one real `routeTree.gen.ts` shape (exports, path strings)
- [x] Manual map: FS tree + gen paths → expected `RouteNode[]`
- [x] Decide gen-vs-FS conflict policy (prefer gen)

### Phase 1 — Routes

- [x] Locate `routeTree.gen.ts` (default + common alternate paths)
- [x] Parse gen file for path list (`RouteSource.GENERATED`)
- [x] Fallback: walk `src/routes/`; read `createFileRoute('...')` path args
- [x] Skip `-` private files, treat `__root` as layout-only
- [x] `$param` / splat → medium confidence; static → high
- [x] Unit tests: flat + directory + dynamic + pathless layout

### Phase 2 — Navigation

- [x] `Link to` / `Navigate to` via `parse_js`
- [x] `navigate({ to })` / `router.navigate({ to })`
- [x] `redirect({ to })`
- [x] File → route attach; shared chrome → entry policy (reuse `paths.py`)

### Phase 3 — Robustness

- [x] Code-based-only apps (`createRoute` tree, no gen file)
- [x] Soft-match template `` `/posts/${id}` `` → `/posts/$postId`
- [x] Read `tsr.config.json` / vite plugin options for custom dirs
- [x] Virtual file routes — JSON `virtualRouteConfig`, `routes.ts` builders, in-tree `__virtual.ts`
- [x] Optional TS miss-path for re-exported `to` constants (`HOME`, `PATHS.about`, `navigate({ to: PATHS.x })`)

## Open questions

1. **Gen file missing in CI checkouts** — many repos gitignore `routeTree.gen.ts`. Must FS + `createFileRoute` work alone (**yes** — Phase 1 fallback).
2. **Pathless layout URL** — `_` prefix segments contribute zero URL segments; pathless-only files are layout-only (not leaf routes).
3. **`$param` vs concrete** — journeys keep parametric URLs (`/posts/$postId`); do not invent sample ids. **`meta.dynamic_form=tanstack`**.
4. **Sample app** — official TanStack Router Vite file-routing example as golden fixture.

## References

- [Journey architecture](./journey-architecture.md)
- [Framework popularity](./framework-popularity-report.md) — `tanstack-router` ~#4 by weekly downloads
- [File-based routing](https://tanstack.com/router/latest/docs/routing/file-based-routing)
- [Code-based routing](https://tanstack.com/router/latest/docs/routing/code-based-routing)
- [Navigation](https://tanstack.com/router/latest/docs/framework/react/guide/navigation)
