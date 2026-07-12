"""Phase 1 route-tree tests — JSX sample shaped like free-react-tailwind App.tsx."""

from __future__ import annotations

from pathlib import Path

from deterministic_kit.framework import FrameworkDetection
from deterministic_kit.journeys.parse_js import extract_imports, parse_js_ts
from deterministic_kit.journeys.react_router import (
    ReactRouterExtractor,
    extract_nav_from_parse,
    extract_routes_from_parse,
    join_route_paths,
)

SAMPLE_APP = '''\
import { BrowserRouter as Router, Routes, Route } from "react-router";
import SignIn from "./pages/AuthPages/SignIn";
import NotFound from "./pages/OtherPage/NotFound";
import UserProfiles from "./pages/UserProfiles";
import AppLayout from "./layout/AppLayout";
import Home from "./pages/Dashboard/Home";

export default function App() {
  return (
    <>
      <Router>
        <Routes>
          <Route element={<AppLayout />}>
            <Route index path="/" element={<Home />} />
            <Route path="/profile" element={<UserProfiles />} />
          </Route>
          <Route path="/signin" element={<SignIn />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </Router>
    </>
  );
}
'''


def _write_sample(tmp: Path) -> Path:
    app = tmp / "src" / "App.tsx"
    app.parent.mkdir(parents=True)
    app.write_text(SAMPLE_APP, encoding="utf-8")
    for rel in (
        "pages/AuthPages/SignIn.tsx",
        "pages/OtherPage/NotFound.tsx",
        "pages/UserProfiles.tsx",
        "layout/AppLayout.tsx",
        "pages/Dashboard/Home.tsx",
    ):
        path = tmp / "src" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"export default function {path.stem}() {{ return null }}\n",
            encoding="utf-8",
        )
    (tmp / "package.json").write_text(
        '{"name":"sample","dependencies":{"react-router":"7.1.5"}}\n',
        encoding="utf-8",
    )
    return app


def test_parse_js_ts_ok_for_tsx(tmp_path: Path) -> None:
    app = _write_sample(tmp_path)
    result = parse_js_ts(app)
    assert result.ok
    assert result.backend == "tree_sitter"
    assert result.root is not None
    imports = extract_imports(result)
    assert imports["Home"] == "./pages/Dashboard/Home"
    assert imports["AppLayout"] == "./layout/AppLayout"


def test_join_route_paths() -> None:
    assert join_route_paths("", "/", True) == "/"
    assert join_route_paths("", "/profile", False) == "/profile"
    assert join_route_paths("/app", "users", False) == "/app/users"
    assert join_route_paths("/app", "/absolute", False) == "/absolute"
    assert join_route_paths("/app", "*", False) == "*"
    assert join_route_paths("/app", None, True) == "/app"


def test_extract_routes_path_join_and_layout(tmp_path: Path) -> None:
    app = _write_sample(tmp_path)
    parsed = parse_js_ts(app)
    routes, gaps = extract_routes_from_parse(parsed, "src/App.tsx", tmp_path)
    by_path = {r.url_path: r for r in routes}

    assert set(by_path) >= {"/", "/profile", "/signin", "*"}
    home = by_path["/"]
    assert home.is_index
    assert home.component == "src/pages/Dashboard/Home.tsx"
    assert home.layout == "src/layout/AppLayout.tsx"
    assert home.confidence.value == "high"
    assert home.source.value == "config_ast"

    profile = by_path["/profile"]
    assert profile.component == "src/pages/UserProfiles.tsx"
    assert profile.layout == "src/layout/AppLayout.tsx"

    signin = by_path["/signin"]
    assert signin.layout is None
    assert signin.component == "src/pages/AuthPages/SignIn.tsx"

    assert by_path["*"].is_wildcard
    assert not gaps


def test_react_router_extractor(tmp_path: Path) -> None:
    _write_sample(tmp_path)
    detection = FrameworkDetection(
        framework="react-router",
        routing_style="config",
        confidence="high",
        signals=["dependency: react-router"],
        root=None,
        package_name="sample",
    )
    graph = ReactRouterExtractor().extract(tmp_path, detection)
    assert graph.meta["parser"] == "tree_sitter"
    paths = {r.url_path for r in graph.routes}
    assert paths >= {"/", "/profile", "/signin", "*"}
    assert all(r.confidence.value == "high" for r in graph.routes)


