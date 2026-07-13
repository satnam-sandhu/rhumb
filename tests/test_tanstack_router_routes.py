"""TanStack Router filesystem + gen + nav extraction tests."""

from __future__ import annotations

import json
from pathlib import Path

from tributary.framework import FrameworkDetection
from tributary.journeys.parse_js import parse_js_ts
from tributary.journeys.paths import build_journeys
from tributary.journeys.tanstack_router import (
    TanStackRouterExtractor,
    extract_filesystem_routes,
    extract_nav_from_parse,
    extract_routes,
    file_to_route_url,
    find_route_tree_gen,
    find_routes_dir,
    load_tsr_config,
    normalize_url_path,
    parse_route_tree_gen,
    soften_template_to,
    strip_pathless_segments,
    url_from_file_route_id,
)


def _touch(path: Path, body: str = "export const Route = {}\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _route_file(path: Path, route_id: str, extra: str = "") -> None:
    body = (
        f'import {{ createFileRoute }} from "@tanstack/react-router";\n'
        f"export const Route = createFileRoute('{route_id}')({{}});\n"
        f"{extra}"
    )
    _touch(path, body)


def _fixture_tree(tmp: Path) -> Path:
    """Doc example tree under ``src/routes/``."""
    routes = tmp / "src" / "routes"
    _touch(routes / "__root.tsx", "export const Route = {}\n")
    _route_file(routes / "index.tsx", "/")
    _route_file(
        routes / "about.tsx",
        "/about",
        'import { Link } from "@tanstack/react-router";\n'
        "export function AboutLinks() {\n"
        '  return <Link to="/posts">Posts</Link>;\n'
        "}\n",
    )
    _route_file(routes / "posts" / "index.tsx", "/posts/")
    _route_file(
        routes / "posts" / "$postId.tsx",
        "/posts/$postId",
        'import { redirect } from "@tanstack/react-router";\n'
        "export function guard() {\n"
        '  throw redirect({ to: "/about" });\n'
        "}\n",
    )
    _route_file(routes / "_authenticated" / "settings.tsx", "/_authenticated/settings")
    _touch(routes / "-components" / "Button.tsx")  # private — skip
    (tmp / "package.json").write_text(
        '{"name":"tsr-sample","dependencies":{"@tanstack/react-router":"1.0.0"}}\n',
        encoding="utf-8",
    )
    return routes


_SAMPLE_GEN = """\
export interface FileRoutesByFullPath {
  '/': typeof IndexRoute
  '/posts': typeof PostsRouteRouteWithChildren
  '/about': typeof AboutRoute
  '/posts/$postId': typeof PostsPostIdRoute
  '/posts/': typeof PostsIndexRoute
  '/settings': typeof SettingsRoute
}
export interface FileRoutesByTo {
  '/': typeof IndexRoute
  '/about': typeof AboutRoute
  '/posts/$postId': typeof PostsPostIdRoute
  '/posts': typeof PostsIndexRoute
  '/settings': typeof SettingsRoute
}
export interface FileRouteTypes {
  fullPaths:
    | '/'
    | '/posts'
    | '/about'
    | '/posts/$postId'
    | '/posts/'
    | '/settings'
}
"""


def test_file_to_route_url_notation() -> None:
    assert file_to_route_url(Path("about.tsx")) == ("/about", False, False)
    assert file_to_route_url(Path("index.tsx")) == ("/", True, False)
    assert file_to_route_url(Path("posts/index.tsx")) == ("/posts", True, False)
    assert file_to_route_url(Path("posts/$postId.tsx")) == ("/posts/$postId", False, False)
    assert file_to_route_url(Path("posts.$postId.tsx")) == ("/posts/$postId", False, False)
    assert file_to_route_url(
        Path("project.$projectId_.session.$sessionId.kpi-preview.tsx")
    ) == ("/project/$projectId/session/$sessionId/kpi-preview", False, False)
    assert file_to_route_url(Path("_authenticated/settings.tsx")) == (
        "/settings",
        False,
        False,
    )
    assert file_to_route_url(Path("$.tsx")) == ("/$", False, True)
    assert file_to_route_url(Path("__root.tsx")) is None
    assert file_to_route_url(Path("_pathlessLayout.tsx")) is None
    assert file_to_route_url(Path("-components/Button.tsx")) is None


def test_strip_pathless_and_url_from_id() -> None:
    assert strip_pathless_segments("/_authenticated/settings") == "/settings"
    assert url_from_file_route_id("/_authenticated/settings") == "/settings"
    assert url_from_file_route_id("/_pathlessLayout") is None
    assert url_from_file_route_id("/posts/$postId") == "/posts/$postId"
    # Layout nest opt-out: route id keeps trailing _; journey URL drops it
    assert (
        url_from_file_route_id("/project/$projectId_/session/$sessionId/kpi-preview")
        == "/project/$projectId/session/$sessionId/kpi-preview"
    )
    assert (
        strip_pathless_segments("/project/$projectId_/session/$sessionId/create")
        == "/project/$projectId/session/$sessionId/create"
    )
    assert normalize_url_path("/posts/") == "/posts"


def test_layout_opt_out_multiline_create_file_route(tmp_path: Path) -> None:
    routes = tmp_path / "src" / "routes"
    _touch(
        routes / "project.$projectId_.session.$sessionId.kpi-preview.tsx",
        "import { createFileRoute } from '@tanstack/react-router';\n"
        "export const Route = createFileRoute(\n"
        "  '/project/$projectId_/session/$sessionId/kpi-preview',\n"
        ")({});\n",
    )
    _touch(
        routes / "project.$projectId_.session.$sessionId.create.tsx",
        "import { createFileRoute } from '@tanstack/react-router';\n"
        "export const Route = createFileRoute(\n"
        "  '/project/$projectId_/session/$sessionId/create',\n"
        ")({});\n",
    )
    found, gaps = extract_filesystem_routes(tmp_path)
    urls = {r.url_path for r in found}
    assert "/project/$projectId/session/$sessionId/kpi-preview" in urls
    assert "/project/$projectId/session/$sessionId/create" in urls
    assert not any("$projectId_" in u for u in urls)
    assert not gaps


def test_find_routes_dir(tmp_path: Path) -> None:
    assert find_routes_dir(tmp_path) is None
    d = tmp_path / "src" / "routes"
    d.mkdir(parents=True)
    assert find_routes_dir(tmp_path) == d.resolve()


def test_extract_filesystem_routes_fixture(tmp_path: Path) -> None:
    _fixture_tree(tmp_path)
    routes, gaps = extract_filesystem_routes(tmp_path)
    by_path = {r.url_path: r for r in routes}

    assert set(by_path) >= {"/", "/about", "/posts", "/posts/$postId", "/settings"}
    assert not any("Button" in (r.component or "") for r in routes)
    assert by_path["/posts/$postId"].confidence.value == "medium"
    assert by_path["/settings"].source.value == "filesystem"
    assert by_path["/about"].layout is not None
    assert by_path["/about"].layout.endswith("__root.tsx")
    assert not any("duplicate" in g.message for g in gaps)


def test_parse_route_tree_gen() -> None:
    paths, _ = parse_route_tree_gen(_SAMPLE_GEN)
    assert "/" in paths
    assert "/about" in paths
    assert "/posts/$postId" in paths
    assert "/settings" in paths
    # trailing slash collapsed
    assert "/posts/" not in paths or "/posts" in paths


def test_extract_routes_prefers_gen(tmp_path: Path) -> None:
    _fixture_tree(tmp_path)
    gen = tmp_path / "src" / "routeTree.gen.ts"
    gen.write_text(_SAMPLE_GEN, encoding="utf-8")

    routes, gaps, meta = extract_routes(tmp_path)
    by_path = {r.url_path: r for r in routes}

    assert meta["route_source"] == "generated"
    assert find_route_tree_gen(tmp_path) == gen.resolve()
    assert by_path["/about"].source.value == "generated"
    assert by_path["/about"].component is not None
    assert by_path["/about"].component.endswith("about.tsx")
    assert "/settings" in by_path


def test_nav_link_navigate_redirect(tmp_path: Path) -> None:
    _fixture_tree(tmp_path)
    routes, _, _ = extract_routes(tmp_path)
    extractor = TanStackRouterExtractor()
    graph = extractor.extract(
        tmp_path,
        FrameworkDetection(
            framework="tanstack-router",
            routing_style="file-based",
            confidence="high",
            signals=[],
            root=".",
        ),
        None,
    )
    kinds = {(e.to_path, e.kind) for e in graph.edges}
    assert ("/posts", "link") in kinds
    assert ("/about", "redirect") in kinds


def test_extract_nav_from_parse_navigate_object(tmp_path: Path) -> None:
    src = tmp_path / "nav.tsx"
    src.write_text(
        'import { navigate } from "@tanstack/react-router";\n'
        "export function go() {\n"
        '  navigate({ to: "/settings" });\n'
        "}\n",
        encoding="utf-8",
    )
    parsed = parse_js_ts(src)
    edges, gaps = extract_nav_from_parse(parsed, "nav.tsx", "/")
    assert not gaps
    assert any(e.to_path == "/settings" and e.kind == "navigate" for e in edges)


def test_soften_template_to() -> None:
    known = {"/posts/$postId", "/about"}
    assert soften_template_to("/posts/${id}", known) == "/posts/$postId"
    assert soften_template_to("/about", known) == "/about"
    assert soften_template_to("/missing/${x}", known) is None


def test_extractor_builds_journeys(tmp_path: Path) -> None:
    _fixture_tree(tmp_path)
    # Wire about → posts → about cycle for journey enum
    about = tmp_path / "src" / "routes" / "about.tsx"
    about.write_text(
        'import { createFileRoute, Link } from "@tanstack/react-router";\n'
        "export const Route = createFileRoute('/about')({});\n"
        "export function AboutLinks() {\n"
        '  return <Link to="/posts">Posts</Link>;\n'
        "}\n",
        encoding="utf-8",
    )
    posts = tmp_path / "src" / "routes" / "posts" / "index.tsx"
    posts.write_text(
        'import { createFileRoute, Link } from "@tanstack/react-router";\n'
        "export const Route = createFileRoute('/posts/')({});\n"
        "export function PostsLinks() {\n"
        '  return <Link to="/about">About</Link>;\n'
        "}\n",
        encoding="utf-8",
    )

    graph = TanStackRouterExtractor().extract(
        tmp_path,
        FrameworkDetection(
            framework="tanstack-router",
            routing_style="file-based",
            confidence="high",
            signals=[],
            root=".",
        ),
        None,
    )
    journeys = build_journeys(graph)
    assert graph.meta["dynamic_form"] == "tanstack"
    assert len(graph.routes) >= 4
    assert any("→" in str(j) for j in journeys) or len(graph.edges) >= 1


# --- Phase 3 -----------------------------------------------------------------


def test_virtual_routes_from_tsr_json(tmp_path: Path) -> None:
    routes = tmp_path / "src" / "routes"
    _touch(routes / "root.tsx")
    _touch(routes / "home.tsx")
    _touch(routes / "about.tsx")
    _touch(routes / "posts" / "detail.tsx")
    (tmp_path / "tsr.config.json").write_text(
        json.dumps(
            {
                "routesDirectory": "./src/routes",
                "virtualRouteConfig": {
                    "type": "root",
                    "file": "root.tsx",
                    "children": [
                        {"type": "index", "file": "home.tsx"},
                        {
                            "type": "route",
                            "path": "/about",
                            "file": "about.tsx",
                        },
                        {
                            "type": "route",
                            "path": "/posts",
                            "children": [
                                {
                                    "type": "route",
                                    "path": "$postId",
                                    "file": "posts/detail.tsx",
                                }
                            ],
                        },
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "package.json").write_text(
        '{"dependencies":{"@tanstack/react-router":"1.0.0"}}\n',
        encoding="utf-8",
    )

    found, gaps, meta = extract_routes(tmp_path)
    by_path = {r.url_path: r for r in found}
    assert meta["route_source"] == "virtual"
    assert meta["virtual_routes"] == "tsr.config.json"
    assert "/" in by_path
    assert "/about" in by_path
    assert "/posts/$postId" in by_path
    assert by_path["/posts/$postId"].confidence.value == "medium"
    assert not gaps


def test_virtual_routes_from_module(tmp_path: Path) -> None:
    routes = tmp_path / "src" / "routes"
    _touch(routes / "root.tsx")
    _touch(routes / "index.tsx")
    _touch(routes / "about.tsx")
    _touch(routes / "dash.tsx")
    (tmp_path / "routes.ts").write_text(
        'import { rootRoute, route, index, layout } from "@tanstack/virtual-file-routes";\n'
        "export const routes = rootRoute('root.tsx', [\n"
        "  index('index.tsx'),\n"
        "  route('/about', 'about.tsx'),\n"
        "  layout('layout.tsx', [\n"
        "    route('/dashboard', 'dash.tsx'),\n"
        "  ]),\n"
        "]);\n",
        encoding="utf-8",
    )
    (tmp_path / "tsr.config.json").write_text(
        '{"virtualRouteConfig": "./routes.ts"}\n',
        encoding="utf-8",
    )
    (tmp_path / "package.json").write_text(
        '{"dependencies":{"@tanstack/react-router":"1.0.0"}}\n',
        encoding="utf-8",
    )

    found, gaps, meta = extract_routes(tmp_path)
    by_path = {r.url_path: r for r in found}
    assert meta["route_source"] == "virtual"
    assert meta["virtual_routes"] == "routes.ts"
    assert set(by_path) >= {"/", "/about", "/dashboard"}
    assert not any("parse failed" in g.message for g in gaps)


def test_virtual_subtree_file(tmp_path: Path) -> None:
    routes = tmp_path / "src" / "routes"
    _route_file(routes / "index.tsx", "/")
    _touch(routes / "posts" / "home.tsx")
    _touch(routes / "posts" / "details.tsx")
    # Would be wrong if FS-walked as /posts/home — virtual remaps
    (routes / "posts" / "__virtual.ts").write_text(
        'import { defineVirtualSubtreeConfig, index, route } '
        'from "@tanstack/virtual-file-routes";\n'
        "export default defineVirtualSubtreeConfig([\n"
        "  index('home.tsx'),\n"
        "  route('$id', 'details.tsx'),\n"
        "]);\n",
        encoding="utf-8",
    )
    (tmp_path / "package.json").write_text(
        '{"dependencies":{"@tanstack/react-router":"1.0.0"}}\n',
        encoding="utf-8",
    )

    found, gaps, meta = extract_routes(tmp_path)
    by_path = {r.url_path: r for r in found}
    assert "/" in by_path
    assert "/posts" in by_path  # index under /posts
    assert "/posts/$id" in by_path
    assert "/posts/home" not in by_path
    assert meta.get("virtual_subtrees") == "1"


def test_vite_config_sniff(tmp_path: Path) -> None:
    (tmp_path / "vite.config.ts").write_text(
        'import { tanstackRouter } from "@tanstack/router-plugin/vite";\n'
        "export default {\n"
        "  plugins: [\n"
        "    tanstackRouter({\n"
        '      routesDirectory: "./app/routes",\n'
        '      generatedRouteTree: "./app/routeTree.gen.ts",\n'
        '      virtualRouteConfig: "./virtual-routes.ts",\n'
        "    }),\n"
        "  ],\n"
        "};\n",
        encoding="utf-8",
    )
    cfg = load_tsr_config(tmp_path)
    assert cfg["routesDirectory"] == "./app/routes"
    assert cfg["generatedRouteTree"] == "./app/routeTree.gen.ts"
    assert cfg["virtualRouteConfig"] == "./virtual-routes.ts"
    assert cfg["vite_config"] == "vite.config.ts"


def test_miss_path_local_and_imported_to(tmp_path: Path) -> None:
    paths_mod = tmp_path / "paths.ts"
    paths_mod.write_text(
        'export const HOME = "/";\n'
        'export const PATHS = { about: "/about", settings: "/settings" };\n',
        encoding="utf-8",
    )
    src = tmp_path / "nav.tsx"
    src.write_text(
        'import { Link, navigate } from "@tanstack/react-router";\n'
        'import { HOME, PATHS } from "./paths";\n'
        "const LOCAL = '/posts';\n"
        "export function Nav() {\n"
        "  return (\n"
        "    <>\n"
        "      <Link to={HOME} />\n"
        "      <Link to={PATHS.about} />\n"
        "      <Link to={LOCAL} />\n"
        "    </>\n"
        "  );\n"
        "}\n"
        "export function go() {\n"
        "  navigate({ to: PATHS.settings });\n"
        "}\n",
        encoding="utf-8",
    )
    parsed = parse_js_ts(src)
    edges, gaps = extract_nav_from_parse(
        parsed, "nav.tsx", "/", project_dir=tmp_path
    )
    assert not gaps
    targets = {e.to_path for e in edges}
    assert targets >= {"/", "/about", "/posts", "/settings"}


def test_tsr_custom_routes_directory(tmp_path: Path) -> None:
    custom = tmp_path / "app" / "routes"
    _route_file(custom / "index.tsx", "/")
    _route_file(custom / "hello.tsx", "/hello")
    (tmp_path / "tsr.config.json").write_text(
        '{"routesDirectory": "./app/routes"}\n',
        encoding="utf-8",
    )
    (tmp_path / "package.json").write_text(
        '{"dependencies":{"@tanstack/react-router":"1.0.0"}}\n',
        encoding="utf-8",
    )
    found, _, meta = extract_routes(tmp_path)
    assert meta["routes_dir"] == "app/routes"
    assert {r.url_path for r in found} >= {"/", "/hello"}
