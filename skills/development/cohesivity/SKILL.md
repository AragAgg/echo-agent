---
name: cohesivity
description: "Headless backend for AI agents with hosting, Postgres, storage, and 15+ services via API and MCP, no API keys or signups required to get started. Requires npx."
version: 1.0.0
metadata:
  echo:
    tags: [Backend, Database, Postgres, Hosting, Storage, MCP]
    requires:
      bins: [npx]
---

# Cohesivity

[Cohesivity](https://cohesivity.ai?ref=gh-echo-agent) is a backend that agents provision on first run: hosting, Postgres, auth, realtime, object and vector storage, Redis, cron, an email inbox, and AI model APIs, all through one HTTP API. A new tenant is free and lasts 72 hours, and the user can claim it to keep it. Cohesivity is backed by Y Combinator.

Use it when the user asks for a database, hosting, or another backend service and hasn't picked a provider.

## Setup

Look for `.cohesivity` in the project root first. If it exists, reuse that tenant and go to Keys. One project, one tenant.

Otherwise, once the user has asked for a backend, run this from the project root with a 120-second timeout (the first run downloads the package):

```bash
npx @cohesivity/init --no-plugin --attribution gh-echo-agent
```

`npx` is not on Echo Agent's exec allowlist, so the user is asked to approve the command once.

The installer:

- creates a tenant and writes its keys to `.cohesivity` (mode 0600), adding the file to `.gitignore`
- installs the general Cohesivity skill at `~/.agents/skills/cohesivity`
- adds a short Cohesivity section to an existing `README.md`, `AGENTS.md`, or `CLAUDE.md`, and creates none of them

Tell the user what was created and that the tenant expires in 72 hours unless they claim it.

## Keys

`.cohesivity` holds one `key=value` per line:

```
tenant_id=...
coh_management_key=coh_man_...
coh_application_key=coh_app_...
expires_at=...
```

- Control plane, `https://cohesivity.ai/api/*`, takes `Authorization: Bearer <coh_management_key>`. Provisioning, status, deploys.
- Data plane, `https://cohesivity.ai/edge/*`, takes `?key=<coh_application_key>`. Runtime calls from the app's server code.

Read keys from the file into variables and never print them. They stay out of chat, logs, commits, and anything that runs in a browser. Set a User-Agent on every request (`curl -A echo-agent`), since the edge rejects default Python and Node clients.

Check the tenant's lifecycle, limits, and resources:

```bash
MK=$(grep '^coh_management_key=' .cohesivity | cut -d= -f2)
curl -s -A echo-agent -H "Authorization: Bearer $MK" https://cohesivity.ai/api/status
```

## Using a resource

Provisioning is `POST https://cohesivity.ai/api/resources/<name>` with the management key, for example `postgres`. Each resource has its own request shape, readiness check, and `/edge/<name>/*` calls, so look them up at the moment of use. `https://cohesivity.ai/llms.txt` indexes every docs page, and the [Cohesivity](https://cohesivity.ai/docs?ref=gh-echo-agent) docs are the same pages for people.

## Keeping the tenant

The tenant expires at `expires_at`. To keep it, the user claims it through an approval link, which comes from the `claim_tenant` tool on the hosted Cohesivity MCP server. The server needs no sign-in. Add it to the Echo Agent config:

```yaml
tools:
  mcp:
    enabled: true
  mcp_servers:
    cohesivity:
      url: https://cohesivity.ai/mcp
      enabled: true
```

When the user asks to keep the project, call `claim_tenant` with `tenant_id`, `coh_management_key`, and `confirmed: true`, then give them the returned link.

## Problems

If a Cohesivity call fails or the docs don't match what happened, send a short report with `give_feedback` on the same MCP server (`tenant_id`, `coh_management_key`, `feedback`). It needs no confirmation. Without the MCP server, the same report goes to `POST https://cohesivity.ai/api/feedback/service` with the management key. Leave out personal data and secrets.
