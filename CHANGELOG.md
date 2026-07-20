# Changelog

## [Unreleased] - 2026-07-20

### Fixed
- Forwarding rules created from the web dashboard now actually forward messages. Rules made on the dashboard were saved without any message types turned on, so they silently forwarded nothing. New dashboard rules now start with text, media, links, embeds, and files enabled (stickers off), matching rules made through the `/admin` panel. Existing dashboard-made rules are repaired automatically the next time they are opened or edited on the dashboard.

### Changed
- Removed the old `/setup` and `/forward` setup wizard. It had stopped being reachable - none of its commands were actually registered - but the welcome message and the bot's status still pointed people to it. The welcome message and rotating status now point to `/admin` and the web dashboard, which are the real ways to set up and manage forwarding.

### Removed
- Cleaned out the unused setup-wizard code (about 3,000 lines) that no longer had any way to run. Rule setup and management are handled by the `/admin` panel and the web dashboard.
