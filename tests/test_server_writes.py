"""Server-level write tool behavior: kill switch and credential errors."""

from connectwise_mcp.server import cw_patch, cw_post, cw_put


async def test_write_tools_refuse_when_writes_disabled(monkeypatch):
    monkeypatch.setenv("CW_MCP_ALLOW_WRITES", "false")
    out = await cw_post("/service/tickets", body={"summary": "x"})
    assert "disabled" in out["error"]
    out = await cw_put("/service/tickets/{id}", body={}, path_params={"id": 1})
    assert "disabled" in out["error"]
    out = await cw_patch("/service/tickets/{id}", body=[], path_params={"id": 1})
    assert "disabled" in out["error"]


async def test_write_tools_report_missing_credentials(monkeypatch):
    monkeypatch.setenv("CW_MCP_ALLOW_WRITES", "true")
    for var in ("CW_COMPANY_ID", "CW_PUBLIC_KEY", "CW_PRIVATE_KEY", "CW_CLIENT_ID"):
        monkeypatch.delenv(var, raising=False)
    out = await cw_post("/service/tickets", body={"summary": "x"})
    assert "Missing ConnectWise credentials" in out["error"]
