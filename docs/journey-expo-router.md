# Journey Detection: Expo Router

**Status:** planned (doc only — plugin not started)  
**Framework id:** `expo-router` (already detected via `dependency: expo-router`)  
**Shared shell:** [`journey-architecture.md`](./journey-architecture.md) — registry, `JourneyGraph`, hybrid `parse_js`, path enumeration  
**Related:** [`journey-react-router.md`](./journey-react-router.md) (config/JSX sibling); filesystem peers: Next, SvelteKit, Remix

This doc is **Expo Router only**. Cross-framework rules live in the architecture doc.

## Goal

Deterministic **route + navigation** graphs from an Expo Router app source tree — no runtime, no LLM in the extract path.

Output: `JourneyGraph` via a future `ExpoRouterExtractor` (same contract as every other plugin).

Expo Router is **filesystem-first**: the `app/` (or `src/app/`) directory *is* the route table. AST/`parse_js` supplements **navigation** (`Link`, `router.push`, redirects), not primary route discovery.

## Why Expo Router differs from React Router

| Concern | React Router | Expo Router |
|---------|--------------|-------------|
| Route source | Config AST / JSX `<Route>` | Files under `app/` |
| Layouts | Pathless `<Route element={Layout}>` | `_layout.tsx` per directory |
| URL segments | Explicit `path` strings | File/dir names (+ notation) |
| Dynamic params | `:id` or `[id]` in config | `[id].tsx`, `[...slug].tsx` |
| Groups | Nested route objects | `(group)/` dirs — **omitted from URL** |
| Nav APIs | `Link to`, `navigate()` | `Link href`, `router.push` / `replace` / `navigate` |

Architecture principle #4 applies: **filesystem first**, then `parse_js` for nav.

## File notation to support

