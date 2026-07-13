"""Expo Router filesystem + nav extraction tests."""

from __future__ import annotations

from pathlib import Path

from rhumb.framework import FrameworkDetection
from rhumb.journeys.expo_router import (
    ExpoRouterExtractor,
    collect_layouts,
    cross_check_typed_routes,
    extract_filesystem_routes,
    extract_nav_from_parse,
    file_to_route_url,
    find_app_root,
    parse_typed_routes,
    resolve_relative_href,
)
from rhumb.journeys.parse_js import parse_js_ts
from rhumb.journeys.paths import build_journeys


def _touch(path: Path, body: str = "export default function Page() { return null }\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _fixture_tree(tmp: Path) -> Path:
    """Doc example tree under ``app/``."""
    app = tmp / "app"
    _touch(app / "_layout.tsx")
    _touch(app / "index.tsx")
    _touch(app / "(auth)" / "_layout.tsx")
    _touch(app / "(auth)" / "sign-in.tsx")
    _touch(app / "(tabs)" / "_layout.tsx")
    _touch(
        app / "(tabs)" / "index.tsx",
        'import { Link } from "expo-router";\n'
        "export default function TabsHome() {\n"
        '  return <Link href="/settings">Settings</Link>;\n'
        "}\n",
    )
    _touch(
        app / "(tabs)" / "settings.tsx",
        'import { router } from "expo-router";\n'
        "export default function Settings() {\n"
        "  return null;\n"
        "}\n"
        "export function goProduct() {\n"
        '  router.push("/product/[id]");\n'
        "}\n",
    )
    _touch(app / "product" / "[id].tsx")
    _touch(app / "+not-found.tsx")
    _touch(app / "+html.tsx")  # skip
    _touch(app / "+native-intent.tsx")  # deep-link gap
    _touch(app / "_components" / "Button.tsx")  # private — skip
    (tmp / "package.json").write_text(
        '{"name":"expo-sample","dependencies":{"expo-router":"4.0.0"}}\n',
        encoding="utf-8",
    )
    return app


def test_file_to_route_url_notation() -> None:
    assert file_to_route_url(Path("about.tsx")) == ("/about", False, False)
    assert file_to_route_url(Path("index.tsx")) == ("/", True, False)
    assert file_to_route_url(Path("profile/index.tsx")) == ("/profile", True, False)
    assert file_to_route_url(Path("(tabs)/feed.tsx")) == ("/feed", False, False)
    assert file_to_route_url(Path("(app)/(tabs)/home.tsx")) == ("/home", False, False)
    assert file_to_route_url(Path("users/[id].tsx")) == ("/users/[id]", False, False)
    assert file_to_route_url(Path("[...slug].tsx")) == ("/[...slug]", False, True)
    assert file_to_route_url(Path("+not-found.tsx")) == ("*", False, True)
    assert file_to_route_url(Path("_layout.tsx")) is None
    assert file_to_route_url(Path("+html.tsx")) is None
    assert file_to_route_url(Path("+native-intent.tsx")) is None
    assert file_to_route_url(Path("_components/Button.tsx")) is None


def test_find_app_root_prefers_app_then_src(tmp_path: Path) -> None:
    assert find_app_root(tmp_path) is None
    src_app = tmp_path / "src" / "app"
    src_app.mkdir(parents=True)
    assert find_app_root(tmp_path) == src_app.resolve()
    app = tmp_path / "app"
    app.mkdir()
    assert find_app_root(tmp_path) == app.resolve()


def test_extract_filesystem_routes_fixture(tmp_path: Path) -> None:
    _fixture_tree(tmp_path)
    routes, gaps = extract_filesystem_routes(tmp_path)
    by_path = {r.url_path: r for r in routes}

    assert "/" in by_path
    assert "/sign-in" in by_path
    assert "/settings" in by_path
    assert "/product/[id]" in by_path
    assert "*" in by_path
    assert "+html" not in str(by_path)
    assert not any("Button" in (r.component or "") for r in routes)

    # Duplicate index: root index.tsx and (tabs)/index.tsx both → /
    assert any("duplicate URL /" in g.message for g in gaps)
    # Deep-link special file
    assert any("+native-intent" in g.message for g in gaps)

    settings = by_path["/settings"]
    assert settings.source.value == "filesystem"
    assert settings.layout is not None
    assert settings.layout.endswith("(tabs)/_layout.tsx")

    product = by_path["/product/[id]"]
    assert product.confidence.value == "medium"
    assert product.layout is not None
    assert product.layout.endswith("_layout.tsx")


def test_nested_groups_and_layout_chain(tmp_path: Path) -> None:
    app = tmp_path / "app"
    _touch(app / "_layout.tsx")
    _touch(app / "(app)" / "_layout.tsx")
    _touch(app / "(app)" / "(tabs)" / "_layout.tsx")
    _touch(app / "(app)" / "(tabs)" / "home.tsx")
    _touch(app / "(app)" / "(tabs)" / "profile.tsx")

    routes, gaps = extract_filesystem_routes(tmp_path)
    by_path = {r.url_path: r for r in routes}
    assert set(by_path) >= {"/home", "/profile"}
    assert not gaps

    home = by_path["/home"]
    assert home.layout is not None
    assert home.layout.endswith("(tabs)/_layout.tsx")

    layouts = collect_layouts(app, app / "(app)" / "(tabs)" / "home.tsx", tmp_path)
    assert len(layouts) == 3
    assert layouts[0].endswith("(tabs)/_layout.tsx")
    assert layouts[-1].endswith("app/_layout.tsx")


def test_canonicalize_expo_href() -> None:
    from rhumb.journeys.expo_router import canonicalize_expo_href

    assert canonicalize_expo_href("/(auth)/sign-in") == "/sign-in"
    assert canonicalize_expo_href("/(tabs)") == "/"
    assert canonicalize_expo_href("/(tabs)/add") == "/add"
    assert canonicalize_expo_href("/(tabs)/groups") == "/groups"
    assert canonicalize_expo_href("/settings/about?x=1") == "/settings/about"
    assert canonicalize_expo_href("/(auth)/verify-otp#top") == "/verify-otp"


def test_soften_template_href() -> None:
    from rhumb.journeys.expo_router import soften_template_href

    known = {"/group/[id]", "/expense/[id]", "/expense/group/[id]", "/add-expense", "/"}
    assert soften_template_href("/group/${group.id}", known) == "/group/[id]"
    assert soften_template_href("/expense/${item.id}", known) == "/expense/[id]"
    assert soften_template_href("/expense/group/${item.id}", known) == "/expense/group/[id]"
    assert soften_template_href("/add-expense?groupId=${id}", known) == "/add-expense"
    assert soften_template_href("/unknown/${id}", known) is None


def test_group_href_normalized_in_extractor(tmp_path: Path) -> None:
    app = tmp_path / "app"
    _touch(app / "_layout.tsx")
    _touch(app / "(auth)" / "_layout.tsx")
    _touch(
        app / "(auth)" / "sign-in.tsx",
        'import { router } from "expo-router";\n'
        "export default function SignIn() {\n"
        "  return null;\n"
        "}\n"
        "export function go() {\n"
        "  router.replace('/(tabs)');\n"
        "  router.push('/(auth)/forgot-password');\n"
        "}\n",
    )
    _touch(app / "(auth)" / "forgot-password.tsx")
    _touch(app / "(tabs)" / "_layout.tsx")
    _touch(app / "(tabs)" / "index.tsx")
    (tmp_path / "package.json").write_text(
        '{"dependencies":{"expo-router":"4.0.0"}}\n',
        encoding="utf-8",
    )
    graph = ExpoRouterExtractor().extract(
        tmp_path,
        FrameworkDetection(
            framework="expo-router",
            routing_style="filesystem",
            confidence="high",
            signals=["dependency: expo-router"],
        ),
    )
    targets = {(e.from_path, e.to_path) for e in graph.edges}
    assert ("/sign-in", "/") in targets
    assert ("/sign-in", "/forgot-password") in targets
    assert not any("nav target not in route tree" in g.message for g in graph.gaps)


def test_template_push_softens_to_dynamic_route(tmp_path: Path) -> None:
    app = tmp_path / "app"
    _touch(app / "_layout.tsx")
    _touch(app / "index.tsx")
    _touch(app / "group" / "[id]" / "index.tsx")
    _touch(
        app / "friends.tsx",
        'import { router } from "expo-router";\n'
        "export default function Friends() { return null }\n"
        "export function open(id: string) {\n"
        "  router.push(`/group/${id}`);\n"
        "}\n",
    )
    (tmp_path / "package.json").write_text(
        '{"dependencies":{"expo-router":"4.0.0"}}\n',
        encoding="utf-8",
    )
    graph = ExpoRouterExtractor().extract(
        tmp_path,
        FrameworkDetection(
            framework="expo-router",
            routing_style="filesystem",
            confidence="high",
            signals=["dependency: expo-router"],
        ),
    )
    assert any(e.to_path == "/group/[id]" for e in graph.edges)
    assert not any("dynamic router" in g.message for g in graph.gaps)

    assert resolve_relative_href("/abs", "/settings") == "/abs"
    assert resolve_relative_href("./about", "/settings") == "/about"
    assert resolve_relative_href("../sign-in", "/product/[id]") == "/sign-in"
    # /a/b → drop leaf b → /a; ../ pops a → /c
    assert resolve_relative_href("../c", "/a/b") == "/c"
    assert resolve_relative_href("../c", "/a/b/x") == "/a/c"
    assert resolve_relative_href("./x", None) is None


def test_extract_nav_link_and_router_push(tmp_path: Path) -> None:
    _fixture_tree(tmp_path)
    tabs_home = tmp_path / "app" / "(tabs)" / "index.tsx"
    parsed = parse_js_ts(tabs_home)
    edges, gaps = extract_nav_from_parse(parsed, "app/(tabs)/index.tsx", "/")
    assert not gaps
    assert any(e.to_path == "/settings" and e.kind == "link" for e in edges)

    settings = tmp_path / "app" / "(tabs)" / "settings.tsx"
    parsed2 = parse_js_ts(settings)
    edges2, gaps2 = extract_nav_from_parse(parsed2, "app/(tabs)/settings.tsx", "/settings")
    assert not gaps2
    assert any(e.to_path == "/product/[id]" and e.kind == "navigate" for e in edges2)


def test_relative_href_resolved_in_navigation(tmp_path: Path) -> None:
    app = tmp_path / "app"
    _touch(app / "_layout.tsx")
    _touch(app / "index.tsx")
    _touch(
        app / "product" / "[id].tsx",
        'import { Link } from "expo-router";\n'
        "export default function Product() {\n"
        '  return <Link href="../sign-in">Sign in</Link>;\n'
        "}\n",
    )
    _touch(app / "sign-in.tsx")
    (tmp_path / "package.json").write_text(
        '{"dependencies":{"expo-router":"4.0.0"}}\n',
        encoding="utf-8",
    )
    graph = ExpoRouterExtractor().extract(
        tmp_path,
        FrameworkDetection(
            framework="expo-router",
            routing_style="filesystem",
            confidence="high",
            signals=["dependency: expo-router"],
        ),
    )
    assert any(e.to_path == "/sign-in" and e.kind == "link" for e in graph.edges)
    assert not any("relative href unresolved" in g.message for g in graph.gaps)


def test_local_const_href_miss_path(tmp_path: Path) -> None:
    f = tmp_path / "Screen.tsx"
    f.write_text(
        'import { Link } from "expo-router";\n'
        "const DEST = '/settings';\n"
        "export default function S() { return <Link href={DEST} />; }\n",
        encoding="utf-8",
    )
    parsed = parse_js_ts(f)
    edges, gaps = extract_nav_from_parse(parsed, "Screen.tsx", None, project_dir=tmp_path)
    assert not gaps
    assert edges[0].to_path == "/settings"


def test_imported_const_and_object_href(tmp_path: Path) -> None:
    routes_mod = tmp_path / "routes.ts"
    routes_mod.write_text(
        'export const HOME = "/";\n'
        'export const ROUTES = { settings: "/settings" };\n',
        encoding="utf-8",
    )
    f = tmp_path / "Screen.tsx"
    f.write_text(
        'import { Link } from "expo-router";\n'
        'import { HOME, ROUTES } from "./routes";\n'
        "export default function S() {\n"
        "  return (\n"
        "    <>\n"
        "      <Link href={HOME} />\n"
        "      <Link href={ROUTES.settings} />\n"
        "    </>\n"
        "  );\n"
        "}\n",
        encoding="utf-8",
    )
    parsed = parse_js_ts(f)
    edges, gaps = extract_nav_from_parse(parsed, "Screen.tsx", None, project_dir=tmp_path)
    assert not gaps
    targets = {e.to_path for e in edges}
    assert targets >= {"/", "/settings"}


def test_truly_dynamic_href_still_gaps(tmp_path: Path) -> None:
    f = tmp_path / "Screen.tsx"
    f.write_text(
        'import { Link } from "expo-router";\n'
        "function getPath() { return '/x'; }\n"
        "export default function S() { return <Link href={getPath()} />; }\n",
        encoding="utf-8",
    )
    parsed = parse_js_ts(f)
    edges, gaps = extract_nav_from_parse(parsed, "Screen.tsx", None, project_dir=tmp_path)
    assert not edges
    assert any("dynamic Link href" in g.message for g in gaps)


def test_href_object_pathname(tmp_path: Path) -> None:
    f = tmp_path / "Screen.tsx"
    f.write_text(
        'import { Link } from "expo-router";\n'
        "export default function S() {\n"
        '  return <Link href={{ pathname: "/sign-in" }} />;\n'
        "}\n",
        encoding="utf-8",
    )
    parsed = parse_js_ts(f)
    edges, gaps = extract_nav_from_parse(parsed, "Screen.tsx", None)
    assert not gaps
    assert edges[0].to_path == "/sign-in"
    assert edges[0].kind == "link"


def test_parse_typed_routes_and_cross_check(tmp_path: Path) -> None:
    typed = (
        "declare namespace ExpoRouter {\n"
        "  type StaticRoutes =\n"
        "    | `/`\n"
        "    | `/settings`\n"
        "    | `/ghost`;\n"
        "  type DynamicRoutes =\n"
        "    | `/product/${string}`;\n"
        "  type Href =\n"
        "    | StaticRoutes\n"
        "    | { pathname: `/sign-in` };\n"
        "}\n"
    )
    assert parse_typed_routes(typed) >= {
        "/",
        "/settings",
        "/ghost",
        "/sign-in",
        "/product/[param]",
    }

    app = tmp_path / "app"
    _touch(app / "index.tsx")
    _touch(app / "settings.tsx")
    # missing /ghost on FS; FS has no /sign-in
    typed_dir = tmp_path / ".expo" / "types"
    typed_dir.mkdir(parents=True)
    (typed_dir / "router.d.ts").write_text(typed, encoding="utf-8")

    routes, _ = extract_filesystem_routes(tmp_path)
    gaps, meta = cross_check_typed_routes(tmp_path, routes)
    assert meta["typed_routes"].endswith("router.d.ts")
    assert any("typed route not found on filesystem: /ghost" in g.message for g in gaps)
    assert any("typed route not found on filesystem: /sign-in" in g.message for g in gaps)


def test_expo_router_extractor_end_to_end(tmp_path: Path) -> None:
    _fixture_tree(tmp_path)
    # Avoid duplicate-/ by dropping root index; keep tabs index as /
    (tmp_path / "app" / "index.tsx").unlink()

    detection = FrameworkDetection(
        framework="expo-router",
        routing_style="filesystem",
        confidence="high",
        signals=["dependency: expo-router"],
        root=None,
    )
    graph = ExpoRouterExtractor().extract(tmp_path, detection)
    by_path = {r.url_path for r in graph.routes}
    assert by_path >= {"/", "/sign-in", "/settings", "/product/[id]", "*"}
    assert graph.meta["dynamic_form"] == "expo"
    assert graph.meta["route_source"] == "filesystem"
    assert int(graph.meta["max_layout_depth"]) >= 1
    assert any(e.to_path == "/settings" for e in graph.edges)
    assert any("+native-intent" in g.message for g in graph.gaps)

    journeys = build_journeys(graph)
    assert isinstance(journeys, tuple)
