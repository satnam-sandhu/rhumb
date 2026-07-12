# Journey Detection: React Router

**Status:** plugin live (tree-sitter + nav + journey paths)  
**Sample project:** `../free-react-tailwind-admin-dashboard` (detected as `react-router`, v7.1.5)  
**Shared shell:** [`journey-architecture.md`](./journey-architecture.md) — registry, `JourneyGraph`, hybrid `parse_js`, Vue/Svelte stubs.

This doc is **React Router only**. Cross-framework rules live in the architecture doc.

## Goal

Build a **deterministic route graph** and **navigation graph** from source — no runtime, no LLM.

A **journey** is a path through:

1. **Routes** — URL → page component (from router config)
2. **Transitions** — how users move between routes (`Link`, `navigate`, sidebar config, redirects)

Output: `JourneyGraph` via `ReactRouterExtractor` (same contract as every other plugin).

## React Router styles to support

React Router v6/v7 apps use two dominant patterns. Detect both.

### 1. Data router (config objects)

```tsx
const router = createBrowserRouter([
  {
    path: "/",
    Component: Root,
    children: [
      { index: true, Component: Home },
      { path: "about", Component: About },
    ],
  },
]);
```

Also: `createHashRouter`, `createMemoryRouter`, `createRoutesFromElements(...)`.

Route objects use: `path`, `index`, `Component` / `element`, `children`, `lazy`, `loader`, `action`.

### 2. Declarative JSX

```tsx
<BrowserRouter>
  <Routes>
    <Route element={<AppLayout />}>
      <Route index path="/" element={<Home />} />
      <Route path="/profile" element={<UserProfiles />} />
    </Route>
    <Route path="*" element={<NotFound />} />
  </Routes>
</BrowserRouter>
```

Aliases: `BrowserRouter as Router`, imports from `react-router` or `react-router-dom`.

### 3. Dynamic / hard cases (phase 2+)

| Pattern | Challenge |
|---------|-----------|
| `patchRoutesOnNavigation` | Routes added at runtime |
| `lazy: () => import(...)` | Component resolved lazily |
| Spread route modules `...authRoutes` | Cross-file re-exports → TS miss-path (B) |
| `useRoutes(routeConfig)` | Config in a variable → miss-path |
| String-template paths | `path: \`/users/${id}\`` — rare in static config |
| Layout routes (no `path`) | Inherit parent prefix only |

## What graphify AST gives us today

Ran AST on `free-react-tailwind-admin-dashboard`: **353 nodes, 611 edges, 104 files**.

**Useful:**

- File-level import graph (`App.tsx` → `src/pages/...`)
- Component function nodes (`App()`, `Home()`)
- `react-router` import detection

**Missing (confirmed):**

- No `<Route>` / `createBrowserRouter` nodes
- No `path` / `element` prop extraction
- No `<Link to="...">` edges

**Conclusion:** Route and navigation extraction needs the shared **`parse_js`** hybrid (tree-sitter + optional TS binder). Graphify supplements component resolution after routes are parsed. See architecture doc.

## Proposed pipeline (this plugin)

```
┌─────────────────┐     ┌──────────────────────┐     ┌─────────────────┐
│ Find route      │────▶│ Parse route tree     │────▶│ Resolve         │
│ candidate files │     │ parse_js (A, then B) │     │ via Graphify    │
└─────────────────┘     └──────────────────────┘     └────────┬────────┘
                                                                │
┌─────────────────┐     ┌──────────────────────┐               │
│ JourneyGraph    │◀────│ Parse navigation     │◀──────────────┘
│ (+ gaps)        │     │ (Link, navigate, nav)│
└─────────────────┘     └──────────────────────┘
```

### Step 1 — Find route candidate files

Heuristics (any match):

- Imports from `react-router` / `react-router-dom`
- Contains `createBrowserRouter`, `createRoutesFromElements`, `<Routes>`, `<Route`

Likely entry: `src/App.tsx`, `src/routes.tsx`, `src/router/index.ts`.

Implemented: `find_route_candidates()`.

### Step 2 — Parse route tree

**Production path:** `parse_js` (tree-sitter first; TypeScript binder on unresolved).  
**Current spike:** regex in `extract_routes_regex()` — works on sample; not production-accurate.

**Extract per route node:**

- `path` (string or `*`)
- `index` (bool)
- `element` / `Component` (identifier or `<Foo />`)
- `children` (nested)
- `source_file`, `source_line`