See [Expo Router notation](https://docs.expo.dev/router/basics/notation/).

| Pattern | Example | URL / role |
|---------|---------|------------|
| Static | `app/about.tsx` | `/about` |
| Index | `app/index.tsx`, `app/profile/index.tsx` | `/`, `/profile` |
| Layout | `app/_layout.tsx`, `app/(tabs)/_layout.tsx` | Not a leaf URL; wraps children |
| Group | `app/(tabs)/feed.tsx` | `/feed` (parens not in URL) |
| Dynamic | `app/users/[id].tsx` | `/users/:id` (record as `/users/[id]` or `/users/:id`) |
| Catch-all | `app/[...slug].tsx` | `/*` / `/[...slug]` |
| Not found | `app/+not-found.tsx` | Special terminal |
| Platform | `+html.tsx`, `+native-intent.tsx` | Skip or gap — not journey steps |

Also accept route root at **`app/`** or **`src/app/`** (Expo templates vary).

### Example tree → routes

```text
app/
  _layout.tsx
  index.tsx                 → /
  (auth)/
    _layout.tsx
    sign-in.tsx             → /sign-in
  (tabs)/
    _layout.tsx
    index.tsx               → /          (or group default — resolve carefully)
    settings.tsx            → /settings
  product/
    [id].tsx                → /product/[id]
  +not-found.tsx            → * (not-found)
```

**Layout parent:** child routes under a directory inherit that directory’s `_layout.tsx` as `RouteNode.layout` (file path), analogous to RR layout components.

**`RouteSource`:** `filesystem` for FS-derived routes (not `config_ast`).

## Navigation to extract (`parse_js`)

Scan `.ts`/`.tsx`/`.js`/`.jsx` under the project (or `app/` + components):

| API | Extract | `NavEdge.kind` |
|-----|---------|----------------|
| `<Link href="...">` | static string `href` | `link` |
| `<Link href={{ pathname: "..." }}>` | static `pathname` when literal | `link` |
| `router.push("...")` | string literal | `navigate` |
| `router.replace("...")` | string literal | `navigate` |
| `router.navigate("...")` | string literal | `navigate` |
| `<Redirect href="...">` | static `href` | `redirect` |
| `router.back()` / `router.dismiss()` | skip (no named target) | — |

Dynamic `href={expr}` / `push({ pathname: var })` → `JourneyGap` (low confidence), same policy as RR.

Relative hrefs (`./`, `../`) — resolve against source file’s route URL when possible; else gap.

## What Graphify gives / does not

**Useful:**

- File graph under `app/`
- Import edges from screens → components
- Detect `expo-router` import usage

**Missing (expected):**

- No automatic “this file is route `/settings`” nodes from Expo conventions
- No `Link href` / `router.push` edges without `parse_js`

**Conclusion:** FS walk builds `RouteNode[]`; `parse_js` builds `NavEdge[]`; Graphify optional for component resolve outside `app/`.

## Proposed pipeline

```
┌─────────────────┐     ┌──────────────────────┐     ┌─────────────────┐
│ Find app/ or    │────▶│ Map files → URLs     │────▶│ Attach layouts  │
│ src/app/ root   │     │ (notation rules)     │     │ (_layout.tsx)   │
└─────────────────┘     └──────────────────────┘     └────────┬────────┘
                                                                │
┌─────────────────┐     ┌──────────────────────┐               │
│ JourneyGraph    │◀────│ parse_js nav scan    │◀──────────────┘
│ + build_journeys│     │ Link / router.*      │
└─────────────────┘     └──────────────────────┘
```

Shared `build_journeys()` (already in shell) turns edges into `/a → /b → …` after extract.

## Module layout (planned)

```
src/deterministic_kit/journeys/
  expo_router.py           # ExpoRouterExtractor (new)
  registry.py              # "expo-router" → ExpoRouterExtractor()
  parse_js.py              # nav only (shared)
  paths.py                 # journey sequences (shared)
```

Stub today: unregistered → CLI prints `not registered`. Add one registry line when plugin lands.

## Implementation phases

### Phase 0 — Spike

- [ ] Confirm detection (`expo-router` in `framework.py`) on a sample app
- [ ] Locate `app/` vs `src/app/`
- [ ] Manual map of one sample tree → expected `RouteNode[]`
- [ ] Confirm Graphify does not encode Expo URL conventions

### Phase 1 — Filesystem routes

- [ ] Resolve routes dir (`app/` / `src/app/`)
- [ ] Walk files; apply notation → `url_path`
- [ ] Skip `_layout`, `+html`, non-route files
- [ ] Set `layout` from nearest `_layout.tsx`
- [ ] `RouteSource.FILESYSTEM`, confidence high for static; medium for dynamic `[param]`
- [ ] Unit tests on fixture trees (groups, index, dynamic, not-found)

### Phase 2 — Navigation

- [ ] `Link href` / object `pathname` via `parse_js`
- [ ] `router.push` / `replace` / `navigate` string args
- [ ] `Redirect href`
- [ ] File → route attach; shared chrome → entry/`(shared)` policy (reuse RR path builder)

### Phase 3 — Robustness

- [ ] Typed routes / generated types (if present) as optional cross-check
- [ ] Relative href resolution
- [ ] Nested groups + multiple layout roots
- [ ] Deep-link only routes / `+native-intent` gaps
- [ ] Optional TS miss-path when hrefs are re-exported constants

## Open questions

1. **Canonical dynamic form** — store `/users/[id]` (Expo) or `/users/:id` (RR-like)? Prefer Expo form for this plugin; document in `meta`.
2. **Duplicate index URLs** — `(tabs)/index.tsx` and root `index.tsx` both claim `/` — gap or pick by Expo resolution rules?
3. **Tabs vs stack** — are tab switches journeys, or only stack pushes? Default: any static `href`/`push` counts as an edge.
4. **Sample app** — pick an official Expo template or an internal demo with `expo-router` for golden fixtures.

## References

- [Journey architecture](./journey-architecture.md)
- [Framework popularity](./framework-popularity-report.md) — `expo-router` ~#7 by weekly downloads
- [Expo Router core concepts](https://docs.expo.dev/router/basics/core-concepts/)
- [Expo Router notation](https://docs.expo.dev/router/basics/notation/)
- [Navigating between pages](https://docs.expo.dev/router/basics/navigation/)
