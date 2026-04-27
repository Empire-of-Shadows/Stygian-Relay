# Changelog

## 2025-12-23

### Added
- **Manager Role System**: Guild administrators can now designate a role that grants settings management permissions without requiring full administrator access.
  - New `/settings set-manager-role <role>` command to assign manager role (admin only)
  - New `/settings remove-manager-role` command to remove manager role (admin only)
  - New `/settings view` command to view current guild configuration (all members)
  - Manager role permissions include: managing forwarding rules, redeeming premium codes, and configuring bot settings
- **Smart Branding System**: Replaced always-on branding with intelligent occasional display for non-premium guilds.
  - Branding now shows on only 20% of forwarded messages (configurable)
  - Minimum 10-minute cooldown between branding messages to prevent back-to-back display
  - Significantly less intrusive while maintaining visibility

### Changed
- **Premium Code Redemption**: Removed admin-only restriction - any guild member can now redeem premium codes.
  - Encourages community members to support their servers
  - Audit trail maintained (tracks who redeemed codes)
  - Bot owner can still deactivate premium if needed
- **Permission System**: Forwarding commands (`/forward setup`, `/forward edit`, `/forward delete_rule`, `/forward list_rules`) now respect the manager role in addition to Manage Server permission.

### Fixed
- Replaced deprecated `datetime.utcnow()` with `datetime.now(timezone.utc)` for Python 3.12+ compatibility.

### Technical
- Created new `database/permissions.py` module with reusable permission checking utilities
- Created new `extensions/settings/` extension for guild settings management
- Added `manager_role_id` field to `DEFAULT_GUILD_SETTINGS_TEMPLATE` in database schema

## 2025-11-25

### Improved
- Increased the default cumulative attachment size limit for forwarded messages from 8MB to 10MB.

### Fixed
- Removed an unnecessary newline before the attachment size limit message for improved formatting.

## 2025-11-24

### Fixed
- Added robust error handling for "413 Payload Too Large" (error code 40005) HTTP exceptions during message forwarding. If an initial send attempt fails due to payload size, the message is automatically retried without attachments to ensure the text content and embeds are still delivered.

## 2025-11-19

### Fixed
- Resolved "413 Payload Too Large" error when forwarding messages with large attachments by implementing a cumulative attachment size limit.
  - The total attachment size for forwarded messages is now capped at 8MB by default.
  - For Discord servers boosted to Level 2 or higher, the total attachment size limit is dynamically increased to 50MB.

### Improved
- Enhanced attachment handling in `forward_as_component_v2` to prevent redundant processing and improve logging for omitted attachments.