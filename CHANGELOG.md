# Changelog

## [Unreleased] - 2026-08-24 (login page layout)

### Fixed
- **Logging in on the relay dashboard now brings you back to the relay dashboard.** It used
  to drop you on TheCodex's dashboard after the Discord sign-in, because the sign-in was
  configured to return there. (Your login still counted everywhere - one login covers every
  Empire of Shadows dashboard - you just landed on the wrong site.)
- **The "What Stygian Relay does" section on the dashboard login page is centered again.**
  It sat pushed to the left while everything above it was centered.

## [Unreleased] - 2026-08-24 (honest answers in the rules pages and change history)

### Fixed
- **Turning a rule back on when your server is at its rule limit now says so.** It used to
  answer "Rule not found" for a rule that was right there on the page; now it tells you the
  active-rule limit is reached, the same way creating one too many always has.
- **Rule changes made from Discord's admin panel now show up under the "Forwarding rules"
  filter in Change history.** They were being filed under a different label, so that filter
  quietly hid every change made from inside Discord. Older entries keep their old label.
- **The Change history filter no longer offers "Server" and "System"** - no change was ever
  recorded under either, so picking them always showed an empty page.
- **Error messages for invalid form input are readable now.** Some validation errors used to
  render as raw data instead of a sentence naming the field and the problem.

## [Unreleased] - 2026-08-24 (picking a log channel checks what the bot needs)

### Changed
- **Choosing a Log Channel in the admin panel now checks every permission the bot really
  needs there.** The bot posts notices to that channel on its own - when a forwarding rule
  is switched off after repeated failures, and when premium changes - and those notices are
  embeds. Before, picking a channel where the bot could not post or embed looked fine and
  the notices just silently never arrived; now the panel names the exact missing permission
  the moment you pick the channel.

## [Unreleased] - 2026-08-22 (admin panel pickers)

### Changed
- **A refused pick in the admin panel no longer stays selected.** When a channel, role or
  option is turned down (wrong permissions, a role the bot cannot manage, an invalid choice),
  the picker now resets to what is actually saved, so you can pick again straight away instead
  of having to choose something else first.
- **Creating a role from the admin panel now reminds you where it landed.** Discord puts a new
  role at the bottom of the role list; the confirmation says so and points you to Server
  Settings -> Roles if it needs to sit higher.

## [Unreleased] - 2026-08-19 (prefix and suffix now work)

### Fixed
- **Pressing Escape no longer closes a confirmation box while the action is already running.**
  When you confirm something destructive, the Cancel button greys out and clicking outside the
  box does nothing, because by then there is nothing left to call off. Escape ignored that and
  closed the box anyway, so the action carried on out of sight and it looked like you had
  stopped it. Escape now behaves like the other two, and still closes the box normally before
  you confirm.

### Added
- **Your rule's prefix and suffix are now actually added to forwarded copies.** Both settings
  have been on the rule editor for a while but nothing was done with them. Now the prefix is
  posted on its own line above the copy and the suffix on its own line below it, outside the
  quoted block, so they read as your words rather than as something the original author wrote.
  Leave either one empty to skip it.
- **Worth checking before this goes live:** if you already typed a prefix or a suffix into a rule
  at any point, it was saved even though nothing showed it, and it will start appearing on every
  message that rule copies. Open the rule and clear the box if you do not want it.

### Note
- The **Style** setting is still saved without being used - every copy is posted in the quoted
  style regardless of what you pick. The rule editor and the Discord setup screen both say so.

### Changed
- **The "Members who opted out" figure is gone from the rules page.** It counted everyone who
  had asked Stygian Relay to skip their messages across every server the bot runs in, not just
  yours, so it could never tell you anything about your own server. It said as much, but a number
  you cannot act on is worse than no number. Nothing about opting out itself has changed - members
  can still ask relay to skip their messages, and those messages are still skipped by every rule.
- **Members are told this plainly.** The privacy page used to say a server admin could see how
  many members of their server had opted out. That was never what admins actually saw, and now
  admins see no count at all, so the page says so.

