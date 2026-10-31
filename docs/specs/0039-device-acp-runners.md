# 0039 Device ACP runners

**Status**: Accepted
**Date**: 2026-10-30
**Authorized by**: user requested device scoped adaptation and deployment.

## Summary
Expert ACP permission remains per expert. Runner commands and arguments can be overridden per owned device. New calls use the frozen execution target, while existing sessions remain on their original target.

## Requirements
1. Device settings cannot cross account or device boundaries. Legacy account settings remain the fallback.
2. Device overrides include enabled, command, args, trusted and parser settings. Credentials and environment remain on the executing device, never copied from the hub.
3. ACP UI selects account templates or an owned device, with reset and non executing startup checks.
4. Tool listing and new calls resolve against the current target. Errors become tool results rather than terminating chat. Existing sessions retain their target and configuration.
5. Expert self management can change its ACP tool permission through the existing tool switch after user authorization. It must honor Ask/Plan, ownership and team restrictions.
6. Missing executable, missing adapter, authentication/subscription and timeout are reported distinctly without returning secrets or ACP transcripts in device journals.

## Decision
Reuse settings storage with owner and device scoped keys, avoiding a schema change. Account templates are inherited, device definitions replace individual template entries. No environment fields are accepted for device overrides. Use existing ACP components and design tokens with a scope selector. The selected device requires existing acp_run permission for checks and calls.

## Build plan
Implement store and owner checked API, then request scoped ACP wrapper and error handling. Add configuration UI, process diagnostics and client startup checks. Test device/account isolation, enabled states, session affinity, old clients and real Windows runner paths. Build dashboard and deploy a new isolated source/venv directory with health checked rollback, retaining OctopData and device identities.

## Consequences
Old clients need an update for startup checks, but regular calls retain the existing transport. Installing or authenticating external programs is still a device operation; no model subscription is created by enabling a runner.

## Rationale
An account wide absolute Windows command cannot serve Linux or macOS execution targets. Separate device configuration solves this while preserving existing templates.

## Adapter compatibility
Codex legacy unversioned npx defaults are upgraded to @agentclientprotocol/codex-acp. Explicit custom commands and version pins remain unchanged. Upstream migration: https://github.com/zed-industries/codex-acp and maintained adapter: https://github.com/agentclientprotocol/codex-acp.
