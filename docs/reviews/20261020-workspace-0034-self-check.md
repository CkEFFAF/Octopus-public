# 0034 final continuation self-check

Latest update: the UI-refinement appendix below supersedes the historical frontend failures recorded in this file. Full frontend now has1522 passing tests; full ESLint has zero errors. No independent review, Git publication or deployment is implied.

Date: 2026-10-20, Asia/Shanghai. Scope: root changes following the earlier independent review freezes, against spec revision 4 including 9.9.1/9.9.2. This is the implementer's self-check, not an independent review. The user explicitly withdrew collaboration-subagent use; no replacement reviewer was launched.

The historical independent review in `20261019-workspace-0034-check.md` is retained for its exact frozen slices. Its manifests do not certify later root edits. `../workspace-0034-final-code-sha256.json` fingerprints the current application source, tests, lock and portable dependency artifacts; it is an identity record, not test evidence.

## Findings addressed in the continuation

- Live target status used the stored device row rather than its connection projection. ExecutionService now uses DeviceService's current projection after owner checks; real connect/disconnect regression and actual device observations support this change.
- Fresh execution contexts produced different preview versions and lost visible comments. The stable source identity now incorporates authorized target/policy/grant/path/content; every reopen still reads through current authorization before rebinding. Real SQLite regressions, public API receipts and owner-device full-page reload recovered the same image-region comment. Revoking the temporary device denied the old context and all seven stored preview URLs.
- Dashboard scheduled delivery and active input processing used different locks for the same thread. Delivery now uses the input queue's thread lock; the reproduced failure is retained, followed by successful busy-parallel delivery and exactly-once pending-trigger recovery across backend restart. The Harness pending-work guard was preserved.
- Opaque device save errors hid actual conflicts. The editor compares authorized current bytes, displays the remote version, preserves the local draft, and does not overwrite it with a failed refresh. Real second-client device writes and focused regression verified this behavior.
- The graph mixed historical plans and shrank forks into unreadable text. Explicit run selection, stable user zoom, centered ranks and readable narrow-panel horizontal pan were exercised on actual overlapping native tasks/Jobs, cancellation, manual Job retry and network loss/reconnect.
- Actual hit-testing found collapsed sidebar contents and dock menu stacking blocking file interactions. The collapsed child is hidden/noninteractive; portaled layout/add-tab/file-operation menus use the dock overlay layer. After a full reload, the actual layout item received input and popup/fullscreen worked. Native owner-device editing displayed 24 sample lines; 894/375 measurements showed no page overflow.
- Unread Job logs and cancelled work could show misleading completed text. Read/unread/empty output states are now distinct and neutral. A real running Job showed the animation, reduced-motion disabled it, and offline observation stopped current-running claims. Read-only files have an explicit localized tag and rejected actual keyboard edits/save.
- Packaging review found the pinned activity.3 wheel was excluded by the vendor ignore rule. Exact artifact exceptions, source archive and provenance are now included. The wheel hash matches uv.lock, all 371 package members match the source manifest, and the source archive digest matches. The previous tooltext.1 manifest is explicitly historical.

## Evidence and limits

The final scenario ledger is in `../progress-workspace-0034.md`; raw local screenshots and receipts live in parent `ops/workspace-0034/ego-ui-20261020/`. Root inspected actual screenshots, not just test DOM. Tests used the real application/runtime/transport with disposable files and a deterministic provider; external model reasoning, physical device/WAN performance and production rollout are outside this evidence.

Backend non-live full suite: **4993 passed, 157 skipped**. Strict mypy: **670 files**. Ruff passed. Focused activity/resource tests: **14 passed**; subsequent dock/native-file tests: **8 passed**; final i18n tests: **76 passed**. TypeScript project build, feature-scoped ESLint/Prettier and production build6 passed. The locale-only read-only-label addition followed the eight-test run and was additionally checked by TypeScript, i18n, production build and the actual 894/375 read-only UI.

The full frontend run has **1489 passed / 12 failed**. All twelve were independently reproduced on unchanged baseline c236203: eight useChatDockPanel cases and four across sidebarNavLayout, controlAdminPath and RunReceiptBrowser. Full ESLint also retains an existing unused-constant error outside this change. These are unresolved release-gate facts, not a green suite. Permission-related baseline assertions were not weakened to clear the gate. Runtime Swagger/OpenAPI is disabled (404); no live docs rendering pass is claimed.

The temporary loopback owner file device was stopped and revoked, the original restricted device permissions were preserved, and the isolated session returned to local `workspace-samples`. Review evidence and samples are retained. No Git publication or production/GPU deployment occurred. Root's visual inspection does not substitute for the user's acceptance of the revised UI.

## UI-refinement self-check update

The final UI continuation addresses the user's latest request to improve the actual application. Root remained the sole implementer/verifier and used the original authorized ego-lite space. It was finished in round244 with the final workbench retained for user review.

Resolved findings:

- Preview actions/identity previously consumed too much vertical space. One approximately55px header now groups them; the document/media body owns the remaining height. The actual1390px image/comment screen,894px large Word,375px Markdown and video were inspected. Video range controls are12px below its player. Component-library controls now share the page's explicit Chinese font fallback.
- Saved-comment location inadvertently started a new draft. A selection revision distinguishes new selections from location changes. The draft captures its own anchor, whole-file comments use a file anchor, and reply fields appear only when requested. Five focused annotation regressions and actual persisted comment/reply/locate/close/reopen checks passed.
- Switching text files reused Monaco undo state. Actual py→md→undo reproduced the failure; editor identity now includes context and full path. The repeated actual sequence no longer imports Python into Markdown and leaves the file clean. No file save was used to mask the regression.
- Parent navigation manufactured a `child/..` source alias, hiding the original comments when the same image was reopened. Native parent paths now remain stable across directory round trips and drive/UNC/POSIX roots. Twelve helper cases plus one component navigation regression passed. After full reload the real round trip recovered the original comment and reply (`ui-polish-parent-roundtrip.json`). Explicit dot segments remain endpoint-resolved.
- At375px the annotation overlay overlapped the bottom of the new header. Measured final toolbar bottom199.53px and pane top209.06px leave clearance and no page overflow (`ui-polish-overlay-geometry.json`).
- Real timer attempt history is displayed as compact neutral records with truthful completion/failure state. Three actual bounded-reminder attempts remained available at1390px and375px; the phone close control remains in the viewport. Screenshot/geometry evidence is in the final progress ledger.

Release-gate follow-up repaired the former12 baseline failures at their actual test contracts: context-scoped async dock opening, receipt detail dependency mock, and existing authenticated model-page access. Anonymous and privileged-route denial checks remain. No product permissions were broadened. The unused-import lint error, missing dock-layer mock export and cold lazy-Markdown assertion were also corrected.

Current verification: full frontend **277 files /1522 tests passed** (`.0034-ui-polish-full-frontend-final.log`); full ESLint **0 errors /78 existing warnings** (`.0034-ui-polish-lint-complete.log`); TypeScript/Vite production build passed (`.0034-ui-polish-build-font-final.log`); changed-file formatting and diff whitespace checks passed; locale tests **76 passed**. Backend source/tests were unchanged relative to the previous50-file fingerprints, so the earlier4993/157 full-suite, Ruff and strict-mypy evidence is retained, not presented as a new run.

The refreshed final code SHA256 manifest identifies this source. The self-check found no remaining blocker in this UI slice; it does not replace user visual acceptance or a future independent review. No commit, push, PR or deployment occurred.
