# Performance inspection and bounded concurrency

The administrator-only `GET /api/admin/performance` returns process-local measurements. They reset on restart. Each duration retains at most 512 recent samples; `count` is the lifetime count, while mean, P50, P95 and maximum describe the retained samples. Empty durations and cache hit rates are null. No account, conversation, URL, path, prompt or credential labels are collected. Existing `/api/admin/metrics` is unchanged.

| Duration | Meaning |
| --- | --- |
| archive_flush | Time in the durable archive flush adapter, including no-op flushes |
| mcp_prepare | Preparing the selected turn's MCP tools |
| mcp_wait | Completed wait for shared tool admission |
| mcp_call | Tool invocation after admission and access validation, including failures |
| job_observation | One Job observation attempt after admission, including unavailable outcomes |
| first_text | Stream entry to first nonempty token or reasoning arrival, before archive forwarding; excludes earlier turn preparation |
| skill_refresh | Skill refresh at the model configuration boundary |
| event_loop_lag | Excess delay of a 50 ms sleep, sampled by a five-second system job |

Cache counters cover gateway schema reuse and skill manifest reuse. A schema hit still performs live visibility, account, selection and credential checks. Skill manifest reuse currently supports authoritative local `BackendWorkspace` filesystem storage. It reopens the file to check read access and reads a version including identity, size and change timestamps. Windows uses FileBasicInfo ChangeTime, not creation time. Unchanged parsed metadata is reused. Changed, deleted, replaced or unsupported sources are read again. Remote/materialized workspaces retain fresh reads because they do not expose an authoritative content-version contract.

Completed 1024-character archive text blocks use a bounded 1024-entry cache of their serialized value and digest. The cache does not assert database row presence; each document still maintains its own body references inside the transaction. Partial tails and rewrites retain normal encoding and garbage collection.

Device reconciliation selects due Jobs in rounds across frozen targets, rather than filling an entire batch from one server. There is one active observation per target and at most four globally. Transport/offline failures back off for 30, 60, 120, 240 and then at most 300 seconds, with at most 512 target entries. Backoff is process-local; a restart may probe immediately. Job-specific errors do not suppress other Jobs on the same target. Successful access resets backoff. No retry changes the frozen target or restarts a Job.

Custom HTTP MCP configurations can explicitly opt into independent parallel calls:

```json
{
  "servers": {
    "catalog": {
      "transport": "streamable_http",
      "url": "https://example.com/mcp",
      "max_concurrent_calls": 4
    }
  }
}
```

The default is one call. The accepted range is 1..8; stdio rejects values greater than one. Only configure parallel calls when the server's operations are safe to overlap. This field is Octop metadata and is removed before reaching the MCP SDK. Old and new cached tool generations share a gate, so accepted calls continue to occupy capacity after a limit reduction. Queued calls recheck live access; changed parallel policy invalidates old parallel wrappers. Synchronous callers inside an active asyncio loop must use `ainvoke`, so they cannot bypass admission.

Chat grouping uses bounded numeric copy-on-write ancestry to identify the changed suffix, including the preceding boundary. Unknown ancestry, history prepend and other unhinted operations use full grouping. This preserves existing grouping while avoiding full history scans for ordinary streaming replacements, without retaining old arrays through ancestry links.
