# Codex UI handoff — G4 device file transfers (after 0044)

- Date: 2026-11-07 (Asia/Shanghai)
- Backend tip baseline: `2466b692341746ccdb5b0d1ec0e1a94c757efd86` (#68 squash)
- Spec: `docs/specs/0044-audited-device-p2p-file-transfer.md`

## Surface for Codex

- HTTP: device file transfer APIs under `/api` (create / list / detail / cancel as shipped in #68)
- Events: `transfer.changed` pushed via account notification hub (`push_to_user`)
- Do **not** change `dashboard/` chat-task-work in this handoff; render transfers in Codex-owned UI

## Notes

- Prefer reading live OpenAPI from a running server after main includes 0044
- Advertise host must be routable (non-loopback) for LAN direct; Hub fallback remains
- Receipts require sha256 before `completed`
