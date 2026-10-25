# Configuration ownership and provider isolation

This is the implementation contract for spec `0011`, revision `2026-10-12.3`.

| Configuration | Owner and execution location |
| --- | --- |
| Enabled providers, API keys, default model, Codex OAuth | Account on the management instance. Equal provider names in different accounts are independent. |
| Provider preset catalog | Read-only data from `octop-harness`; enabling a preset creates an account-owned instance. |
| ACP command, arguments, environment, enabled state | One runner definition per account on the management instance. Each expert only stores its ACP tool switch. |
| Expert device binding | Account/expert record on the management instance; the process runs on the selected device. |
| Session execution selection and frozen run target | Account/expert/thread on the management instance. Explicit session selection takes precedence over the expert default, then the account default; existing runs and interactive tabs retain their original context. |
| Device trust, native OS identity and project files | Trust policy belongs to the enrolled controller/account/device relationship. Owner mode uses the device OS user's access; the starting working directory is not a shared-folder boundary. |
| Expert internal storage | AgentStore on the configured expert storage backend; project target changes do not relocate its credentials, memory or checkpoints. |
| CLI installation, CLI login, Gateway tokens for remote runners | Executing device. The management instance does not distribute these credentials. |
| Device connection credentials | Device state, limited to connection/authentication. It must not contain account provider keys or management-side runner environment. |

An expert, including a shared expert, uses **its owner's providers**. A caller's
own providers are not substituted. Model references keep the existing
`provider/model` spelling, but resolution and caches stay within that owner.
An expert without an owner cannot borrow credentials from another account.

Harness currently shares plugin contexts across agents. Until it provides an
account-scoped plugin context, Octopus blocks plugin `ctx.model_factory` and
`ctx.get_model_access()` for every account. Plugins that do not use this API
continue to work. This compatibility guard also covers internal agent rebuilds;
it prevents the last-created agent's credentials from leaking through a shared
context. It is not a sandbox for arbitrary installed Python plugin code.

`/api/providers` is the signed-in user's configuration surface. The explicit
`/api/admin/providers` surface retains the project's delegated administration
policy: administrators and users granted the `providers` management permission
can manage other accounts' providers. That permission is a privileged credential
administration capability; ordinary provider CRUD does not require it.

Delegated user administration does not permit controlling administrator accounts
or accounts with permissions outside the actor's own grants. User and role
writes enforce this boundary before mutation. Delegates can read and revoke only
their own invitations within their current authority. See
`docs/octopus/multiuser-beta-readiness.md` for the implemented checks and the
remaining beta-readiness work.

The existing instance-wide knowledge embedding/OCR configuration remains an
administrator-selected service. Its internal lookup is explicitly privileged;
account-facing selectors and updates still validate account ownership. This
change does not turn that service into separate per-account indexes.

## Upgrading existing data

Migration `025` preserves provider IDs, keys, model definitions and enabled
states. It replaces global name uniqueness with `UNIQUE(user_id, name)` and
requires an existing owner with a foreign key. The legacy active-model setting
moves to the same account. Legacy Codex OAuth is moved only to that recorded
owner's token directory.

An empty instance needs no owner. For an existing single-user instance, that
account is selected automatically. For multiple historical accounts, choose
the account that owns the old credentials and set `PRIMARY_OWNER_USER_ID` to its
numeric database ID before starting the upgraded management service. Invalid
IDs or ambiguous ownership stop migration before assigning keys. This is safer
than guessing from account creation order or an administrator's role.

Back up the database and authentication files before upgrading. After a
successful migration, restart the service normally. Rolling back to older code
requires restoring the pre-migration backup; the old schema cannot represent
same-name providers owned by multiple users.

## ACP credential boundary

Remote `acp.open` sends the runner command/arguments plus its validated execution
context and native working directory; the legacy adapter also retains `root_id`.
It sends no management runner environment. The child inherits the **device process
environment**. Owner mode uses the frozen context's native working directory;
restricted clients retain writable shared-root validation. For remote
OpenClaw, configure the Gateway token on that device or use a device-local
`--token-file`; putting it in the Dashboard environment applies only when the
management host executes the runner locally. Never put the token itself in
command-line arguments.

Hermes, Grok Build and OpenClaw presets start disabled, remain editable and
cannot be deleted. Grok Build has no default `--always-approve` argument.
Actual CLI authentication and an OpenClaw Gateway are separate prerequisites.

## Review checklist

- Provider SQL lookups and mutations require an owner; cross-account methods
  are explicitly named and limited to authorized administration/system use.
- User-facing catalogs and active-model selections do not expose other
  accounts' credentials or substitute the caller for a shared expert's owner.
- Agent model factories, caches, provider reloads and stale-model pin cleanup
  remain within the owner, even when provider names match.
- Runner settings remain user-scoped; expert tool switches remain expert-scoped. Request-scoped target resolution must not mutate another thread's ACP service or fall back to management execution when its selected device is unavailable.
- Remote runner payloads exclude hub environment and device state excludes hub
  API keys. Current grants and frozen context are checked before execution; shared-root checks apply to the restricted compatibility adapter.
- Built-in defaults contain no credential arguments or automatic-approval flag.
- The model catalog remains in the harness source repository. An installed
  package or portable bundle is not a source-of-truth edit target.

Verification results and outstanding acceptance items are recorded alongside
the spec in `docs/specs/0011-gpt-handoff.md`.