## [Unreleased] - 2026-08-17 (rule summary honesty)

### Fixed
- **The rule summary no longer claims a prefix, suffix or style is being applied when it is not.**
  When you set up a forwarding rule, the summary listed things like "Prefix: hello" and
  "Style: Component v2" as though your forwarded copies were being changed that way. They were
  not - relay saves those three settings but always posts copies in its normal quoted style. The
  summary now says they are saved but not applied yet, so what you see matches what actually
  happens. The dashboard's rule editor already said this; the Discord setup screen did not.

## [Unreleased] - 2026-08-17 (where your messages go)

### Fixed
- **A route that blocks you no longer says it carries your messages.** Your privacy page works
  out which routes copy your messages by checking your roles. When that check could not be
  completed - a brief Discord problem, usually - the page treated it as "you have no roles",
  which meant a rule set up to exclude a role stopped recognising you and the page told you your
  messages were being copied when they were not. It now says "could not check" for those routes
  instead of guessing, tells you why, and the count at the top no longer includes them as
  answered either way. Routes that filter by name rather than by role were never affected and
  still give you a straight answer.

## [Unreleased] - 2026-08-17 (dashboard charts and sign-in)

### Fixed
- **Dates under the bar charts no longer overlap.** On a narrow screen, or when a chart covered a
  lot of days, the labels along the bottom could print on top of one another and become
  unreadable. The chart now shows as many labels as genuinely fit the space, and always keeps the
  first and the last so you can see the range at a glance.
- **A brief Discord outage no longer keeps you locked out of the dashboard for a full minute.**
  When Discord could not be reached to confirm your roles, the dashboard remembered that failure
  for 60 seconds, so you stayed shut out even after Discord had come back. It now tries again
  within about 10 seconds.
- **The same applies to a server admin.** The check that confirms you manage this server had the
  same problem and it locked out harder: one failed reply shut every admin of that server out for
  a full minute. It now retries after about ten seconds.
- **The dashboard no longer creeps up in memory the longer it runs.** Two internal lookup caches
  never cleared out entries that had gone stale.

## [Unreleased] - 2026-08-17

### Fixed
- **Buttons that are switched off no longer light up when you point at them.** A greyed-out
  button on the dashboard still brightened as though you could press it, which made it look
  available when it was not. It now stays quiet until it is actually usable.

## [Unreleased] - 2026-08-15

### Changed
- **The bot now asks Discord for far less information about your server.** It used to receive a
  broad default feed of events - reactions, typing, voice activity, invites, scheduled events and
  more - none of which it ever used. It now receives only what forwarding actually needs: your
  server's channels and roles, and the messages in them. It also no longer asks for the server
  member list, which is a permission Discord treats as sensitive.

### Fixed
- **The "Join the server" link on forwarded messages worked again.** The invite in the small
  footer line added to messages forwarded from free servers had expired, so anyone who clicked it
  got an error. It now points at the permanent invite.
- **Help now shows the admin section to everyone who can actually use it.** A member given the
  Manager Role could open and use the entire `/admin` panel, but `/help` still hid the admin page
  from them unless they also had Manage Server.
- **The admin panel no longer fails to open a menu when a summary line gets long.** If a
  dropdown entry's summary grew past what Discord allows - for example a setting listing
  many roles or channels - the whole screen failed with an error instead of showing. Long summaries now switch to a
  compact form such as "12 roles assigned" - the full list still appears in the text right
  above - and the menu always opens.

## [Unreleased] - 2026-08-13

### Fixed
- On phones, the server panel on the settings hub now shows its close button and its server
  icon in full instead of cutting them off at the panel's rounded edge, and the close button
  stays put while you scroll the panel.

### Changed
- **Changes made on the dashboard now show up in the change history.** Editing a server's
  settings, or creating, editing, pausing or deleting a rule from the website, recorded
  nothing at all - only the same actions done from the `/admin` panel in Discord were written
  down. A server run entirely from the website had a change history that looked months out of
  date. Both now record, with the name of the person who made the change, not just their ID.
