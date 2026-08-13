# Changelog

## [Unreleased] - 2026-08-13

### Fixed
- On phones, the server panel on the settings hub now shows its close button and its server
  icon in full instead of cutting them off at the panel's rounded edge, and the close button
  stays put while you scroll the panel.

### Changed
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
