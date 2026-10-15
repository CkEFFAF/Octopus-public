# b12 handshake reconnect review — 2026-10-15

Baseline: public/main `97fccd2b872c0c314051ab237946a4aad978a334`; scope: DeviceClient reconnect change and its real local WebSocket regressions. Code authored by gpt-6.1-sol/high; parent reviewed separately from the author. The previously used 5.6 reviewer reported an account usage limit, so no additional 5.6 review is claimed.

## Findings

No actionable issue found in this bounded diff. The subclass returns the original non-redirect exception, preserving the existing typed reconnect handling; it never calls the base redirect handler. A redirect requires both the explicit redirect status and a Location header and remains fatal before the device hello is sent. An invalid hello is still a fatal authentication failure. No enrollment, credential, policy or installed runtime mutation was introduced.

## Verification evidence

The author first ran real local WebSocket regression cases against the original code: **2 failed, 7 passed**. Both temporary HTTP503 / HTTP200-without-upgrade cases failed because InvalidStatus became DeviceExecutionError. After the repair, the complete client suite passed **38 tests**, followed by a second formatted-source run **38 passed in 13.99s**. Tests observe a successful ping after reconnection, stable device identity, no requests or frames at a second redirect destination across six statuses, and fatal hello authentication rejection. Ruff check/format, focused strict mypy and diff whitespace checks passed. Required integrated commit and hosted CI gates remain pending at review time.

The installed websockets 15.0.1 source was independently inspected: its handshake exception handler calls process_redirect for exceptions beyond actual redirects, confirming the reported mechanism. Historical laptop incident attribution remains unproven; timeout/reset were not separately injected in these new cases. Existing typed handling of those exceptions is preserved.