- **The change history is readable.** It used to be a table with a column of raw ID numbers and
  a column of truncated code. Every entry is now a sentence saying who did what, and you can
  filter by person as well as by area, with a panel summarising what has been changing.
- **The privacy policy says what forwarding actually does.** It now states that a forwarded copy
  republishes your display name and what you wrote into another channel, which can be in a
  different server; that the relay keeps a reference to your original message - its ID and its
  channel, not its text - for 90 days; and exactly what survives if the bot is removed from a
  server, with the real retention periods, replacing a vague line about things possibly being
  cleaned up.
- **The terms of service are published** rather than draft, and now say what a member can do
  about forwarded content rather than only what they are responsible for.
- **The sign-in page explains what the bot does** before you sign in, with the real free-tier
  limits, and links to the two ecosystem dashboards that were missing from the list.
- **The dashboard now opens on a page that tells you whether the relay is actually working.**
  Signing in used to give you a grid of server tiles leading to another grid of link tiles, and
  neither of them said anything about what the bot was doing. Picking a server now lands you
  straight on that server's page: a row of cards saying which parts are on, which need setting up
  and which are off; how many messages have been forwarded over the last month, drawn as a chart;
  how much of today's allowance is left and when the last message went through; your routes with
  the channels they connect and how much each one carried; what was blocked and why; how the
  server is set up; and what your plan allows. Switching servers is now a picker at the top of the
  page instead of going back to a list.
- **Settings have been rebuilt as one page with a proper menu.** The old settings page was four
  boxes asking you to paste in ID numbers. It is now a list of areas down the side - Forwarding,
  Cross-server, Activity log, Who can manage - with one area open at a time, a plain-English
  explanation of what it does, and a panel on the right showing what that area is doing right now.
  The log channel and the manager role are chosen from a dropdown of your server's real channels
  and roles instead of being typed in as ID numbers, so a mistyped digit can no longer quietly
  point the bot at nothing. Every setting that was there before is still there and still does the
  same thing, and anything you had already set is kept.
- **The Settings link in the top bar now goes somewhere.** It used to bounce you back to the
  server list. It now opens a view of every server you manage as a connected web, where picking
  one brings up its overview, rules, settings and analytics.

### Added
- **You can now tell Stygian Relay to leave your messages alone.** There is a new Privacy page
  on the dashboard, open to anyone who signs in - you do not need to run a server or hold any
  permission to use it. Two switches: one stops your messages being copied anywhere at all, and
  one keeps your name off the copies while still letting them through. Both apply in every
  server the bot is in, not just one, and take effect within about a minute. A member's choice
  wins over a server's settings, so if a rule is set to show the author and you have asked us
  not to, your name is left off. Copies that were already posted stay where they are - those
  are ordinary Discord messages in someone else's channel now, and the bot cannot delete them,
  which the page says plainly rather than pretending otherwise.
- **You can see where your own messages go.** Signing in now shows you, for each of your
  servers, which channels are being copied into which - including when a copy leaves for a
  different server, and which server that is - and whether each of those routes actually
  carries your messages or skips you. This used to be invisible unless you ran the server.
  Members with no permissions used to get a completely blank dashboard; they now get this.
- **You can download or delete what the relay holds about you.** The same Privacy page has an
  export button and a delete button, either for one server or all of them. The download is
  small, and the page explains why instead of leaving you wondering: the relay forwards
  messages, it does not keep them. Deleting takes your name out of every forwarding rule, and
  the page warns you before you confirm that this changes what those servers relay - a rule
  that was blocking you stops blocking you.
- **Server admins can see how many people have opted out.** The rules page shows a count, and
  only a count - never who. It is there so a forwarded conversation with gaps in it has an
  explanation other than "the bot is broken".
- **The rules page shows what each rule is actually doing.** Instead of a table of ID numbers,
  each rule is now a card showing the two channels it connects, whether it leaves the server,
  how many messages it carried in the last month, when it was created and when it was last
  edited, with a dot for whether it is running. Deleting a rule now asks you properly, in a
  dialog that explains what happens, rather than the browser's bare pop-up.
