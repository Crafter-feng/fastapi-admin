from fastapi import Depends, HTTPException
from starlette.requests import Request
from starlette.responses import RedirectResponse
from starlette.status import HTTP_303_SEE_OTHER, HTTP_404_NOT_FOUND

from examples.models import Config
from fastapi_admin.app import app
from fastapi_admin.depends import get_resources, get_current_user
from fastapi_admin.template import templates
from fastapi_admin.i18n import _


@app.get("/")
async def home(
    request: Request,
    resources=Depends(get_resources),
    admin=Depends(get_current_user),
):
    return templates.TemplateResponse(
        "dashboard.html",
        context={
            "request": request,
            "resources": resources,
            "resource_label": _("Dashboard"),
            "page_pre_title": _("overview"),
            "page_title": _("Dashboard"),
        },
    )


@app.put("/config/switch_status/{config_id}")
async def switch_config_status(request: Request, config_id: int):
    config = await Config.get_or_none(pk=config_id)
    if not config:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND)
    config.status = not config.status
    await config.save(update_fields=["status"])
    return RedirectResponse(url=request.headers.get("referer"), status_code=HTTP_303_SEE_OTHER)
