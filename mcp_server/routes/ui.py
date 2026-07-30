"""
mcp_server/routes/ui.py — web UI page routes.

The UI is now a single-page application (Solver-MCPs). One shell template
(index.html) assembles self-contained Jinja2 component partials and loads its
behaviour from /static/app.js:

  GET /           -> index.html   single-page app shell
  GET /dashboard  -> index.html   same shell; serves legacy /dashboard#<job_id>
                                   deep links emitted by inline result cards so
                                   they resolve to the SPA instead of 404'ing.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
router = APIRouter(tags=["ui"])


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def index_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html")


@router.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
async def dashboard_page(request: Request) -> HTMLResponse:
    # Legacy deep-link target. The dashboard is folded into the SPA, so this
    # serves the same shell; the fragment (#<job_id>) is handled client-side.
    return templates.TemplateResponse(request, "index.html")
