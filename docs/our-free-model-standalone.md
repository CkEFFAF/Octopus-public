# Our Free Model provider

Octop integrates the standalone OpenAI-compatible server from
[dsh-our-free-model](https://github.com/Ebony-Vinyl/dsh-our-free-model), rather than
loading its DSH plugin into Octop. The audited deployment uses upstream commit
`482500f79ecbf92f581e1d2e98f170701a743083` and official Node.js 22.23.4 LTS.
Verify the Node distribution against nodejs.org's published SHA256 manifest.

Run `packages/standalone/cli.mjs --port 18900 --data-dir <private-data-dir> --no-lan`
from the pinned source tree. Keep the service on loopback, supervise it with
systemd, use a private data directory and log (0700 / 0600), and restart on failure.
Do not expose its management API or log its one-time management login URL.
The standalone service manages its own upstream model refresh.

In Models settings add the **Our Free Model** preset, retain
`http://127.0.0.1:18900/v1` for a colocated service, and use the standalone server's
own forwarding key. Fetch its model list, then test and enable the models needed.
Keys remain account-owned. No DSH credentials, EAC host bindings or login
restrictions are reused or bypassed.

Fictional-text smoke tests from the deployment host on 2026-10-23 passed chat for
`kilo-auto/free`, `nvidia/nemotron-3.5-lightning:free` and
`poolside/laguna-s-2.1:free`. The latter also passed Octop's actual title and
overview JSON-schema generation path. Availability and free quotas can change;
refresh and test before changing models. Never fall back silently to paid models.

Public preset metadata refreshes from Models.dev and OpenCode Go's official
catalog on the first scheduled check after startup (within one minute), then
daily. Models settings exposes manual refresh and source freshness. Failed
refreshes retain the last successful disk snapshot and retry after an hour.
Saved explicit model settings and custom provider endpoints remain authoritative.

Before replacing the supervised standalone service, preserve its private data
and forwarding key. Before an Octop release, back up Octop data and service
configuration separately. Rolling back Octop does not require deleting the
standalone provider's data.
