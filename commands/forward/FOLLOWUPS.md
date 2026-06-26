# Forward Extension — Follow-ups

Carryover from the audit at `~/.claude/plans/lets-take-a-deep-joyful-quokka.md`. Items already shipped are omitted; this file is only what's still open.

## Improvements (non-bug)


## Additions — from `Roadmap.md` (still planned)

- **`handle_manage_rules` stub.** Same status — wired-up button that returns "not implemented". Either ship or remove the button.
- **User/role restrictions** on filter rules. (Phase 4)
- **Custom message templates / advanced embed customization.** (Phase 4) — partial helpers (`_parse_template_variables`, `_get_embed_color`, `_sanitize_embed`) were deleted as unreachable; reintroduce when wiring a non-native forward style.
- **Premium upgrade prompts** when hitting daily/rule limits. (Phase 5)
- **Usage analytics dashboard.** (Phase 5)

## Additions — beyond Roadmap

- **Edit/delete propagation.** Mirror source-message edits/deletes onto forwarded copies. Requires storing a `source_id → forwarded_message_id` map (likely TTL'd in `message_logs`).
- **Thread / forum channel support.** Wizard only offers `discord.ChannelType.text`; threads and forum posts bypass the feature entirely.

## Suggested next slice

If picking one chunk: **rule testing UI + remove/replace `handle_manage_rules` stub + forwarding metrics**. Closes the two visible "not implemented" stubs, gives admins observability, and unblocks the Roadmap Phase 3 line.
