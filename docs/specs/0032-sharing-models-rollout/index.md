# 0032 会话分享、模型目录与部署

Date: 2026-10-18, Asia/Shanghai
Revision: 2026-10-18.1
Authority: User requested these features and explicitly authorized updating the cloud server and execution clients after development. The prior restriction on deployment applies to the previous task, not this newly authorized rollout. Preserve the GPU manager's scheduled experiment acceptance task.
Implementation: In progress. Architect and integrator: root. Coders: GPT-6.1 Sol high. Reviewer: GPT-6 Luna high.
Baseline: the complete frozen dirty result of0031 in both application and Harness checkouts, not their older HEAD alone. Prior verification and source manifest are recorded in0031/verification.md.

## 决定

分享是用户主动发布的一份只读会话快照。后续消息不会自动公开。链接可过期、可关闭，拥有链接的人可匿名查看。管理界面和 Agent Native 使用同一个领域服务。公开页面不获得原会话、专家、设备或附件的访问权限。

模型目录从官方当前 Go endpoint 表更新，并让已经配置的 Go provider 也能获得新目录。保留用户已有模型的启停、顺序、能力覆盖、默认模型和凭据。部署包含0031及0032，先核对真实服务和定时任务，再备份、分阶段切换、验证并保留回滚材料。

## Acceptance

| ID | Observable requirement |
| --- | --- |
| SH1 | Owner can preview and publish an exact filtered snapshot, receive an external URL, open it anonymously, and retain the same snapshot after new private messages arrive. A stale preview digest fails409 without publishing. |
| SH2 | Owner can list all own shares centrally and per thread, recopy a live URL and revoke it. Revoke is idempotent. Another user, including an admin acting as another user, cannot manage that owner's shares. Expired, revoked, unknown or disabled-owner shares return the same public404. |
| SH3 | Public data contains only the reviewed title/timezone and user/assistant text. No wire metadata, thinking, tool bodies, auto attachment hints, private media URLs or source identifiers. Public rendering disables raw HTML, images, relative/private file links and execution. No authenticated client or chat runtime is required. |
| SH4 | Native preview/create/list/revoke use authenticated runtime owner and existing management-tool policy/audit. Model prose or IDs do not grant ownership. Read operations work under existing read policy; create/revoke respect Ask/Plan write restrictions. Native creation returns a real configured public URL. |
| MD1 | Current supported Go models include MiMo V2.6 Pro/Flash with correct Chat Completions routing and current supported official additions. New preset endpoints follow the official protocol paths. Google-native-only models are not falsely advertised as compatible. |
| MD2 | Existing Go providers see new selectable models in UI, resolution and actual Harness configs, without changing existing IDs, explicit disabled states, capability overrides, ordering, default selection, custom URLs, API keys or headers. Zen and arbitrary custom providers are untouched. |
| OP1 | Deployment inventories actual cloud source/runtime and execution clients, records the GPU experiment cron identity/schedule/prompt/model/status, and checks active work. Staging and smoke checks precede interruption. No GPU experiment process, output, queued acceptance or unrelated device identity is reset. |
| OP2 | Cloud and reachable execution clients run the tested source/package after controlled restart, keep identity/state, reconnect and pass health/native-protocol checks. Schema29 and30 apply monotonically. Public HTTPS share loading and revoke are exercised with synthetic data, and cleanup is bounded to that synthetic data. |
| OP3 | Backup and rollback instructions refer to verified actual paths/hashes and preserve cron/history/device state. Report unreachable clients or any deferred interruption honestly rather than counting them upgraded. No Git commit, push, tag or public release is implied by deployment authorization. |

## Sharing contract

Add a bounded `infra/history/sharing.py` service, a `ThreadShareRepo`, and SQLite/PostgreSQL030 migration pair after029. REST, UI and native tools call this service. Source messages come from canonical `history.reader.read_page`, including legacy history, not only `thread_messages` and not dashboard wire serialization.

Snapshot builder uses a strict public projector: normalize human/user and ai/assistant to user/assistant, accept only string or text blocks, remove thinking and recognized machine attachment/offload hints, exclude all other roles/blocks/metadata. Preserve legitimate repeated text in separate messages. Public message IDs are local sequence numbers, never internal thread/agent/message IDs. Do not claim automatic detection of arbitrary secrets typed in ordinary message text; preview tells the owner to review the exact text before publishing.

Bound the full export to2000 public messages and4 MiB UTF8 snapshot JSON. Reject an oversized or empty share with a typed actionable error, without silently truncating it. Page the source within a captured upper bound and apply bounded scan limits to internal-only histories too. Preview digest is SHA256 of deterministic canonical public snapshot fields, excluding request-time timestamps. Create re-builds and verifies the supplied digest; a changed snapshot is409. No client-supplied message body becomes the published source.

