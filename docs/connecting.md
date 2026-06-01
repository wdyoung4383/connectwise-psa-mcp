# Connecting the ConnectWise PSA MCP server (local stdio)

This guide wires the **read-only** server into an MCP client over stdio, using
your ConnectWise credentials as `CW_*` environment variables. Nothing is stored
server-side — the process reads the env vars per request.

## 1. Install

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate
pip install -e ".[dev]"
```

## 2. Get your ConnectWise API keys

In ConnectWise Manage: **System → Members → API Members** (create a dedicated
API member), then **API Keys** to generate a public/private key pair. You also
need your **company id**, your **clientId** GUID (registered in the ConnectWise
Developer Network), and your **region** (`na`, `eu`, `au`, `aus`, `za`) or a
self-hosted host.

## 3. Validate the connection (smoke test)

Copy `.env.example` to `.env`, fill in the five `CW_*` values, then run:

```bash
python scripts/smoke_live.py
```

Expected output ends with `OK: /system/members returned 1 record(s)`. If you see
`authentication failed`, re-check the keys, company id, clientId, and region.

## 4. Connect Claude Desktop

Edit `claude_desktop_config.json` (Settings → Developer → Edit Config) and add an
entry. Use the **absolute path** to the Python interpreter in your `.venv`:

```json
{
  "mcpServers": {
    "connectwise-psa": {
      "command": "C:\\Users\\wdyou\\connectwisemcp\\connectwise-mcp\\.venv\\Scripts\\python.exe",
      "args": ["-m", "connectwise_mcp"],
      "env": {
        "CW_MCP_TRANSPORT": "stdio",
        "CW_COMPANY_ID": "your_company_id",
        "CW_PUBLIC_KEY": "your_public_key",
        "CW_PRIVATE_KEY": "your_private_key",
        "CW_CLIENT_ID": "your_client_id_guid",
        "CW_REGION": "na"
      }
    }
  }
}
```

Restart Claude Desktop. The `connectwise-psa` tools (`list_modules`,
`search_endpoints`, `describe_endpoint`, `cw_get`) should appear. Ask it to
"list the ConnectWise modules" to confirm.

## 5. Connect Claude Code

From the project directory:

```bash
claude mcp add connectwise-psa \
  --env CW_MCP_TRANSPORT=stdio \
  --env CW_COMPANY_ID=your_company_id \
  --env CW_PUBLIC_KEY=your_public_key \
  --env CW_PRIVATE_KEY=your_private_key \
  --env CW_CLIENT_ID=your_client_id_guid \
  --env CW_REGION=na \
  -- C:\\Users\\wdyou\\connectwisemcp\\connectwise-mcp\\.venv\\Scripts\\python.exe -m connectwise_mcp
```

Then run `claude mcp list` to confirm it's registered.

## Manual verification checklist

- [ ] `python scripts/smoke_live.py` prints `OK: /system/members returned ...`
- [ ] Client lists the four `connectwise-psa` tools
- [ ] Asking the client to read open service tickets returns real data
- [ ] No credentials appear in the server's log output
