from mcp.server.fastmcp import FastMCP

from .config import Settings
from .storage import Storage
from .tools import read_tool

mcp = FastMCP('industrial-evidence')
storage = Storage(Settings())


@mcp.tool()
def query_metrics(device_id: str) -> dict:
    """Read the selected device's latest telemetry and 24-hour trend summary."""
    return read_tool(storage, 'query_metrics', device_id)


@mcp.tool()
def query_alerts(device_id: str) -> dict:
    """Read alerts and acknowledgement status for one device."""
    return read_tool(storage, 'query_alerts', device_id)


@mcp.tool()
def query_logs(device_id: str) -> dict:
    """Read recent operational logs for one device."""
    return read_tool(storage, 'query_logs', device_id)


if __name__ == '__main__':
    mcp.run(transport='stdio')
