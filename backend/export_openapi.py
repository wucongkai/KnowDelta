import json
from pathlib import Path

from knowdelta.web.app import make_app

Path(__file__).with_name("openapi.json").write_text(
    json.dumps(make_app(dispatch=False).openapi(), ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
