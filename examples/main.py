import os
from contextlib import asynccontextmanager


from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import RedirectResponse
from starlette.staticfiles import StaticFiles
from starlette.status import (
    HTTP_401_UNAUTHORIZED,
    HTTP_403_FORBIDDEN,
    HTTP_404_NOT_FOUND,
    HTTP_500_INTERNAL_SERVER_ERROR,
)
from tortoise.contrib.fastapi import register_tortoise
from tortoise import Tortoise

from examples import settings
from examples.constants import BASE_DIR
from examples.models import Admin, Role, Permission, Resource, AdminLog
from examples.providers import LoginProvider
from fastapi_admin.app import app as admin_app
from fastapi_admin.exceptions import (
    forbidden_error_exception,
    not_found_error_exception,
    server_error_exception,
    unauthorized_error_exception,
)
from fastapi_admin.utils.storage import MemoryStorage
from fastapi_admin.providers.permission import PermissionProvider
from fastapi_admin.providers.admin_log import AdminLogProvider
from fastapi_admin.utils.logger import logger, logger_configure

# 配置日志
logger_configure(
    log_level=os.environ.get("LOG_LEVEL", "DEBUG"),
    log_path=os.path.join(BASE_DIR, "logs")
)

# 自定义权限获取函数
async def get_admin_permissions(admin):
    """获取管理员权限"""
    return await admin.get_permissions()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 确保数据库在此处初始化，admin_app配置前
    await Tortoise.init(
        config={
            "connections": {"default": settings.DATABASE_URL},
            "apps": {
                "models": {
                    "models": ["examples.models"],
                    "default_connection": "default",
                }
            },
        }
    )
    
    # 创建数据库表
    logger.debug("Creating schema...")
    await Tortoise.generate_schemas(safe=True)
    logger.debug("Schema created successfully")
    
    storage = MemoryStorage()
    await admin_app.configure(
        logo_url="https://preview.tabler.io/static/logo-white.svg",
        template_folders=[os.path.join(BASE_DIR, "templates")],
        favicon_url="https://raw.githubusercontent.com/fastapi-admin/fastapi-admin/dev/images/favicon.png",
        default_locale="zh_CN",
        providers=[
            LoginProvider(
                login_logo_url="https://preview.tabler.io/static/logo.svg",
                admin_model=Admin,
            ),
            PermissionProvider(
                admin_model=Admin,
                permission_model=Permission,
                role_model=Role,
                get_admin_permissions=get_admin_permissions,
                resource_model=Resource,
            ),
            AdminLogProvider(AdminLog),
        ],
        storage=storage,
    )
    
    # 导入资源，触发权限收集
    import examples.resources
    
    yield
    # 关闭数据库连接
    await Tortoise.close_connections()


def create_app():
    app = FastAPI(lifespan=lifespan)
    app.mount(
        "/static",
        StaticFiles(directory=os.path.join(BASE_DIR, "static")),
        name="static",
    )

    @app.get("/")
    async def index():
        from examples.models import Admin
        
        # 检查是否存在管理员用户
        has_users = await Admin.all().limit(1).exists()
        
        if has_users:
            # 如果存在用户，重定向到管理面板
            return RedirectResponse(url="/admin")
        else:
            # 如果不存在用户，重定向到初始化页面
            return RedirectResponse(url="/admin/init")

    admin_app.add_exception_handler(HTTP_500_INTERNAL_SERVER_ERROR, server_error_exception)
    admin_app.add_exception_handler(HTTP_404_NOT_FOUND, not_found_error_exception)
    admin_app.add_exception_handler(HTTP_403_FORBIDDEN, forbidden_error_exception)
    admin_app.add_exception_handler(HTTP_401_UNAUTHORIZED, unauthorized_error_exception)

    app.mount("/admin", admin_app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
    )

    return app


app_ = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app_", reload=True)
