"""Launch DeclaratorLM with the English UI (index.en.html)."""
from __future__ import annotations

import os
import sys

# Must be set before webview_app resolves the frontend path.
os.environ["DECLARATOR_UI_LANG"] = "en"

import webview_app  # noqa: E402

if __name__ == "__main__":
    sys.exit(webview_app.main() or 0)
