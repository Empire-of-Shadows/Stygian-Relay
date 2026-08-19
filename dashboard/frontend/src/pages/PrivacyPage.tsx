import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Guild, PrivacyFeatures, ScopeGuild } from "../api/types";
import { formatError } from "../_engine/api/formatError";
import ServerPicker from "../_engine/components/overview/ServerPicker";
import { Rule, Tile } from "../_engine/components/overview/Tile";
import { ToggleField } from "../_engine/components/settings/fields";

/*
 * Privacy and data - the member's own control panel.
 *
 * Relay is the one bot in the fleet that takes something a member wrote and republishes
 * it into a channel they may not be in, possibly in a server they are not in. So the two
 * switches here are the most consequential in the ecosystem, and the copy has to be
 * blunt about what each of them costs.
 *
 * Three scopes live on this page and they are NOT the same, which is the thing the
 * wording must keep straight:
 *
 *   - The two switches are ACCOUNT-WIDE and FORWARD-ONLY. They apply in every server
 *     relay runs in and never remove anything already stored or already posted.
 *   - Export and delete are scoped by the picker: one server or all of them.
 *   - Copies already posted into a Discord channel are outside all of it. Relay does not
 *     own those messages and cannot delete them. That is said on the page, not buried.
 */

type Feature = "relay_messages" | "show_name";

const FEATURES: { key: Feature; label: string; description: string }[] = [
  {
    key: "relay_messages",
    label: "Do not relay my messages",
    description:
      "Nothing you post in a watched channel is copied anywhere, by any rule, in any server. Everyone else's messages are still copied as normal, so a conversation forwarded out of a channel you post in will read with your side of it missing.",
  },
  {
    key: "show_name",
    label: "Do not show my name on forwarded copies",
    description:
      "Your messages are still copied, but the copy does not say who wrote it. The link back to your original post is kept, so anyone who follows it still lands on your message in the channel you posted it in - this hides your name on the copy, it does not make the message anonymous.",
  },
];

