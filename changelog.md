# Changelog

## 2025-11-19

### Fixed
- Resolved "413 Payload Too Large" error when forwarding messages with large attachments by implementing a cumulative attachment size limit.
  - The total attachment size for forwarded messages is now capped at 8MB by default.
  - For Discord servers boosted to Level 2 or higher, the total attachment size limit is dynamically increased to 50MB.

### Improved
- Enhanced attachment handling in `forward_as_component_v2` to prevent redundant processing and improve logging for omitted attachments.