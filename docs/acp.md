# ACP (Agent Client Protocol)

Octop integrates [ACP](https://agentclientprotocol.com/) in two directions:

| Direction | ACP server | ACP client | Typical use |
|-----------|------------|------------|-------------|
| **Inbound** | Octop (`octop acp`) | Zed, OpenCode, … | External IDE drives your Octop agent |
| **Outbound** | OpenCode, CodeBuddy, … | Octop (`acp_runner` tool) | Octop agent delegates coding tasks |

Both use **stdio** JSON-RPC today. Octop does not expose an HTTP ACP endpoint.

---

## Dashboard: outbound runners

Open **ACP** in the sidebar (`/acp`).

### What is global vs per-agent

| Setting | Scope | Stored in |
|---------|--------|-----------|
| Runner cards (command, args, enabled, …) | **Per user** — shared by all your agents | `settings` table (`acp_runners:user:{id}`) |
| **Enable acp_runner tool** toggle | **Per agent** | Agent `config_json.acp.tool_enabled` |

Legacy per-agent `config_json.acp.runners` is migrated to the user-global store on first load.

### Built-in runners

| ID | Command | Args |
|----|---------|------|
| `opencode` | `opencode` | `acp` |
| `codebuddy` | `codebuddy` | `--acp` |
| `claude_code` | `npx` | `-y`, `@zed-industries/claude-agent-acp` |
| `codex` | `npx` | `-y`, `@zed-industries/codex-acp` |
| `kimi_code` | `kimi` | `acp` |
| `cursor_cli` | `agent` | `acp` |
| `pi` | `npx` | `-y`, `pi-acp` |
| `hermes` | `hermes` | `acp` |
| `grok_build` | `grok` | `agent`, `stdio` |
| `openclaw` | `openclaw` | `acp` |

All built-in runners start disabled and cannot be deleted; their command, args and env can be edited. Custom runners can be added from **Add runner**.

Install and authenticate the CLI on the machine that will execute it. An expert with a `device_binding` starts ACP on that device, using its shared directory and local CLI login; an unbound expert runs on the management host. Ensure the CLI is on that process's `PATH`, or configure an absolute `command` valid on the execution machine. See [device ACP](octopus/device-acp.md).

Runner definitions and enablement belong to the Octop account; CLI installations, CLI logins and running processes belong to the execution machine. The agent's tool toggle and device binding are independent of the desktop viewer's target selection.

### Credentials for local and remote execution

For local execution on the hub, runner `env` overlays the process environment. Remote `acp.open` sends only `root_id`, `runner`, `command` and `args`; it never forwards hub runner `env` or provider API keys. Set remote CLI credentials on the device itself.

OpenClaw is an ACP bridge to an already running Gateway. Use `OPENCLAW_GATEWAY_TOKEN` in the execution process environment, or `--token-file` with a file on that machine; never put the token value in command-line args. Setting a token in the Dashboard runner env works only for a local hub process. The preset contains neither a token nor `--token`.

Grok Build uses `grok agent stdio`. The preset omits `--always-approve`, preserving external permission requests and the chat `action=respond` flow.

### Enable delegation in chat

1. Configure and enable at least one runner on `/acp`.
2. Switch agent in the top bar and turn on **Enable acp_runner tool** for that agent.
3. In chat, ask the agent to use `acp_runner`, or let it delegate when appropriate.

### `acp_runner` tool workflow

```text
action=list              → enabled runners and session state
action=start             → new session: runner + message (+ optional cwd)
action=message           → continue session
action=respond           → answer [permission_required] with exact option id
action=status            → session open / waiting for permission
action=close             → end session
```

Example user message:

```text
Use acp_runner: action=start, runner=opencode, message=find the README in the workspace and summarize it.
```

Permission prompts from the external agent appear in chat; pick an option or instruct the agent to call `action=respond` with the option id.

After changing global runners, Octop reloads your agents automatically. Changing only `tool_enabled` reloads that agent.

---

## CLI: inbound — expose Octop as an ACP server

Let external clients (e.g. Zed) use an Octop agent as their coding agent:

```bash
octop acp --agent main
```

| Option | Description |
|--------|-------------|
| `--agent ID` | Agent to expose (default: CLI `default_agent` or first agent) |
| `--debug` | Log to stderr |

This starts a **standalone** `OctopServer` (reads `~/.octop`), boots the agent, and speaks ACP on stdin/stdout. It does **not** require `octop run` to be running; it is a separate process.

Pin the default agent for convenience:

```bash
octop user login --username you
# set default_agent in ~/.octop/cli_state.json, or:
octop --agent main acp
```

### Zed example

`~/.config/zed/settings.json`:

```json
{
  "agent_servers": {
    "Octop": {
      "command": "octop",
      "args": ["acp", "--agent", "main"],
      "env": {}
    }
  }
}
```

From a dev checkout:

```json
{
  "agent_servers": {
    "Octop": {
      "command": "uv",
      "args": ["run", "octop", "acp", "--agent", "main"],
      "env": {}
    }
  }
}
```

Create an agent thread in Zed and prompt as usual. Sessions map to `thread_id`; the agent workspace remains under `~/.octop/agents/<agent_id>/`.

---

## HTTP API

Interactive docs: `/api/docs` (tag **agents**).

### Global runners (current user)

| Method | Path | Body |
|--------|------|------|
| `GET` | `/api/acp` | — |
| `PUT` | `/api/acp` | `{ "runners": { "<id>": { … } } }` |
| `GET` | `/api/acp/{runner_name}` | — |
| `PUT` | `/api/acp/{runner_name}` | runner object |
| `DELETE` | `/api/acp/{runner_name}` | custom runners only |

### Per-agent tool toggle

| Method | Path | Body |
|--------|------|------|
| `GET` | `/api/agents/{agent_id}/acp` | returns global `runners` + agent `tool_enabled` |
| `PUT` | `/api/agents/{agent_id}/acp` | `{ "tool_enabled": bool, "runners": …? }` — `runners` optional, updates global |
| `PUT` | `/api/agents/{agent_id}/acp/tool` | `{ "tool_enabled": bool }` only |

Runner shape:

```json
{
  "enabled": true,
  "command": "opencode",
  "args": ["acp"],
  "env": {},
  "trusted": true,
  "tool_parse_mode": "update_detail",
  "stdio_buffer_limit_bytes": 52428800
}
```

---

## Prerequisites

- **octop-harness `[acp]` extra** — pulls in `agent-client-protocol` (included in the Octop wheel dependency on octop-harness).
- **Outbound:** install external CLIs on the bound device, or on the management host for an unbound expert.
- **Inbound:** agent must start successfully (provider + model configured).

---

## Troubleshooting

| Symptom | Likely cause |
|---------|----------------|
| Runner missing on some agents | Upgrade to user-global runners; open `/acp` once or `GET /api/acp` to trigger migration |
| `acp_runner` lists runner but start fails with “Unknown runner” | Restart `octop run` after adding a custom runner (ACP service cache is process-wide) |
| External runner returns no text | Check CLI auth/quota (e.g. `codebuddy auth status`) |
| `octop acp` fails immediately | Agent not running or invalid `--agent`; create/start agent in dashboard first |
| Command not found | Use absolute path in runner `command` if `PATH` for the server process differs from your shell |
| Kimi Code fails to start | Install [kimi-code](https://github.com/MoonshotAI/kimi-code) and run `kimi` login on the host |
| Cursor CLI fails to start | Install Cursor CLI; run `agent login` or set `CURSOR_API_KEY` |
| Pi runner fails to start | Requires Node.js for `npx -y pi-acp`; ensure network access for first npm fetch |
| Hermes fails to start | Install Hermes and its ACP extra on the execution machine; run `hermes acp --check`, then configure its model/login with `hermes model` |
| Grok Build fails to start | Install Grok Build CLI and authenticate on the execution machine, or set `XAI_API_KEY` there; verify `grok agent stdio` is supported by that version |
| OpenClaw cannot connect | Verify its Gateway is running and reachable; configure the Gateway URL and a device-local env token or `--token-file` |
| Runner env works on hub but not on a remote device | Remote ACP deliberately does not forward hub env. Configure credentials on the bound device; check its client process environment and token-file path |

---

## Related

- Dashboard: `/acp`
- CLI: `octop acp --help`
- OpenAPI: `/api/docs`
- Harness implementation: `octop-harness` → `octop_harness.acp` (server + `acp_runner` tool)
- [Hermes ACP setup and dependency checks](https://hermes-agent.nousresearch.com/docs/user-guide/features/acp)
- [Grok Build ACP, installation and authentication](https://docs.x.ai/build/cli/headless-scripting)
- [OpenClaw ACP Gateway and token-file options](https://docs.openclaw.ai/cli/acp)

New runner launch commands checked against the official documentation on 2026-10-13. The presets do not install CLIs, authenticate accounts or provision an OpenClaw Gateway.
