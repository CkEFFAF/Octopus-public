# Premerge sharing and model catalog review

Date: 2026-10-18, Asia/Shanghai. Mode: check review, read-only source review.
Comparison: application HEAD `60111355` and Harness HEAD `2ac4d602`, including tracked dirty changes and new files. Contracts: 0031 revision 2026-10-18.4 and 0032 revision 2026-10-18.1. Existing independent 0031 review remains the source for its earlier detailed lifecycle/resource review. No source, Git, deployment or external state was changed by this reviewer.

## Findings

1. **[P2, resolved after source re-review] Reject private destinations independently of the public page origin.** The original renderer accepted cross-origin localhost/private-network links and checked private application paths only on the current origin. The corrected `PublicMarkdown.tsx` independently rejects localhost/local/single-label hosts; normalized loopback, RFC1918, link-local, CGNAT and local/mapped IPv6 destinations; credentials; and decoded known private application paths on any origin. The correction applies to the shared anchor renderer, covering inline Markdown, angle autolinks and GFM bare links. Fourteen new parameterized regression cases exercise these forms while retaining an ordinary public external link. Source re-review found the original defect closed; integrator test execution remains the runtime evidence.

No remaining material source finding was identified in this bounded pass.

## Default history integration re-review

The integrator subsequently found that normal startup can leave `history_archive=None` when versioned history is disabled; the first sharing implementation incorrectly rejected this valid configuration. Source re-review confirms `history.reader.read_page` now accepts the absent archive together with the existing `ThreadMessageRepo`, and `ThreadSharingService.preview` supplies its own repository after the unchanged active-owner/thread checks. Existing archive callers retain their previous repository and segment branch. Both legacy projection and checkpoint pagination retain their existing scoped cursors; checkpoint anchors still force the selected thread, and older projection pages use an exclusive sequence boundary. No new store is created and no source history is repaired by sharing reads.

The legacy regression is parameterized for absent/present archives. The real server integration now invokes the tools from the assembled Harness configuration and exercises preview/create/public read/list/mode denial/revoke under the default startup configuration. The integrator reported 11 passing focused cases. This reviewer did not run those tests; the source correction introduces no identified ownership or pagination regression.

## Go discovery endpoint re-review

The final discovery correction reuses the same exact built-in name, OpenAI protocol and recognized Go endpoint matcher with an empty synthetic persisted catalog. Consequently, only a recognized built-in Go compatible provider obtains a nonempty catalog and switches discovery to the shared official `/inference/go/v1/models` URL. Custom proxy URLs, Zen and the Anthropic variant do not qualify. The response is intersected with that compatible-protocol catalog before ordinary deduplication; unsupported native-only models are not offered from the shared response. Credential/session headers retain the existing handling, and a custom URL does not redirect its credentials to the official endpoint. Source re-review identified no identity-matching or protocol-leak regression. The integrator reported 30 passing model-related tests; this reviewer did not execute them.

## Positive evidence

- Public reads use the exact anonymous GET route and a random 32-byte capability; management checks the actual active owner without admin impersonation. Expiry, revocation and disabled-owner lookup share the generic unavailable response.
- Snapshot creation re-reads canonical history, validates the preview digest, bounds source/public messages and encoded snapshot size, and keeps only projected text. Tokens are hashed for public lookup and separately encrypted for authorized recopy; revoke atomically removes recovery material.
- The public route sits outside AuthGuard and private providers; its fetch omits credentials/cache, and its renderer omits images, raw HTML and execution controls. Failed refreshes clear retained content.
- Native tools reuse authenticated runtime identity, write-mode restrictions, disabled-tool policy and minimal audit payloads.
- One effective Go catalog feeds API, resolution and Harness configuration. Exact name/protocol/recognized endpoint matching, deep copies and null-aware metadata filling preserve saved order, explicit disabled/false/zero values, credentials, headers and custom endpoints; new catalog entries do not rewrite the database or an existing model reference.
- SQLite/PostgreSQL 030 migrations are additive after 029 and cascade source/owner deletion. The deployment contract explicitly preserves the GPU experiment cron identity, model, prompt, schedule and device jobs, stages artifacts before interruption, and requires hashes and synthetic share lifecycle checks.

## Verification and release limits

This reviewer inspected source, the renderer correction and its regression cases; tests and live deployment were not executed by this reviewer. The integrator must run the affected renderer tests, complete the pending typecheck/vendor-wheel checks and preserve the recorded baseline failures separately. A green source review is not evidence of an upgraded cloud or client runtime. At rollout, verify actual paths/processes and artifact hashes, backup the pre-migration data, retain the experiment cron and require an idle window before each controlled restart. Do not restore an old whole data directory over new unrelated experiment output when rolling back code/schema.