export function PrivacyPage() {
  // Scope for export and delete only. The switches above are account-wide.
  const [guilds, setGuilds] = useState<ScopeGuild[]>([]);
  const [guildsFailed, setGuildsFailed] = useState(false);
  const [scopeGuildId, setScopeGuildId] = useState<string | null>(null);

  // `saved` is the server's copy, `draft` the edits in front of you.
  const [saved, setSaved] = useState<PrivacyFeatures | null>(null);
  const [draft, setDraft] = useState<PrivacyFeatures | null>(null);
  const [loadingPrivacy, setLoadingPrivacy] = useState(true);
  const [privacyLoadError, setPrivacyLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState<
    { kind: "success" | "danger"; text: string } | null
  >(null);

  const [confirmOpen, setConfirmOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteResult, setDeleteResult] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  useEffect(() => {
    api
      .userDataGuilds()
      .then((list) => {
        setGuilds(list);
        setGuildsFailed(false);
      })
      .catch(() => {
        setGuilds([]);
        setGuildsFailed(true);
      });

    api
      .getUserPrivacy()
      .then((r) => {
        setSaved(r.features);
        setDraft(r.features);
      })
      .catch((e) => {
        setPrivacyLoadError(
          formatError(e, "Your privacy choices could not be loaded."),
        );
      })
      .finally(() => setLoadingPrivacy(false));
  }, []);

  const scopeGuild = useMemo(
    () => guilds.find((g) => g.id === scopeGuildId) ?? null,
    [guilds, scopeGuildId],
  );
  const scopeLabel = scopeGuild
    ? (scopeGuild.name ?? `Server ${scopeGuild.id}`)
    : "all servers";

  // ServerPicker speaks the shared Guild shape. Every server in this list is one relay
  // is already in and already holds something of yours for, so the setup flags are fixed.
  const pickerGuilds: Guild[] = useMemo(
    () =>
      guilds.map((g) => ({
        id: g.id,
        name: g.name ?? `Server ${g.id}`,
        icon: g.icon,
        bot_in_guild: true,
        has_config: true,
        setup_required: false,
        panel_role: "none" as const,
      })),
    [guilds],
  );

  const scopeMeta = scopeGuild
    ? "Export and delete cover this server only"
    : guilds.length === 0
      ? "Relay holds no server data for you yet"
      : guilds.length === 1
        ? "Export and delete cover your one server"
        : `Export and delete cover all ${guilds.length} of your servers`;

  const dirty =
    saved !== null && draft !== null && JSON.stringify(saved) !== JSON.stringify(draft);

  const setFeature = (key: Feature | "all", value: boolean) => {
    setSaveMessage(null);
    setDraft((prev) => (prev ? { ...prev, [key]: value } : prev));
  };

  async function savePrivacy() {
    if (!draft) return;
    setSaving(true);
    setSaveMessage(null);
    try {
      const r = await api.saveUserPrivacy(draft);
      setSaved(r.features);
      setDraft(r.features);
      setSaveMessage({
        kind: "success",
        text: "Saved. Your choices apply everywhere within about a minute.",
      });
    } catch (e) {
      setSaveMessage({ kind: "danger", text: formatError(e, "Your choices were not saved.") });
    } finally {
      setSaving(false);
    }
  }

  async function runDelete() {
    setDeleteResult(null);
    setDeleteError(null);
    setDeleting(true);
    try {
      const r = await api.deleteUserData(scopeGuildId);
      const total = Object.values(r.deleted).reduce((a, n) => a + n, 0);
      const where = scopeGuild ? `in ${scopeLabel}` : "across all servers";
      setDeleteResult(
        total === 0
          ? `No rule named you ${where}, so nothing needed changing.`
          : `Removed your name from ${total} rule${total === 1 ? "" : "s"} ${where}. What those rules relay may have changed.`,
      );
    } catch (e) {
      setDeleteError(formatError(e, "Your data could not be deleted."));
    } finally {
      setDeleting(false);
      setConfirmOpen(false);
    }
  }

  const allPaused = draft?.all ?? false;

  return (
    <div className="page">
      <section className="dash-hero">
        <div className="dash-hero__orb" />
        <div className="dash-hero__copy">
          <span className="dash-hero__eyebrow">Account control</span>
          <h1 className="dash-hero__title">Privacy &amp; data</h1>
          <p className="dash-hero__sub">
            Choose whether your messages are relayed and whether your name goes with them,
            download what relay holds for you, or have it removed.
          </p>
        </div>
      </section>

      <h2 className="section-title" style={{ margin: "24px 0 12px" }}>
        Your messages
      </h2>

      <div className="ov-grid">
        <Tile span={12} title="What relay may do with what you post" live>
          <p className="ov-body">
            Stygian Relay copies messages from one channel into another, and sometimes into
            a different server. These switches are your say over that. They apply to your
            account everywhere - in every server that uses relay, not just one - and take
            effect within about a minute.
          </p>
          <p className="ov-muted">
            They only change what happens from now on. Copies already posted into a Discord
            channel stay there: relay does not own those messages and cannot delete them.
          </p>

          <Rule />

          {loadingPrivacy ? (
            <p className="ov-muted">Loading your choices...</p>
          ) : privacyLoadError ? (
            <p className="alert danger" role="alert">
              {privacyLoadError}
            </p>
          ) : draft ? (
            <>
              <ToggleField
                label="Leave me out of relaying entirely"
                value={draft.all}
                disabled={saving}
                onChange={(v) => setFeature("all", v)}
                description="Both switches below at once. Nothing you post is copied anywhere, and no forwarded copy carries your name."
              />

              <Rule />

              {allPaused && (
                <p className="ov-muted">
                  Both switches below are covered by the one above. Turn it off to choose
                  between them.
                </p>
              )}

              {FEATURES.map((feature) => (
                <ToggleField
                  key={feature.key}
                  label={feature.label}
                  value={allPaused || draft[feature.key]}
                  disabled={allPaused || saving}
                  onChange={(v) => setFeature(feature.key, v)}
                  description={feature.description}
                />
              ))}

              <p className="ov-muted">
                A server admin can still stop relaying your messages from their side with a
                rule filter. They are never shown who has opted out, and are not shown a
                count of it either.
              </p>

              <div className="admin-actions" style={{ alignItems: "center", flexWrap: "wrap" }}>
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={!dirty || saving}
                  onClick={savePrivacy}
                >
                  {saving ? "Saving..." : "Save choices"}
                </button>
                <span className="ov-muted">
                  {dirty ? "Unsaved changes" : "Everything here is saved"}
                </span>
              </div>

              {saveMessage && (
                <p
                  className={saveMessage.kind === "danger" ? "alert danger" : "ov-muted"}
                  role={saveMessage.kind === "danger" ? "alert" : "status"}
                >
                  {saveMessage.text}
                </p>
              )}
            </>
          ) : null}
        </Tile>
      </div>

      <h2 className="section-title" style={{ margin: "28px 0 0" }}>
        Export and delete
      </h2>

      <div className="ov-command">
        <ServerPicker
          guilds={pickerGuilds}
          selectedGuildId={scopeGuildId}
          onSelect={(id) => {
            setScopeGuildId(id);
            setDeleteResult(null);
            setDeleteError(null);
          }}
          meta={scopeMeta}
        />
        <span className="ov-muted">
          One choice for both sections below. It does not affect the switches above, which
          always apply to every server.
        </span>
      </div>

      {guildsFailed && (
        <p className="ov-muted">
          Your server list could not be loaded, so only the all-servers option is available
          here. Reload the page to try again.
        </p>
      )}

      <div className="ov-grid">
        <Tile span={6} title="Export your data">
          <p className="ov-body">
            Download a JSON file with everything relay holds for you in {scopeLabel}:
          </p>
          <ul className="ov-body" style={{ margin: 0, paddingLeft: "1.1rem" }}>
            <li>Your privacy choices above</li>
            <li>Any forwarding rule whose filters name you, and which list you are on</li>
            <li>Admin audit entries, if you have changed a relay setting yourself</li>
            <li>Your premium purchase records, if you have any</li>
          </ul>
          <Rule />
          <p className="ov-muted">
            The file is short, and that is the honest answer rather than a fault: relay
            forwards messages, it does not keep them. The record it writes for each
            forwarded message names the rule and the channels but never the author, so
            there is nothing of yours in it to hand back.
          </p>
          <div className="admin-actions">
            <a href={api.exportUserDataUrl(scopeGuildId)} className="btn btn-secondary" download>
              Download my data
            </a>
          </div>
        </Tile>

        <Tile span={6} title="Delete your data">
          <p className="ov-body">
            Takes your name out of every forwarding rule in {scopeLabel}. This cannot be
            undone.
          </p>
          <p className="ov-body">
            <strong>It changes what those servers relay.</strong> If an admin had put you on
            a rule's blocked list, that entry goes too and your messages start being copied
            again. If a rule only copied a named few and you were one of them, you stop
            being copied. Use the switches above, not this, if what you want is to stop
            being relayed.
          </p>

          <Rule />

          <span className="ov-card__title">What stays</span>
          <ul className="ov-body" style={{ margin: 0, paddingLeft: "1.1rem" }}>
            <li>
              Copies already posted into a Discord channel. Relay does not own those
              messages and cannot delete them - ask that server's staff.
            </li>
            <li>
              Audit entries for changes you made as an admin, so a server keeps a complete
              record of who changed what.
            </li>
            <li>Your privacy choices above, so an erasure never switches relaying back on.</li>
            <li>Premium purchase records, which are a receipt rather than your data.</li>
          </ul>

          <div className="admin-actions">
            <button
              type="button"
              className="btn btn-danger"
              disabled={deleting}
              onClick={() => {
                setDeleteResult(null);
                setDeleteError(null);
                setConfirmOpen(true);
              }}
            >
              {deleting ? "Deleting..." : "Delete my data..."}
            </button>
          </div>

          {deleteResult && (
            <p style={{ color: "var(--success)", margin: 0 }} role="status">
              {deleteResult}
            </p>
          )}
          {deleteError && (
            <p className="alert danger" role="alert">
              {deleteError}
            </p>
          )}
        </Tile>
      </div>

      <p className="ov-muted" style={{ margin: "20px 0 28px" }}>
        The full <Link to="/privacy">privacy policy</Link> explains what relay stores and
        why. <Link to="/me">Your servers</Link> shows which routes carry your messages
        right now.
      </p>

      {confirmOpen && (
        <DeleteConfirm
          scopeLabel={scopeLabel}
          deleting={deleting}
          onConfirm={runDelete}
          onCancel={() => setConfirmOpen(false)}
        />
      )}
    </div>
  );
}

/**
 * Type-DELETE confirmation for the erase button.
 *
 * Written here rather than reached for from ConfirmDialog because that shared dialog has
 * no typed-confirmation step, and this action changes what other people's servers relay -
 * a one-click confirm is not enough for it. Everything ConfirmDialog does is kept: the
 * same .confirm-* markup, focus moved into the dialog on open and handed back on close,
 * and Escape or a backdrop click cancelling. Tab is additionally kept inside the dialog,
 * which matters more here than on a one-button confirm.
 *
 * Mounted only while open, so each opening starts with an empty box.
 */
function DeleteConfirm({
  scopeLabel,
  deleting,
  onConfirm,
  onCancel,
}: {
  scopeLabel: string;
  deleting: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const [text, setText] = useState("");
  const dialogRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const previousActive = useRef<HTMLElement | null>(null);
  // Held in a ref so the key handler is installed once on open. The parent passes a fresh
  // closure every render; depending on it would re-run the effect mid-typing and steal
  // focus back to the input.
  const cancelRef = useRef(onCancel);
  cancelRef.current = onCancel;

  useEffect(() => {
    previousActive.current = document.activeElement as HTMLElement | null;
    inputRef.current?.focus();

    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        cancelRef.current();
        return;
      }
      if (e.key !== "Tab") return;
      const dialog = dialogRef.current;
      if (!dialog) return;
      // Rebuilt on every Tab because the confirm button is disabled until the word is
      // typed, and a disabled control must not be a stop in the cycle.
      const stops = Array.from(
        dialog.querySelectorAll<HTMLElement>("input, button"),
      ).filter((node) => !node.hasAttribute("disabled"));
      if (stops.length === 0) return;
      const first = stops[0];
      const last = stops[stops.length - 1];
      const active = document.activeElement;
      if (!dialog.contains(active)) {
        e.preventDefault();
        first.focus();
      } else if (e.shiftKey && active === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      previousActive.current?.focus?.();
    };
    // Runs once for the lifetime of one opening; the cancel closure is a ref.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const armed = text === "DELETE" && !deleting;

  return (
    <div
      className="confirm-backdrop"
      role="dialog"
      aria-modal="true"
      aria-labelledby="privacy-delete-title"
      aria-describedby="privacy-delete-message"
      onClick={onCancel}
    >
      <div className="confirm-dialog" ref={dialogRef} onClick={(e) => e.stopPropagation()}>
        <h2 id="privacy-delete-title" className="confirm-title">
          Delete your data in {scopeLabel}?
        </h2>
        <p id="privacy-delete-message" className="confirm-message">
          This takes your name out of every forwarding rule in {scopeLabel}, which changes
          what those servers relay - a rule that was blocking you stops blocking you, and a
          rule that only copied a named few stops copying you. Messages already forwarded
          into a Discord channel stay there. Your privacy choices, your audit entries and
          your premium records stay. This cannot be undone.
        </p>

        <div className="eos-field">
          <label htmlFor="privacy-delete-confirm">Type DELETE to confirm</label>
          <input
            id="privacy-delete-confirm"
            ref={inputRef}
            type="text"
            value={text}
            disabled={deleting}
            autoComplete="off"
            placeholder="DELETE"
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && armed) onConfirm();
            }}
          />
        </div>

        <div className="confirm-actions">
          <button type="button" className="btn btn-secondary" disabled={deleting} onClick={onCancel}>
            Cancel
          </button>
          <button type="button" className="btn btn-danger" disabled={!armed} onClick={onConfirm}>
            {deleting ? "Deleting..." : "Delete everything"}
          </button>
        </div>
      </div>
    </div>
  );
}
