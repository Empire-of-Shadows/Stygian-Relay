import { useEffect, useState } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { Header } from "./components/Header";
import { Footer } from "./components/Footer";
import { api, UnauthorizedError } from "./api/client";
import type { Me } from "./api/types";
import { LoginPage } from "./pages/LoginPage";
import { DashboardPage } from "./pages/DashboardPage";
import { GuildPage } from "./pages/GuildPage";
import { RulesPage } from "./pages/RulesPage";
import { RuleEditorPage } from "./pages/RuleEditorPage";
import { StatsPage } from "./pages/StatsPage";
import { PremiumPage } from "./pages/PremiumPage";
import { AuditLogPage } from "./pages/AuditLogPage";
import { ConfigPage } from "./pages/ConfigPage";

interface AuthState {
  loading: boolean;
  me: Me | null;
}

export default function App() {
  const [auth, setAuth] = useState<AuthState>({ loading: true, me: null });

  useEffect(() => {
    api
      .me()
      .then((me) => setAuth({ loading: false, me }))
      .catch((err) => {
        if (err instanceof UnauthorizedError) {
          setAuth({ loading: false, me: null });
        } else {
          setAuth({ loading: false, me: null });
        }
      });
  }, []);

  if (auth.loading) {
    return (
      <div className="container" style={{ paddingTop: "4rem", textAlign: "center" }}>
        <p className="muted">Loading…</p>
      </div>
    );
  }

  return (
    <>
      <AppChrome me={auth.me} />
      <main>
        <div className="container">
          <Routes>
            <Route path="/login" element={<LoginPage me={auth.me} />} />

            <Route
              path="/me"
              element={<RequireAuth me={auth.me}><DashboardPage me={auth.me} /></RequireAuth>}
            />

            <Route
              path="/guilds/:guildId"
              element={<RequireAuth me={auth.me}><GuildPage /></RequireAuth>}
            />
            <Route
              path="/guilds/:guildId/rules"
              element={<RequireAuth me={auth.me}><RulesPage /></RequireAuth>}
            />
            <Route
              path="/guilds/:guildId/rules/:ruleId"
              element={<RequireAuth me={auth.me}><RuleEditorPage /></RequireAuth>}
            />
            <Route
              path="/guilds/:guildId/stats"
              element={<RequireAuth me={auth.me}><StatsPage /></RequireAuth>}
            />
            <Route
              path="/guilds/:guildId/premium"
              element={<RequireAuth me={auth.me}><PremiumPage /></RequireAuth>}
            />
            <Route
              path="/guilds/:guildId/audit-log"
              element={<RequireAuth me={auth.me}><AuditLogPage /></RequireAuth>}
            />
            <Route
              path="/guilds/:guildId/config"
              element={<RequireAuth me={auth.me}><ConfigPage /></RequireAuth>}
            />

            {/* Legacy alias */}
            <Route path="/settings" element={<Navigate to="/me" replace />} />
            <Route path="/dashboard" element={<Navigate to="/me" replace />} />

            <Route path="/" element={<Navigate to={auth.me ? "/me" : "/login"} replace />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </div>
      </main>
      <Footer />
    </>
  );
}

function AppChrome({ me }: { me: Me | null }) {
  const { pathname } = useLocation();
  if (pathname === "/login") return null;
  return <Header me={me} />;
}

function RequireAuth({ me, children }: { me: Me | null; children: React.ReactNode }) {
  const location = useLocation();
  if (!me) {
    const target = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/login?next=${target}`} replace />;
  }
  return <>{children}</>;
}
