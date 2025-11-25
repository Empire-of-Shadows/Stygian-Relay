# Changelog

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