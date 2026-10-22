# Stale insertion receipts, spec0033 revision5

The user reported two persistent queue states: waiting for a safe point, and an
unconfirmed outcome. This follows the still-unreleased immediate-insertion change.
Current application baseline is `210529788395aa7ec953ea94cb7192582498beb9`; the
combined local diff contains revisions4 and5. No commit, push or deployment has
been performed for either revision.

## Observed production facts

Read-only service metadata confirmed the Hub still runs the connector-skills
release, with its previous PID unchanged. Read-only receipt/history correlation
found an accepted steering receipt whose exact `steer:<command_id>` human message
was already in that same thread's canonical history. The associated scheduled
delivery had subsequently failed. The second unknown receipt had no corresponding
canonical message. Recent model/tool events showed ongoing work; no real task was
cancelled, retried or restarted, and no live database row was changed.

Inspection identified the missing path: `CronDeliveryService._deliver_agent`
consumed steering events but did not pass them through the gateway's receipt and
Dashboard control observer. It also did not end the live Dashboard state on errors.
The newly added test first failed because the accepted receipt stayed accepted
even when its canonical inserted human message existed.

Operational probes remain outside the repository under `../ops/` and omit prompt
bodies and credentials. The managed browser reached the login page, had no session,
and was closed without attempting login or changing the user's browser tabs.

## Change

- Scheduled Dashboard turns now observe/broadcast run phases, insertion application
  and inserted-user events through the same gateway path as resumed turns. Buffered
  prior public assistant text is delivered before the inserted user; the completion
  contains only the new answer. Raw reasoning and tool payloads are not broadcast by
  this added path. Success, error and cancellation close the visible stream.
- Gateway control observation updates active/idle markers, so reconnecting clients
  see the scheduled turn's current state. Existing session serialization remains.
- Receipt polling repairs requested/accepted/unknown entries only with an exact
  canonical human/user message ID in the authorized thread. An assistant message
  with that ID, a match in another thread, or mere elapsed time is insufficient.
  Read checks do not acquire a write transaction; only confirmed repairs use CAS.
- Unknown/failed/rejected receipts can be explicitly dismissed. The owner/thread
  checks and CAS reject pending work; retries are idempotent. Dismissal retains the
  audit payload and never withdraws, dispatches, cancels or replays a task. The UI
  provides a separate labelled clear-status action and explains unconfirmed state.

Harness runtime, wheel and lock are unchanged from the locally verified revision4
artifact. The fix does not claim to resolve the separately reported upstream
reasoning-content400 error, nor to terminate external/background processes.

## Verification

- All cron unit tests plus queue/API regression: **156 passed**, including both
  successful and failed scheduled turns updating the receipt and ending the stream.
- Final broader UI run: **84 passed across14files**, covering chat-store behavior,
  queue mode forwarding, clear-status without resend, and composer draft recovery.
- Application Ruff/format: **1355files pass**. mypy: **672source files pass**.
  i18n: **76passed**. Changed UI ESLint has0errors and3existing hook warnings.
- TypeScript and final production build: **passed**, including the updated status
  label and clear-status button; the final Vite build took79seconds.
- Final full non-live backend: **5050 passed,157 skipped,36 dependency warnings**,
  exit0,494.53seconds. Command: `uv run --frozen --no-sync pytest -n 8 -m 'not live'`.
  The final run includes active/idle reconnect-marker assertions; its XML is
  `../ops/stuck-input-full-final-results.xml`. An earlier partial run was deliberately
  stopped before that correction and is not counted as a full pass.

GNU make is unavailable on this host; the applicable lint, format, typecheck,
pytest and frontend build commands run directly. No skipped hook or CI success
is claimed. Tests use isolated synthetic data rather than production conversations.

## Release state

The user subsequently authorized merging and deploying both revisions together.
Publication is in progress on `hotfix/immediate-steering-and-receipts`; the earlier
local-only statements describe the implementation checkpoint. Deployment must
preserve active GPU/device jobs, reconcile the source/static/wheel artifacts, and
use an idle Hub window plus the established backup and rollback procedure. The old
accepted receipt will repair on a successful poll of the new version; the unproven
unknown receipt will remain available to dismiss without being resent.