- **The rule editor now covers everything a rule can do.** Which kinds of message get copied,
  words a message must or must not contain, how long a message may be, whether matching cares
  about capital letters or whole words, whether the copy shows the author, and whether
  attachments and embeds come with it. All of this could previously only be changed from the
  `/admin` panel in Discord. Channels and roles are chosen from your server's real lists, and a
  panel on the right says in plain words what the rule you are editing will do.
- **The analytics page gained four things:** which channels the messages land in (not just
  which they come from), which day of the week is busiest, how many copies leave your server
  versus stay in it, and a sentence explaining why the forwarded total can be bigger than the
  number of messages people actually posted.
- **The plan page now tells you whether you need to upgrade.** It shows your rules and today's
  messages against your actual limits, a free-versus-premium comparison using the real numbers
  the bot enforces, and how many messages the daily cap has actually cost you in the last
  month.
- **Error notices can now be switched on and off from the dashboard.** This is the short message
  the bot posts in a channel when it has to stop forwarding because the daily limit was reached.
  It was already available in the `/admin` panel in Discord; it is now on the dashboard's
  Forwarding page too, so both places offer the same switches.

### Fixed
- **The dashboard no longer struggles on a phone.** Every page was checked at phone width and now
  stacks into a single readable column with nothing running off the side of the screen. On a
  narrow screen the server web's detail panel slides up from the bottom instead of being squeezed
  into the side.

## [Unreleased] - 2026-08-07

### Changed
- **The bot no longer asks for the Manage Webhooks permission.** The invite link and the setup
  guide used to request Manage Webhooks for a planned option to forward messages under a custom
  name and avatar. That option was never actually built - forwarded messages have always been
  posted by the bot itself in the quoted style you see today - so the permission did nothing
  except make the invite ask for more than the bot needs. New invites now request only the
  permissions forwarding really uses. Servers that already invited the bot do not need to do
  anything, though you can safely revoke Manage Webhooks from the bot's role if it has it.

### Added
- **There is now an About page explaining the whole project.** The dashboard's login page and
  the footer on every page link to a new About page for Empire of Shadows: what each of the six
  bots does, how they fit together, and why the project is built as separate bots instead of one
  big one. Handy if you have just found one of the bots and want to know what the rest of it is.

## [Unreleased] - 2026-08-06

### Changed
- **The Manager Role is now described for what it actually does.** Nothing about who can get in
  has changed: the `/admin` panel and the web dashboard are open to anyone with Manage Server or
  Administrator, plus anyone holding the Manager Role you pick - and the Manager Role has always
  given that person the whole panel, exactly the same as an admin. The setup guide used to call it
  access "without full admin", which read as a limited, moderator-style tier that never existed.
  The setup guide and the Manager Role description now say plainly that it hands out full panel
  access without granting Manage Server, so you know what you are giving away before you set it.
  There is no moderator tier on this bot, and the leftover moderator wiring behind the scenes has
  been cleared out.

## [Unreleased] - 2026-08-05

### Added
- **Create roles and channels straight from the picker.** Every role and channel picker in the
  admin panel now carries a Create button: type a name and the new role or channel is created and
  selected in one step, without leaving the panel. The button first checks that the bot itself is
  allowed to create it and tells you which permission is missing instead of failing afterwards.
  Text channel names follow Discord's rules (lowercase letters, digits and dashes), and a rejected
  name comes back with a Try Again button that keeps what you typed.
- **Pick a category when creating a channel.** The Create Channel button in the admin panel now
  lets you choose which category the new channel goes under - or leave the picker empty to create
  it at the top of the channel list. If something goes wrong, Try Again keeps both the name you
  typed and the category you picked.

## [Unreleased] - 2026-08-02

