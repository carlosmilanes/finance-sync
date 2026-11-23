# CLAUDE.md — Project Instructions

Check @project.md for a project overview.

## Before making any changes to API code

**Always consult the Enable Banking API documentation first.** This project is rate-limited to approximately 4 API calls per account per day by ActivoBank. Every failed test wastes one of those daily calls, so changes to API interaction code must be as correct as possible before running.

Relevant sources to check:

- **API reference:** https://enablebanking.com/docs/api/reference/
- **FAQ (rate limits, field semantics, deduplication):** https://enablebanking.com/docs/faq/
- **Python samples:** https://github.com/enablebanking/enablebanking-api-samples

Key things to verify in the docs before touching API calls:
- Correct field names for the endpoint in use
- Whether pagination (`continuation_key`) applies to the response
- Rate limit behavior and any headers that influence it
- The distinction between `entry_reference` (stable unique ID) and `transaction_id` (unstable, do not use for deduplication)
