import { useEffect, useState } from "react";
import { get, getToken, setToken } from "./api";
import Login from "./pages/Login";
import ProfilePage from "./pages/ProfilePage";
import JobsPage from "./pages/JobsPage";
import type { User } from "./types";

type Tab = "profile" | "jobs";

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [checking, setChecking] = useState(Boolean(getToken()));
  const [tab, setTab] = useState<Tab>("jobs");

  const loadMe = () =>
    get<User>("/auth/me")
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setChecking(false));

  useEffect(() => {
    if (getToken()) loadMe();
  }, []);

  if (checking) return <p className="center muted">Loading…</p>;
  if (!user) return <Login onLoggedIn={loadMe} />;

  return (
    <div className="shell">
      <header className="topbar">
        <strong>Job Auto Apply</strong>
        <nav>
          <button className={tab === "jobs" ? "tab active" : "tab"} onClick={() => setTab("jobs")}>Jobs</button>
          <button className={tab === "profile" ? "tab active" : "tab"} onClick={() => setTab("profile")}>Profile</button>
        </nav>
        <span className="muted small">{user.email}</span>
        <button
          className="link"
          onClick={() => {
            setToken(null);
            setUser(null);
          }}
        >
          Log out
        </button>
      </header>
      <main>{tab === "profile" ? <ProfilePage /> : <JobsPage />}</main>
    </div>
  );
}
