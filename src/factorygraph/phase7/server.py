"""Single-worker local API entry point."""

import logging
import os

import uvicorn

logging.basicConfig(level=logging.INFO, format="%(message)s")

if __name__ == "__main__":
    container = os.environ.get("FG7_CONTAINER") == "1"
    uvicorn.run(
        "factorygraph.phase7.api:app",
        host="0.0.0.0" if container else "127.0.0.1",
        port=18080,
        workers=1,
        access_log=False,
        proxy_headers=False,
    )
