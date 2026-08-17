from __future__ import annotations

import uvicorn

from lpr_cpe_demo.config import get_settings

if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run(
        "lpr_cpe_demo.mcp_server.app:app",
        host="0.0.0.0",
        port=settings.mcp_port,
        reload=False,
        log_level=settings.log_level.lower(),
    )
