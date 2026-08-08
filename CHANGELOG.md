# Changelog

## [Unreleased] - 2026-08-07

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
