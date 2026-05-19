from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from voulezvous.acquisition.api import (
    bridge as acq_bridge,
)
from voulezvous.acquisition.api import (
    candidates as acq_candidates,
)
from voulezvous.acquisition.api import (
    discovery as acq_discovery,
)
from voulezvous.acquisition.api import (
    domain_policies as acq_domain_policies,
)
from voulezvous.acquisition.api import (
    enrichment as acq_enrichment,
)
from voulezvous.acquisition.api import (
    keywords as acq_keywords,
)
from voulezvous.acquisition.api import (
    lineups as acq_lineups,
)
from voulezvous.acquisition.api import (
    media_ir as acq_media_ir,
)
from voulezvous.acquisition.api import (
    reports as acq_reports,
)
from voulezvous.api.routers import assets, health, plans, prep, reports, stream
from voulezvous.config import settings
from voulezvous.logging_config import setup_logging

setup_logging()

app = FastAPI(title="Voulezvous Streaming Engine", version="0.2.0")

# Static files and templates
_pkg_dir = Path(__file__).resolve().parent.parent
app.mount("/static", StaticFiles(directory=str(_pkg_dir / "static")), name="static")
templates = Jinja2Templates(directory=str(_pkg_dir / "templates"))

# Mount HLS spool dir for live segment serving
settings.ensure_spool_dirs()
app.mount("/hls", StaticFiles(directory=str(settings.spool_hls)), name="hls")

# Existing MVP routers
app.include_router(health.router)
app.include_router(assets.router)
app.include_router(plans.router)
app.include_router(prep.router)
app.include_router(stream.router)
app.include_router(reports.router)

# Acquisition subsystem routers
app.include_router(acq_domain_policies.router)
app.include_router(acq_keywords.router)
app.include_router(acq_discovery.router)
app.include_router(acq_candidates.router)
app.include_router(acq_enrichment.router)
app.include_router(acq_lineups.router)
app.include_router(acq_media_ir.router)
app.include_router(acq_reports.router, prefix="/acq")
app.include_router(acq_bridge.router)


@app.get("/", response_class=HTMLResponse)
async def client_page(request: Request):
    return templates.TemplateResponse(request, "client.html")


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    return templates.TemplateResponse(request, "admin.html")
