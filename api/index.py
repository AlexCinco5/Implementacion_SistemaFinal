import os
import sys
from urllib.parse import parse_qs, urlencode

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.main import app as fastapi_app

async def app(scope, receive, send):
    if scope["type"] == "http":
        scope = dict(scope)
        qs = parse_qs(scope.get("query_string", b"").decode("utf-8"))
        if "__path" in qs:
            nuevo_path = qs.pop("__path")[0]
            scope["path"] = nuevo_path
            scope["raw_path"] = nuevo_path.encode("utf-8")
            scope["query_string"] = urlencode(qs, doseq=True).encode("utf-8")
    await fastapi_app(scope, receive, send)