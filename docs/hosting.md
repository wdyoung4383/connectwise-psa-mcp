# Hosting the ConnectWise PSA MCP server (Render)

This deploys the **read-only** server to a public HTTPS URL. Clients connect
from Claude Code/Desktop and pass **their own** ConnectWise keys as headers — the
host stores no ConnectWise credentials. A per-customer **gateway token** gates
access.

## 1. Deploy to Render

1. Push this repo to GitHub (already done).
2. In the Render dashboard: **New → Blueprint**, point it at this repo. Render
   reads `render.yaml` and creates the `connectwise-psa-mcp` web service.
3. Set the secret env var **`CW_GATEWAY_TOKENS`** (see step 2 below) in the
   service's Environment settings. The service will not start without it
   (fail-closed).
4. Render builds the Docker image and gives you a URL like
   `https://connectwise-psa-mcp.onrender.com`. The MCP endpoint is that URL + `/mcp`.

> **Free plan sleeps when idle.** On `plan: free` the service spins down after
> inactivity, so the first request after a lull is slow (cold start) and an MCP
> client may time out connecting. For anything clients rely on, change
> `plan: free` to `plan: starter` in `render.yaml` for an always-on instance.

## 2. Mint and issue gateway tokens

For each client, mint a token **on your local machine** (not in CI — the command
prints a raw secret to stdout):

```bash
python scripts/new_gateway_token.py acme-msp
```

This prints a raw **token** (give it to the client over a secure channel) and its
**sha256 hash**. Add the hash to `CW_GATEWAY_TOKENS`, which is a JSON object
mapping `sha256(token) -> client-label`:

```json
{"<sha256-of-acme-token>": "acme-msp", "<sha256-of-globex-token>": "globex"}
```

Set that JSON as the `CW_GATEWAY_TOKENS` env var in Render. To **revoke** a
client, remove their entry and redeploy. The server stores only hashes, never
the raw tokens.

## 3. Verify

```bash
curl https://<your-app>.onrender.com/health        # -> {"status":"ok"}
curl -i https://<your-app>.onrender.com/mcp         # -> 401 (no gateway key)
```

Then connect a client (see `docs/connecting.md`, "Remote (hosted)" section) and
ask it to list the ConnectWise modules.

## Security notes

- TLS is managed by Render.
- Gateway tokens are stored only as sha256 hashes; raw tokens live with clients.
  Mint them locally — never run the mint script in CI/automation that captures
  stdout.
- ConnectWise credentials are pass-through only and are never stored server-side.
- Logs never contain credentials or the gateway key (see `logging_setup.redact`).
- Residual risk: client ConnectWise credentials transit the server's memory and
  TLS termination in flight (they are not persisted, but they are processed).
