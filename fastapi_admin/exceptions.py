from fastapi import HTTPException
from starlette.requests import Request
from starlette.status import HTTP_500_INTERNAL_SERVER_ERROR
from starlette.responses import RedirectResponse
from starlette.status import HTTP_303_SEE_OTHER

from fastapi_admin.template import templates


class ServerHTTPException(HTTPException):
    def __init__(self, error: str = None):
        super(ServerHTTPException, self).__init__(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR, detail=error
        )


class InvalidResource(ServerHTTPException):
    """
    raise when has invalid resource
    """


class NoSuchFieldFound(ServerHTTPException):
    """
    raise when no such field for the given
    """


class FileMaxSizeLimit(ServerHTTPException):
    """
    raise when the upload file exceeds the max size
    """


class FileExtNotAllowed(ServerHTTPException):
    """
    raise when the upload file ext not allowed
    """


async def server_error_exception(request: Request, exc: HTTPException):
    return templates.TemplateResponse(
        "errors/500.html",
        status_code=HTTP_500_INTERNAL_SERVER_ERROR,
        context={"request": request},
    )


async def not_found_error_exception(request: Request, exc: HTTPException):
    return templates.TemplateResponse(
        "errors/404.html", status_code=exc.status_code, context={"request": request}
    )


async def forbidden_error_exception(request: Request, exc: HTTPException):
    return templates.TemplateResponse(
        "errors/403.html", status_code=exc.status_code, context={"request": request}
    )


async def unauthorized_error_exception(request: Request, exc: HTTPException):
    from tortoise.exceptions import OperationalError
    
    # 尝试检查是否有用户
    try:
        # 动态导入以避免循环引用
        from fastapi_admin.models import AbstractAdmin
        
        # 获取管理员模型类
        admin_model = request.app.login_provider.admin_model
        
        # 检查是否有任何用户
        has_users = await admin_model.all().limit(1).exists()
        
        if not has_users:
            # 如果没有用户，重定向到初始化页面
            return RedirectResponse(
                url=request.app.admin_path + "/init", 
                status_code=HTTP_303_SEE_OTHER
            )
    except (ImportError, AttributeError, OperationalError):
        # 如果出错，默认行为是重定向到登录页
        pass
        
    # 默认重定向到登录页
    return RedirectResponse(
        url=request.app.admin_path + "/login", 
        status_code=HTTP_303_SEE_OTHER
    )
