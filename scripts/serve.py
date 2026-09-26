"""Start the app at http://127.0.0.1:8000 (works offline; basemap falls back to plain dark without internet)."""
import sys
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if __name__ == "__main__":
    uvicorn.run("egress.api:app", host="127.0.0.1", port=8000, log_level="info")