Share row: public share_id, owner_user_id, source_agent_id/source_thread_id, token_hash unique, encrypted token, snapshot_json, snapshot_version=1, message_count, created_at, expires_at nullable, revoked_at nullable. User/thread deletion cascades the row so an old link cannot bypass deletion. Public lookup also checks owner remains enabled. Store token SHA256 for lookup, never plaintext token. To let the owner recopy/manage existing links, encrypt the token using the existing cryptography.Fernet dependency and installation-specific SecretRepo key, following existing domain encryption patterns; do not invent cryptography or reuse a provider/SSO token key. Raw token appears only in authorized management/native responses and the public URL. Revoke clears recoverable encrypted token and records revoked_at atomically; never reactivate that link.

Default expiry is30 days. UI offers1 day,7 days,30 days and no automatic expiry. REST accepts null or60..31536000 seconds. Expiry is evaluated at every public read, not only by a cleanup job. Owner lists are bounded cursor pages, newest first; compute active/expired/revoked status without mutating state on reads. Active entries include recopyable URL; inactive entries do not. Source labels/IDs are owner-only management fields.

Add `OctopConfig.public_origin: str = ""`, env `OCTOP_PUBLIC_ORIGIN`, a validated HTTPS origin without credentials/query/fragment/path. An empty setting keeps private functionality usable but share creation fails with a clear configuration-required error; preview/list/revoke still work. Do not derive public origin from arbitrary forwarded headers, bind_host, SSO settings or localhost. Rollout sets the actual verified origin `https://octop.effaf.me`. Public URL is `${public_origin}/share/${token}`. Tests may use a synthetic HTTPS origin. No browser-origin or user-supplied URL becomes authority.

HTTP under existing `/api` mount:

* GET `/agents/{agent_id}/threads/{thread_id}/share-preview` -> `{preview_digest,title,timezone,messages,message_count}`.
* POST `/agents/{agent_id}/threads/{thread_id}/shares` body `{preview_digest,expires_in_seconds?}` ->201 owner share record including `{share_id,public_url,public_path,title,agent_id,thread_id,created_at,expires_at,revoked_at,status,message_count}`.
* GET `/agents/{agent_id}/threads/{thread_id}/shares?before=&limit=` and GET `/thread-shares?before=&limit=` -> `{shares,next_before,has_more}`. `before` is an exclusive bounded owner-record cursor, default page50/max100. Avoid leaking raw token via cursor.
* DELETE `/thread-shares/{share_id}` ->204; optional thread-scoped DELETE delegates to the exact same owner check, not a weaker second implementation.
* GET `/public/thread-shares/{token}` -> `{title,timezone,created_at,expires_at,messages:[{id,role,content}]}`. Token is a32-byte URL-safe random capability. Only this exact GET route is anonymous; malformed tokens fail before lookup. All other public-prefix methods/routes and all management operations retain normal authentication.

Use existing typed errors where their semantics fit; new share error codes require backend/dashboard zh/en parity. Anonymous missing/revoked/expired failures expose no state distinction. Responses use `Cache-Control: no-store`, `X-Robots-Tag: noindex, nofollow, noarchive`, `Referrer-Policy: no-referrer`; never explicitly log token, body or encrypted value. Redact share capability paths in existing application access logs where applicable. Keep reverse proxy logs from recording share URLs during rollout.

Native names: `octop_thread_share_preview`, `octop_thread_share_create`, `octop_thread_share_list`, `octop_thread_share_revoke`. Preview/create accept optional thread_id (default current authenticated runtime thread), never owner/user/agent authority arguments; service resolves the owned source. Create requires preview_digest and expiry, and its description/instructions allow publishing only when the user explicitly asks for external sharing. List supports optional thread_id, omission lists all own shares. Revoke takes share_id. Use existing `operation(writes=...)` checks, audit and disabled-tool policy, tool catalog/capability discovery, prompts and i18n. A model-supplied confirm=true is not a new security authority. Existing write/HITL policy remains the enforcement boundary; no bespoke language-intent regex or guessed authorization.

## UI

One owner ShareManagement dialog previews exact public text, explains snapshot/exclusions/link access, selects expiry, creates and copies URL, lists the thread's existing links and closes them. Reach it from desktop ChatTitleBar and mobile/history SessionList through the existing sidebar chain. Add an authenticated global share management page reachable from normal navigation/settings; show source title, creation/expiry/status, copy active links and close. Pagination must work without listing another owner's data.

Anonymous `/share/:token` is a top-level route outside AuthGuard and MainLayout. Use independent credential-free, no-store fetch, no401 token-clearing behavior and no private providers. Render safe public Markdown (GFM/code/math as feasible), no raw HTML, automatic images, private file/relative links or attachment downloads. HTTP(S) links are manual with noreferrer/noopener and no referrer. Failed/expired/revoked public pages show one generic unavailable state, network failure offers retry and hides retained text. Revalidate every30 seconds while visible, on focus and online; a404 clears rendered content. Do not persist snapshot JSON in storage/service worker/offline cache. Explain that closing a link prevents future access but cannot retract copies already saved.

