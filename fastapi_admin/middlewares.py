from typing import Callable

from starlette.requests import Request
from starlette.responses import HTMLResponse
from starlette.status import HTTP_503_SERVICE_UNAVAILABLE

from fastapi_admin import i18n
from fastapi_admin.i18n import _
from fastapi_admin.template import templates


async def language_processor(request: Request, call_next: Callable):
    locale = request.query_params.get("language")
    if not locale:
        locale = request.cookies.get("language")
        if not locale:
            accept_language = request.headers.get("Accept-Language")
            if accept_language:
                locale = accept_language.split(",")[0].replace("-", "_")
            else:
                locale = None
    i18n.set_locale(locale)
    response = await call_next(request)
    if locale:
        response.set_cookie(key="language", value=locale)
    return response


async def maintenance_middleware(request: Request, call_next):
    """
    Maintenance mode middleware
    """
    # 如果应用不处于维护模式，正常处理请求
    if not request.app.maintenance:
        return await call_next(request)
    
    # 如果请求是静态资源，正常处理
    if '/static/' in request.url.path:
        return await call_next(request)
    
    # 返回维护模式页面
    return templates.TemplateResponse(
        "maintenance.html",
        context={"request": request},
        status_code=HTTP_503_SERVICE_UNAVAILABLE,
    )