SIDEBAR = '''\
import { Link } from "react-router";

const navItems = [
  { name: "Home", path: "/" },
  { name: "Profile", path: "/profile" },
  { name: "Missing", path: "/missing-page" },
];

export default function AppSidebar() {
  return (
    <aside>
      <Link to="/">Logo</Link>
      <Link to={navItems[0].path}>Dyn</Link>
    </aside>
  );
}
'''

HOME_PAGE = '''\
import { Link, useNavigate } from "react-router";

export default function Home() {
  const navigate = useNavigate();
  return (
    <div>
      <Link to="/profile">Profile</Link>
      <button onClick={() => navigate("/signin")}>Go</button>
      <button onClick={() => navigate(-1)}>Back</button>
    </div>
  );
}
'''

NOT_FOUND = '''\
import { Link } from "react-router";

export default function NotFound() {
  return <Link to="/">Back home</Link>;
}
'''


def _write_nav_sample(tmp: Path) -> None:
    _write_sample(tmp)
    (tmp / "src" / "layout" / "AppSidebar.tsx").write_text(SIDEBAR, encoding="utf-8")
    (tmp / "src" / "pages" / "Dashboard" / "Home.tsx").write_text(HOME_PAGE, encoding="utf-8")
    (tmp / "src" / "pages" / "OtherPage" / "NotFound.tsx").write_text(NOT_FOUND, encoding="utf-8")


def test_extract_nav_link_navigate_and_config(tmp_path: Path) -> None:
    _write_nav_sample(tmp_path)
    detection = FrameworkDetection(
        framework="react-router",
        routing_style="config",
        confidence="high",
        signals=["dependency: react-router"],
    )
    graph = ReactRouterExtractor().extract(tmp_path, detection)

    kinds = {e.kind for e in graph.edges}
    assert "link" in kinds
    assert "navigate" in kinds
    assert "nav_config" in kinds

    # Sidebar nav_config (layout shell → from_path None)
    config_targets = {
        e.to_path for e in graph.edges if e.kind == "nav_config" and "AppSidebar" in e.source_file
    }
    assert config_targets >= {"/", "/profile", "/missing-page"}

    # Home page Link attached to route /
    home_links = [
        e
        for e in graph.edges
        if e.kind == "link" and e.source_file.endswith("Home.tsx") and e.to_path == "/profile"
    ]
    assert home_links
    assert home_links[0].from_path == "/"

    # navigate("/") string kept; navigate(-1) skipped
    nav_edges = [e for e in graph.edges if e.kind == "navigate"]
    assert any(e.to_path == "/signin" for e in nav_edges)
    assert all(e.to_path != "-1" for e in nav_edges)

    # Dynamic Link to={...} not emitted as link from sidebar logo-only static
    sidebar_links = [
        e for e in graph.edges if e.kind == "link" and "AppSidebar" in e.source_file
    ]
    assert any(e.to_path == "/" for e in sidebar_links)
    assert all(e.from_path is None for e in sidebar_links)

    assert any("not in route tree: /missing-page" in g.message for g in graph.gaps)


def test_extract_nav_from_parse_skips_history_back(tmp_path: Path) -> None:
    path = tmp_path / "useGoBack.ts"
    path.write_text(
        "export function go(navigate: (x: string | number) => void) {\n"
        "  navigate(-1);\n"
        '  navigate("/");\n'
        "}\n",
        encoding="utf-8",
    )
    parsed = parse_js_ts(path)
    edges = extract_nav_from_parse(parsed, "useGoBack.ts", None)
    assert len(edges) == 1
    assert edges[0].kind == "navigate"
    assert edges[0].to_path == "/"


