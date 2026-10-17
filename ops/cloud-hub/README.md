# Cloud hub ops scripts (0027 S0 / 0009)

Tracked helpers for Ubuntu 24 cloud management hub. Authoritative checklist:
`docs/octopus/cloud-hub-ops.md`. Specs: `docs/specs/0027-ops-host-runtime.md` (Ready),
`docs/specs/0009-cloud-hub-production.md` (Accepted; production defaults upgraded by 0027).

| File | Role |
|------|------|
| `install-hub.sh` | Write unit + **`90-octop.conf`**, archive stale `50-*` drop-ins, optional `uv sync [--frozen]`, `enable --now` |
| `upgrade-hub.sh` | S0 skeleton: record version (N=3) → fetch/checkout → `uv sync --frozen` → reinstall → smoke; rollback on fail |
| `rollback-hub.sh` | S0 skeleton: checkout prior SHA + frozen sync + reinstall |
| `_hub_common.sh` | Shared helpers (bind/user validation, drop-in archive, version records) |
| `smoke-hub.sh` | `curl` `/api/health` |
| `octop-hub.service.in` | Unit template (`OCTOP_HOME`, bind host/port, User/Group) |
| `90-octop.conf.in` | Sole high-priority ExecStart override drop-in (0027 DEC-S01) |
| `octop-hub.octop.service.example` | Preferred non-root (`User=octop`, `127.0.0.1`) |
| `octop-hub.ubuntu.service.example` | Transition non-root (`User=ubuntu`) |
| `octop-hub.root.service.example` | **Bootstrap-only** root (requires `--allow-root`) |
| `ssh-ufw-checklist.md` | SSH / ufw / access-log acceptance checklist (AC-S04) |

## Production defaults (0027)

- **Bind**: `127.0.0.1` (topology A + Tunnel/reverse-proxy). Public bind (`0.0.0.0`) requires `--allow-public-bind`.
- **User**: non-root (`octop` preferred, `ubuntu` transition). Root requires `--allow-root`.
- **Truth source**: `/etc/systemd/system/octop-hub.service` + `…/octop-hub.service.d/90-octop.conf` only.
- **Runtime**: prefer `uv sync --frozen`; do not hand-edit `.venv`/site-packages in production.
- **Data**: `OCTOP_HOME=~/OctopData`; upgrade/rollback must not wipe the data plane.

Never commit Deploy Keys / tokens / passwords.
