# Peer context and occupancy verification

Spec: 0024, AC1–AC4. Management baseline5f8033e4; harness baseline3a82d260.

The GPU chat exhibited a real integration gap: synchronous peer invocation called
the raw harness agent without normal host request preparation. Parent identity
therefore reached child tools. The request-scoped restore now runs normal manager
preparation after restoring consent; every restore rebinds the persisted context
to the callee/thread/run. The inherited target stays intentional. Real SQLite and
Harness team regression covers sync/inbox × inherit/member_default/explicit,
preserves Ask restrictions and checks the actual child context. Existing grant
revocation tests remain active. New tool guidance explains that naming a device
in task prose or changing a conversation selection does not override inherit.

Native expert create/update expose only a bounded device_binding. Validation
checks owned devices, readable roots for restricted targets, local-target shape,
working-directory bounds and unknown keys. It does not update grants, allow
arbitrary config_json or mutate active contexts. Tests cover save/readback,
preserve, clear and rejected writes without partial name changes.

Capacity resolution reads the conversation model then expert/default selection
using the expert owner's providers, including shared-expert conversations. Runtime
caps are bounded by known model capacity and keep explicit provenance; real128k
is not inferred to be unknown by numeric equality. On restart, the bounded history
query reads per-call input and refuses multi-call billing sums. Raw snapshot input
is retained if its displayed count had been clipped against a fallback window.
The ring uses canonical capacity even with connectors, refreshes on usage/model
changes and rejects previous-thread late responses.

Harness2ac4d602 marks every facade invocation and resume. The parent stream filters
nested invocation callbacks before accumulating text/reasoning/tool chunks/usage.
A real nested StateGraph using fake chat models verifies only host text streams,
while the child result remains available. The management HITL compatibility shim
forwards the new projection argument; a combined test verifies both interrupt
events and nested-token exclusion.

Evidence: harness normal make all1745passed/39conditional skips, Ruff and strict
mypy191files; installed-archive focused management78passed, expanded policy
matrix6passed, frontend focused17passed. Full backend4795passed/153skipped with
one Windows child-process temporary state read PermissionError; both cases of that
unmodified test passed when rerun. Normal final submission gate and build are
recorded in ops logs. Full frontend1367passed/12failed in four unmodified files;
the exact baseline reproduced identical12failures/25passes in those files.

Browser inspection unavailable because Work settings disable local browser
control. Component tests and build do not constitute a live screenshot check.
Deployment smoke uses isolated temporary SQLite, fake models and virtual devices,
with no real provider/device calls. Preserve historical messages and existing
memory maintenance. No OS permissions or cross-account grants are changed.
