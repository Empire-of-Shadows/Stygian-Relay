import { useEffect, useState, type ReactNode } from "react";
import { Navigate, Route, Routes, useLocation, useParams } from "react-router-dom";
import { Header } from "./components/Header";
import { Footer } from "./components/Footer";
import { api, UnauthorizedError } from "./api/client";
import type { Me } from "./api/types";
import { LoginPage } from "./pages/LoginPage";
import { DashboardPage } from "./pages/DashboardPage";
import { SettingsPage } from "./pages/SettingsPage";
import { RulesPage } from "./pages/RulesPage";
import { RuleEditorPage } from "./pages/RuleEditorPage";
import { StatsPage } from "./pages/StatsPage";
import { PremiumPage } from "./pages/PremiumPage";
import { AuditLogPage } from "./pages/AuditLogPage";
import { ConfigPage } from "./pages/ConfigPage";
import { TermsPage } from "./pages/TermsPage";
import { PrivacyPolicyPage } from "./pages/PrivacyPolicyPage";

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
        <PageShell>
          <Routes>
            <Route path="/login" element={<LoginPage me={auth.me} />} />

            <Route
              path="/me"
              element={<RequireAuth me={auth.me}><DashboardPage me={auth.me} /></RequireAuth>}
            />

            <Route
              path="/settings"
              element={<RequireAuth me={auth.me}><SettingsPage /></RequireAuth>}
            />

            {/* The old per-guild hub was a card grid of links to the five pages
                below. The server overview now carries every one of those links
                and says whether the relay is actually working, so this lands
                there instead of repeating itself. */}
            <Route
              path="/guilds/:guildId"
              element={<RequireAuth me={auth.me}><GuildRedirect /></RequireAuth>}
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

            {/* Public legal pages */}
            <Route path="/terms" element={<TermsPage />} />
            <Route path="/privacy" element={<PrivacyPolicyPage />} />

            {/* Legacy alias */}
            <Route path="/dashboard" element={<Navigate to="/me" replace />} />

            <Route path="/" element={<Navigate to={auth.me ? "/me" : "/login"} replace />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </PageShell>
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

/**
 * Routes that own their own width.
 *
 * The redesigned pages use the engine's `.page` column (capped and gutted by
 * the shared stylesheet) and the servers scene runs edge to edge, so wrapping
 * either of them in `.container` would double the gutter or box in the scene.
 * Everything else still gets the container it has always had.
 */
const SELF_WIDTH = [/^\/me$/, /^\/settings$/, /^\/guilds\/[^/]+\/config$/];

function PageShell({ children }: { children: ReactNode }) {
  const { pathname } = useLocation();
  if (SELF_WIDTH.some((pattern) => pattern.test(pathname))) return <>{children}</>;
  return <div className="container">{children}</div>;
}

/** The per-guild hub is now the server overview, keyed by ?guild=. */
function GuildRedirect() {
  const { guildId } = useParams<{ guildId: string }>();
  return <Navigate to={guildId ? `/me?guild=${guildId}` : "/me"} replace />;
}

function RequireAuth({ me, children }: { me: Me | null; children: React.ReactNode }) {
  const location = useLocation();
  if (!me) {
    const target = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/login?next=${target}`} replace />;
  }
  return <>{children}</>;
}