### Added
- **A `/help` command.** Until now there was no way to ask the bot what it does. `/help` opens a
  private panel only you can see, with a dropdown to move between pages: an overview of what
  message forwarding is and what you will notice as a member, a page explaining how forwarding
  rules decide which messages get copied (message types, keyword and author filters, per-server
  limits, forwarding into another server, and what happens when a rule breaks), and - for anyone
  who can manage the server - a page covering the `/admin` panel, `/premium status`, first-time
  setup, and the web dashboard. The admin page is hidden from members who cannot use it. There is
  a button straight to the dashboard and a Close button.

## [Unreleased] - 2026-08-01

### Changed
- **The login screen now tells you what you are agreeing to.** It previously said nothing about
  privacy at all. Because one Empire of Shadows login signs you in to every bot dashboard, signing
  in now points you to a single combined Empire of Shadows privacy policy covering every bot,
  dashboard and tool, with Stygian Relay's own privacy page linked alongside it for the detail
  specific to this bot.

### Fixed
- **The privacy page now describes the forwarding records accurately.** It said the bot kept only
  aggregate counts of how many messages had been forwarded. It actually keeps one record per
  forwarded message - which rule ran, the channels involved, the ID of the original message,
  whether it worked and when. Those records still contain no message text and do not name the
  author, and forwarded messages themselves are never stored, but the page now says what is really
  kept rather than understating it. It also now gives the real retention periods: delivery records
  are deleted automatically after 90 days and the settings audit log after 365 days.

## [Unreleased] - 2026-07-26

### Fixed
- The `/admin` panel's setup progress was counting things you cannot actually configure. Buttons
  that only run an action - such as **Add Rule** under Forwarding Rules - were being added to each
  category's "X of Y configured" total, so a category could never read as finished no matter how
  much you set up. Only real settings count now, and a category that holds nothing but action
  screens just shows its name instead of a meaningless total.
- A list you had not put anything in yet was being counted as configured. An empty list now
  correctly reads as still needing setup.

## [Unreleased] - 2026-07-23

### Changed
- The dashboard now keeps a readable activity log. Every settings change, sign-in and rejected
  request is recorded with who did it, which server it was for, whether it worked and how long
  it took - so an admin can look back and see what happened. Ordinary page loads stay out of the
  log unless you ask for them (set `DASHBOARD_LOG_READS=1`).
- The dashboard had been running with debug logging left on, which buried anything useful under
  a constant stream of internal chatter. It now logs at the normal level, to both the console and
  a rotating file under `logs/`. Set `LOG_LEVEL=DEBUG` if you ever need the extra detail back.

### Fixed
- In the `/admin` panel, changing a setting that opens a text box saved your value but then
  errored out instead of taking you back to the menu, and the panel stopped responding. It
  now returns you to the menu with the new value showing.
- The **Privacy Policy** link in the footer was the same grey as the text next to it, so it
  did not look clickable. Footer links are now brighter and underline when you hover or tab
  to them, and links elsewhere on the dashboard use a lighter, easier-to-read violet.

## [Unreleased] - 2026-07-20

### Fixed
- Forwarding rules created from the web dashboard now actually forward messages. Rules made on the dashboard were saved without any message types turned on, so they silently forwarded nothing. New dashboard rules now start with text, media, links, embeds, and files enabled (stickers off), matching rules made through the `/admin` panel. Existing dashboard-made rules are repaired automatically - the bot fills in the missing settings the first time it reads them, so they start forwarding without anyone having to re-open or re-create them.
- Turning a disabled forwarding rule back on now counts against your server's rule limit, the same as making a new one. Previously the limit could be sidestepped by disabling a rule, creating another, then re-enabling the first - so a server could end up with more active rules than its plan allows.

### Changed
- Removed the old `/setup` and `/forward` setup wizard. It had stopped being reachable - none of its commands were actually registered - but the welcome message and the bot's status still pointed people to it. The welcome message and rotating status now point to `/admin` and the web dashboard, which are the real ways to set up and manage forwarding.

### Removed
- Cleaned out the unused setup-wizard code (about 3,000 lines) that no longer had any way to run. Rule setup and management are handled by the `/admin` panel and the web dashboard.
