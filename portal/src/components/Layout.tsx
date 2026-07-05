import { Outlet, Link, useLocation } from "react-router-dom";

export default function Layout() {
  const location = useLocation();

  const nav = [
    { path: "/", label: "Dashboard" },
    { path: "/chat", label: "Agent Chat" },
    { path: "/failures", label: "Failures" },
    { path: "/wiki", label: "Wiki" },
    { path: "/repositories", label: "Repositories" },
    { path: "/access", label: "Access" },
    { path: "/security", label: "Security" },
    { path: "/settings", label: "Settings" },
  ];

  return (
    <div className="layout">
      <header className="layout-header">
        <Link to="/" className="logo">
          <span className="logo-icon">⟡</span> Tracebow
        </Link>
        <p className="tagline">Local AI Root Cause Analysis for CI/CD</p>
        <nav className="nav">
          {nav.map(({ path, label }) => (
            <Link
              key={path}
              to={path}
              className={location.pathname === path ? "active" : ""}
            >
              {label}
            </Link>
          ))}
        </nav>
      </header>
      <main className="layout-main">
        <Outlet />
      </main>
    </div>
  );
}
