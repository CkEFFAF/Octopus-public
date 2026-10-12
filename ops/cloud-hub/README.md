# Cloud hub ops scripts (0009 S1+S2)

Tracked helpers for Ubuntu 24 cloud management hub. Authoritative checklist:
`docs/octopus/cloud-hub-ops.md`. Spec: `docs/specs/0009-cloud-hub-production.md`.

| File | Role |
|------|------|
| `install-hub.sh` | Write `/etc/systemd/system/octop-hub.service`, optional `uv sync`, `enable --now` |
| `smoke-hub.sh` | `curl` `/api/health` |
| `octop-hub.service.in` | Unit template (`OCTOP_HOME`, bind host/port) |
| `octop-hub.root.service.example` | Concrete root example (`/root/octopus`, `/root/OctopData`) |
| `octop-hub.ubuntu.service.example` | Concrete ubuntu example |

Notes:

- Data directory is **`OCTOP_HOME`** (env). There is no `octop run --home` flag.
- MVP smoke binds **`0.0.0.0:8188`** (topology B HTTP IP). Product device default remains `https://octop.effaf.me`.
- Never commit Deploy Keys / tokens / passwords.