def test_utf8_multibyte_before_link_still_parses(tmp_path: Path) -> None:
    """tree-sitter byte offsets must not be sliced as Unicode code points."""
    path = tmp_path / "NotFound.tsx"
    path.write_text(
        'import { Link } from "react-router";\n'
        "export default function NotFound() {\n"
        "  return (\n"
        "    <div>\n"
        "      <p>We can\u2019t seem to find the page!</p>\n"
        '      <Link to="/">Back</Link>\n'
        "    </div>\n"
        "  );\n"
        "}\n",
        encoding="utf-8",
    )
    parsed = parse_js_ts(path)
    edges = extract_nav_from_parse(parsed, "NotFound.tsx", "*")
    assert len(edges) == 1
    assert edges[0].to_path == "/"
    assert edges[0].from_path == "*"


def test_create_browser_router_objects_lazy_and_spread(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "pages").mkdir()
    (tmp_path / "src" / "routes").mkdir()
    (tmp_path / "src" / "pages" / "Home.tsx").write_text(
        "export default function Home() { return null }\n", encoding="utf-8"
    )
    (tmp_path / "src" / "pages" / "About.tsx").write_text(
        "export default function About() { return null }\n", encoding="utf-8"
    )
    (tmp_path / "src" / "pages" / "Login.tsx").write_text(
        "export default function Login() { return null }\n", encoding="utf-8"
    )
    (tmp_path / "src" / "routes" / "auth.tsx").write_text(
        'import Login from "../pages/Login";\n'
        "export const authRoutes = [\n"
        '  { path: "/login", Component: Login },\n'
        "];\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "router.tsx").write_text(
        'import { createBrowserRouter } from "react-router";\n'
        'import Home from "./pages/Home";\n'
        'import { authRoutes } from "./routes/auth";\n'
        "const router = createBrowserRouter([\n"
        "  {\n"
        '    path: "/",\n'
        "    Component: Home,\n"
        "    children: [\n"
        "      { index: true, Component: Home },\n"
        '      { path: "about", lazy: () => import("./pages/About") },\n'
        "      ...authRoutes,\n"
        "    ],\n"
        "  },\n"
        '  { path: `/users/${id}`, Component: Home },\n'
        "]);\n"
        "export default router;\n",
        encoding="utf-8",
    )
    (tmp_path / "package.json").write_text(
        '{"name":"rr","dependencies":{"react-router":"7.0.0"}}\n',
        encoding="utf-8",
    )

    detection = FrameworkDetection(
        framework="react-router",
        routing_style="config",
        confidence="high",
        signals=["dependency: react-router"],
    )
    graph = ReactRouterExtractor().extract(tmp_path, detection)
    by_path = {r.url_path: r for r in graph.routes}

    assert "/" in by_path
    assert by_path["/"].component and "Home" in by_path["/"].component
    assert "/about" in by_path
    assert by_path["/about"].component and "About" in by_path["/about"].component
    assert "/login" in by_path
    assert by_path["/login"].component and "Login" in by_path["/login"].component

    dynamic = [r for r in graph.routes if "users" in r.url_path]
    assert dynamic
    assert dynamic[0].confidence.value == "low"
    assert any("dynamic template route path" in g.message for g in graph.gaps)


def test_create_routes_from_elements(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "Home.tsx").write_text(
        "export default function Home() { return null }\n", encoding="utf-8"
    )
    (tmp_path / "src" / "App.tsx").write_text(
        'import { createRoutesFromElements, Route } from "react-router";\n'
        'import Home from "./Home";\n'
        "const routes = createRoutesFromElements(\n"
        '  <Route path="/" element={<Home />}>\n'
        '    <Route path="dash" element={<Home />} />\n'
        "  </Route>\n"
        ");\n"
        "export default routes;\n",
        encoding="utf-8",
    )
    (tmp_path / "package.json").write_text(
        '{"name":"rr","dependencies":{"react-router":"7.0.0"}}\n',
        encoding="utf-8",
    )
    graph = ReactRouterExtractor().extract(
        tmp_path,
        FrameworkDetection(
            framework="react-router",
            routing_style="config",
            confidence="high",
            signals=["dependency: react-router"],
        ),
    )
    paths = {r.url_path for r in graph.routes}
    assert "/" in paths
    assert "/dash" in paths
