# Framework Popularity Report (NPM Downloads)

**Generated:** 2026-07-09  
**Source:** [npm registry downloads API](https://api.npmjs.org/downloads/) — `last-week` window (2026-07-02 → 2026-07-08)  
**Scope:** Frameworks detected by `rhumb.framework.detect_all_frameworks()`

## Ranking

| Rank | Framework ID | NPM package (primary) | Weekly downloads |
|------|--------------|----------------------|------------------|
| 1 | `vite-react` | `@vitejs/plugin-react` * | 66,858,545 |
| 2 | `react-router` | `react-router` | 50,160,762 |
| 3 | `next` | `next` | 41,826,565 |
| 4 | `tanstack-router` | `@tanstack/react-router` | 22,024,125 |
| 5 | `vue-router` | `vue-router` | 6,812,743 |
| 6 | `angular` | `@angular/router` | 4,622,334 |
| 7 | `expo-router` | `expo-router` | 4,152,745 |
| 8 | `sveltekit` | `@sveltejs/kit` | 2,063,310 |
| 9 | `remix` | `@remix-run/react` | 1,003,724 |

## Alternate stats

| Framework | Alternate package | Weekly downloads |
|-----------|-------------------|------------------|
| `react-router` | `react-router-dom` | 44,527,827 |
| `angular` | `@angular/core` | 5,472,313 |
| `vite-react` | `create-vite` | 695,238 |

## Caveats

- **`vite-react`** has no single npm package. `@vitejs/plugin-react` is the best proxy (Vite + React projects); it is also pulled in by other stacks.
- **`react-router`** detection accepts `react-router` or `react-router-dom`; either package keeps it at #2.
- **Shared dependencies** — `react` (~146M/wk) and `vite` (~153M/wk) are used across many stacks; this table uses framework-specific packages only.
- **Remix overlap** — Remix merged into React Router v7; `@remix-run/react` undercounts total Remix-style usage.
- **Download ≠ production share** — CI, mirrors, and transitive installs inflate numbers; use as relative signal, not absolute market share.

## Journey implementation priority

By npm reach among detected frameworks:

1. `react-router`
2. `next`
3. `tanstack-router`
4. `vue-router`
5. `angular`
6. `expo-router`, `sveltekit`, `remix`, `vite-react`

## Live comparison

- [npmtrends — all nine packages](https://npmtrends.com/next-vs-react-router-vs-@tanstack/react-router-vs-vue-router-vs-@angular/router-vs-@sveltejs/kit-vs-expo-router-vs-@remix-run/react-vs-@vitejs/plugin-react)