## Go model update

Source of truth: official current Go endpoint table, checked2026-10-18: https://opencode.ai/v2/docs/console/go/#endpoints. Older localized/docs subdomains can lag. Exact IDs and routing, not marketing labels, define support. Current local Harness and its0031 vendor wheel already have `mimo-v2.6-pro` and `mimo-v2.6-flash`; cloud version and persisted provider catalogs can still be stale. Fix both delivery and effective model resolution.

Canonical new preset bases: Compatible/OpenAI `https://opencode.ai/inference/go/openai/v1`; Anthropic `https://opencode.ai/inference/go/anthropic` (SDK appends `/v1/messages`). MiMo is Chat Completions, not Responses; preserve per-model use_responses_api. Add current officially listed models supported by existing protocols, deduplicate model IDs, reuse verified capability metadata where known, and use unknown/None rather than guessing context, token limits or capabilities. Exclude Google-native-only Gemini until the runtime supports that protocol; do not build an unrelated new adapter in this slice. Do not remove existing working model IDs solely because a documentation version no longer lists them.

Centralize effective built-in Go model merging for owner API, model resolution and ProviderStore Harness configuration, so UI-only updates cannot leave runtime stale. Match an exact known Go preset identity/variant and compatible kind + recognized OpenCode Go endpoint; never fuzzy-match Zen, arbitrary provider names or custom proxy URLs. Keep all persisted entries and order; existing same-ID values including explicit false/zero win, filling only genuinely missing metadata. Append new canonical models as selectable/enabled (an existing explicit disabled model stays disabled). Preserve default/active/preferred references, credentials, session headers and custom fields. No read path rewrites the database. Configured custom URLs remain untouched; canonical endpoint changes apply to the new preset and explicit preset synchronization, not an unsolicited rewrite of stored endpoints. A catalog bump makes missing options visible without automatically changing any scheduled task's chosen model.

## Build and rollout ownership

Backend coder owns app history sharing/crypto, share repository/migration030, RepoBundle, routes/auth boundary, config.public_origin, native management registration/mode/catalog/backend i18n, and associated backend tests. Frontend coder owns dashboard sharing UI/public route/global management and localized labels/tests. Catalog coder owns Harness provider_template/catalog/tests plus app `infra/agents/providers/`, `api/routers/providers.py`, and provider-model tests only. Root owns this spec, ops, shared plan, dependency wheel/lock, source packaging, final gates and deployment. Do not commit, push or deploy from worker tasks.

Root builds a new reviewed portable Harness wheel after catalog freeze, updates the existing relative source/lock manifest and installs the actual wheel for app integration. Build dashboard to an isolated output first, then stage the complete compiled dashboard for cloud packaging. Preserve0031 improvements and all unrelated dirty work. Read-only GPT-6 Luna high review must cover public auth/capability/renderer boundaries, native policy, provider merging and deployment experiment preservation.

Preflight already confirmed cloud hub `/root/octopus-main/.venv/bin/octop`, cwd `/root/octopus-main`, data `/root/OctopData`, schema28. Cloud device runs a separate b16 portable runtime. GPU, cloud, laptop and workstation have fresh b16 heartbeats. One enabled GPU-manager cron is named `PCCM 实验1 收尾：四档跑完即出 Step4 报告`, `interval:1800`; treat those values as observed evidence, re-read before rollout rather than trusting old deployment reports.

Before switch, inventory exact cron_id/model/prompt/meta and active runs/device jobs, determine next trigger, stage compatible artifacts, snapshot DB/config/code/service definitions and record hashes. Never stop experiment training/evaluation processes or discard its schedule. If hub work is active, stage while it runs and wait for an idle gap. Any bounded pause of the specific scheduler during the actual hub switch must be recorded and restored with the same identity/schedule/model and a verified next run, avoiding duplicate acceptance. Restart clients one at a time after checking active native/PTY/process jobs and process supervision; preserve device state and identity. Unreachable clients are reported/deferred, with a reviewable package or existing authorized update path if available.

Cloud schema upgrade applies029 then030. Deployment uses the tested app/Harness source together, not old0031-only files plus a stale runtime. Check local/public HTTPS health, runtime import/source hashes, model presets/effective models, native capability presence, synthetic share create/anonymous-read/revoke and unchanged cron definition. Roll back code plus compatible data from the bounded backup if checks fail; do not wipe live experiments, history, device state or additive event/resource audit records. Do not claim an upgrade based solely on an unchanged b16 version string; verify build hashes and running entrypoints.

## Limits

Public snapshots do not grant access to attachments, live child collaboration, device operations or ongoing chat. External users cannot interact with the agent. Google-native model support is deferred. No real conversation is automatically published during development or rollout; public smoke tests use only synthetic data. Keep deployment credentials and share tokens out of evidence logs.