**Join paths:** child paths are relative to parent unless absolute (`/` prefix).

Example from sample `App.tsx`:

| Full path | Component | Layout parent |
|-----------|-----------|---------------|
| `/` | `Home` | `AppLayout` |
| `/profile` | `UserProfiles` | `AppLayout` |
| `/calendar` | `Calendar` | `AppLayout` |
| `/signin` | `SignIn` | — |
| `/signup` | `SignUp` | — |
| `*` | `NotFound` | — |

### Step 3 — Resolve components

Map `element={<Home />}` / `Component: Home` → import in same file → `src/pages/Dashboard/Home.tsx`.

Use graphify AST `imports_from` edges where possible; fall back to local import table from parser.

### Step 4 — Parse navigation transitions

Scan all project files (or layout + page subtree) for:

| API | Extract |
|-----|---------|
| `<Link to="...">` | static `to` string |
| `<NavLink to="...">` | static `to` string |
| `navigate("...")` | string literal first arg |
| `redirect("...")` | loader/action redirects |
| Nav config arrays | `path` fields in objects (e.g. `AppSidebar.tsx` `navItems`) |

**Sample sidebar paths** (`AppSidebar.tsx`): `/`, `/calendar`, `/profile`, `/form-elements`, `/signin`, etc. — these are **high-confidence journey edges** from layout shell.

### Step 5 — Build journey graph

Return shared `JourneyGraph`:

- Routes: `RouteNode` (`source=config_ast`)
- Edges: `NavEdge` (`kind`: link | navigate | nav_config | redirect)
- Gaps: regex / unresolved flagged explicitly

## Sample project findings

**`free-react-tailwind-admin-dashboard`**

- Framework: `react-router` (not `vite-react` — router dep matches first in waterfall)
- Route definition: single file `src/App.tsx`, JSX style
- Primary nav: `src/layout/AppSidebar.tsx` — static `navItems` / `othersItems` arrays
- Secondary links: `Link` in header, 404 page, auth layout
- `useNavigate` in `useGoBack.ts` — `navigate(-1)` and `navigate("/")` (history back, not a named journey edge)
- Spike result: **17 routes** via `ReactRouterExtractor` (confidence medium until tree-sitter)

## Module layout (this plugin)

```
src/deterministic_kit/journeys/
  react_router.py          # ReactRouterExtractor, candidates, regex spike
  types.py / base.py / …   # shared — see journey-architecture.md
  registry.py              # "react-router" → ReactRouterExtractor()
```

Dispatch (`journey.py`):

```python
extractor = get_extractor(project.framework)  # "react-router"
graph = extractor.extract(project_dir, project)
```

## Implementation phases

### Phase 0 — Spike (done)

- [x] Confirm graphify AST gaps
- [x] Document patterns and sample project
- [x] Candidate file finder
- [x] Regex prototype on `App.tsx` route list
- [x] Wire `ReactRouterExtractor` + registry + `JourneyGraph`

### Phase 1 — Route tree (done)

- [x] Implement `parse_js` tree-sitter; call from this plugin
- [x] Path joining + index / layout routes
- [x] Component import resolution via Graphify
- [x] Unit tests against sample `App.tsx`

### Phase 2 — Navigation (done)

- [x] `Link` / `NavLink` / `navigate` extraction
- [x] Static nav config arrays (`path:` in object literals)
- [x] Attach edges to source routes via file → route mapping

### Phase 3 — Robustness (done, B-lite)

- [x] Multi-file route modules (`routes/auth.tsx` exported) via miss-path (`follow_export`; full TS binder still architecture ship-order #2)
- [x] `lazy` import paths
- [x] `createRoutesFromElements`
- [x] Confidence flags for dynamic paths

## Open questions

1. **Journey scope** — all possible routes, or only routes reachable from `/` via static nav?
2. **Layout routes** — treat as journey steps or invisible wrappers?
3. **Auth guards** — `loader` redirects (e.g. unauthenticated → `/login`) — include as edges?
4. **Wildcard `*`** — include as terminal node?

## References

- [Journey architecture](./journey-architecture.md)
- [React Router v7 routing](https://reactrouter.com/start/data/routing)
- [Route objects](https://reactrouter.com/start/data/route-object/)
- [createBrowserRouter](https://reactrouter.com/api/data-routers/createBrowserRouter)
