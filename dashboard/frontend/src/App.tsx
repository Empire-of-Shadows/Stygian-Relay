import { useEffect, useState, type ReactNode } from "react";
import { Navigate, Route, Routes, useLocation, useParams, useSearchParams } from "react-router-dom";
import { Header } from "./components/Header";
import { Footer } from "./components/Footer";
import { api, UnauthorizedError } from "./api/client";
import type { Me } from "./api/types";
import { LoginPage } from "./pages/LoginPage";
import { DashboardPage } from "./pages/DashboardPage";
import { OverviewPage } from "./pages/OverviewPage";
import { SettingsPage } from "./pages/SettingsPage";
import { RulesPage } from "./pages/RulesPage";
import { RuleEditorPage } from "./pages/RuleEditorPage";
import { StatsPage } from "./pages/StatsPage";
import { PremiumPage } from "./pages/PremiumPage";
import { AuditLogPage } from "./pages/AuditLogPage";
import { ConfigPage } from "./pages/ConfigPage";
import { TermsPage } from "./pages/TermsPage";
import { PrivacyPolicyPage } from "./pages/PrivacyPolicyPage";
import { PrivacyPage } from "./pages/PrivacyPage";

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

            {/* The dashboard home: the server picker and where your messages go across
                every server at once. One server's own page is /me/guilds/:id/overview,
                and an old /me?guild= link redirects there. */}
            <Route
              path="/me"
              element={<RequireAuth me={auth.me}><MeOrRedirect me={auth.me} /></RequireAuth>}
            />

            {/* The per-guild landing: what this one server relays for you, plus the
                server's own report for somebody who can manage it. */}
            <Route
              path="/me/guilds/:guildId/overview"
              element={<RequireAuth me={auth.me}><OverviewPage /></RequireAuth>}
            />

            {/* The member's own control panel. Signed-in only - it needs no permission
                in any server, because it is about their account rather than a guild. */}
            <Route
              path="/me/privacy"
              element={<RequireAuth me={auth.me}><PrivacyPage /></RequireAuth>}
            />

            {/* Managing a server lives under /settings, which is the picker scene, with
                one branch per server below it. Every one of these pages is admin-only and
                says so from the API, not from the route. */}
            <Route
              path="/settings"
              element={<RequireAuth me={auth.me}><SettingsPage /></RequireAuth>}
            />
            <Route
              path="/settings/guilds/:guildId/settings"
              element={<RequireAuth me={auth.me}><ConfigPage /></RequireAuth>}
            />
            <Route
              path="/settings/guilds/:guildId/rules"
              element={<RequireAuth me={auth.me}><RulesPage /></RequireAuth>}
            />
            <Route
              path="/settings/guilds/:guildId/rules/:ruleId"
              element={<RequireAuth me={auth.me}><RuleEditorPage /></RequireAuth>}
            />
            <Route
              path="/settings/guilds/:guildId/stats"
              element={<RequireAuth me={auth.me}><StatsPage /></RequireAuth>}
            />
            <Route
              path="/settings/guilds/:guildId/premium"
              element={<RequireAuth me={auth.me}><PremiumPage /></RequireAuth>}
            />
            <Route
              path="/settings/guilds/:guildId/audit-log"
              element={<RequireAuth me={auth.me}><AuditLogPage /></RequireAuth>}
            />

            {/* Public legal pages */}
            <Route path="/terms" element={<TermsPage />} />
            <Route path="/privacy" element={<PrivacyPolicyPage />} />

            {/* Legacy aliases. The flat /guilds/:id tree is where every one of these
                pages used to live, so those URLs are in bookmarks and in Discord
                messages; each one lands on the same page at its new address, carrying
                any query string with it (the settings rail and the audit-log filters
                both live in one). */}
            <Route path="/dashboard" element={<Navigate to="/me" replace />} />
            <Route path="/guilds/:guildId" element={<LegacyGuildRedirect to="overview" />} />
            <Route path="/guilds/:guildId/config" element={<LegacyGuildRedirect to="settings" />} />
            <Route path="/guilds/:guildId/rules" element={<LegacyGuildRedirect to="rules" />} />
            <Route
              path="/guilds/:guildId/rules/:ruleId"
              element={<LegacyGuildRedirect to="rule" />}
            />
            <Route path="/guilds/:guildId/stats" element={<LegacyGuildRedirect to="stats" />} />
            <Route path="/guilds/:guildId/premium" element={<LegacyGuildRedirect to="premium" />} />
            <Route
              path="/guilds/:guildId/audit-log"
              element={<LegacyGuildRedirect to="audit-log" />}
            />

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
const SELF_WIDTH = [
  /^\/me$/,
  /^\/me\/privacy$/,
  /^\/me\/guilds\/[^/]+\/overview$/,
  /^\/settings$/,
  // Every management page under a server uses the engine's `.page` column, so the whole
  // branch is listed once rather than one pattern per page.
  /^\/settings\/guilds\/[^/]+\//,
];

function PageShell({ children }: { children: ReactNode }) {
  const { pathname } = useLocation();
  if (SELF_WIDTH.some((pattern) => pattern.test(pathname))) return <>{children}</>;
  return <div className="container">{children}</div>;
}

/**
 * What /me renders, and where an old shareable link goes.
 *
 * A single server's view used to be `/me?guild=<id>` on this same page, so those links
 * are out there in Discord messages and bookmarks. They now land on that server's
 * overview instead of on a picker that no longer reads the parameter. Without the search
 * parameter this is just the dashboard home.
 */
function MeOrRedirect({ me }: { me: Me | null }) {
  const [searchParams] = useSearchParams();
  const guildId = searchParams.get("guild");
  if (guildId) return <Navigate to={`/me/guilds/${guildId}/overview`} replace />;
  return <DashboardPage me={me} />;
}

/**
 * The flat `/guilds/:id/...` tree, sent to wherever each page lives now.
 *
 * The query string is carried over rather than dropped: the settings rail keeps the open
 * area in `?s=`, and the audit log keeps its area and person filters the same way, so a
 * saved link to one of those is a link to a specific view and not just to a page.
 */
function LegacyGuildRedirect({
  to,
}: {
  to: "overview" | "settings" | "rules" | "rule" | "stats" | "premium" | "audit-log";
}) {
  const { guildId, ruleId } = useParams<{ guildId: string; ruleId: string }>();
  const { search } = useLocation();
  if (!guildId) return <Navigate to="/me" replace />;
  const path =
    to === "overview"
      ? `/me/guilds/${guildId}/overview`
      : to === "rule"
        ? `/settings/guilds/${guildId}/rules/${ruleId}`
        : `/settings/guilds/${guildId}/${to}`;
  return <Navigate to={path + search} replace />;
}

function RequireAuth({ me, children }: { me: Me | null; children: React.ReactNode }) {
  const location = useLocation();
  if (!me) {
    const target = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/login?next=${target}`} replace />;
  }
  return <>{children}</>;
}
