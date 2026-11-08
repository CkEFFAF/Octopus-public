# Dashboard plugins

`marketplace.py` owns the trusted shared catalog, personal installations, private configuration and Go quota retrieval. `models.py` defines public typed contracts. The HTTP adapter is `api/routers/plugin_market.py`; the UI is `dashboard/src/pages/Plugins/`. Usage and API documentation lives in `docs/dashboard-plugin-market.md`.

Keep dashboard plugins distinct from executable server tool plugins in `infra/agents/plugins/`. Browsing and personal installation require only an authenticated account; uploading or managing executable server plugins retains the existing administrator permission.

Always derive the owner ID from the authenticated request. Installation, configuration and snapshot keys use `dashboard_plugins.user.<id>.`; never introduce a request parameter that selects another account. Use the existing settings and secrets repositories through `SharedServices`.

One plugin record holds its installation, encrypted configuration and quota snapshot. Updates must use `SettingsRepo.compare_and_set` against the exact previously read record. Uninstall deletes the entire record; do not retry a stale write by merging an old credential into a new record.

Encrypt keys with the existing credential crypto helper. Public models expose only `key_configured`, never a key or ciphertext. Do not discover credentials from server environment variables or host CLI login files. The Go quota client sends credentials only to the fixed official HTTPS endpoint and must not follow redirects or return upstream error bodies.

Preserve absent or invalid quotas as unknown, separately from a real zero. Retain the last successful data on upstream failure and label it stale. Do not infer subscription expiry from the monthly reset; the current expiry source is explicitly manual. Frontend requests and snapshots must be bound to their account so a late response after a user switch cannot display another user's data.

DeepSeek phases use Beijing dates, weekends and the explicitly maintained holiday table. Future years without holiday data must remain visibly marked as incomplete. Display other timestamps in the server timezone. Update phase boundaries and their tests together.

From the repository root, run `uv run pytest tests/unit/test_plugin_price_clock.py tests/integration/test_dashboard_plugin_market.py -q`. Frontend account and permission tests live beside the UI; use `npx vitest run src/pages/Plugins` from `dashboard/`.

_Drafted by /sync from the introducing change, worth a quick human pass._
