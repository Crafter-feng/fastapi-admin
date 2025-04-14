from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from fastapi_admin.providers import Provider
from fastapi_admin.utils.logger import logger
from fastapi_admin.resources import Model, Field
from fastapi_admin.widgets import displays, filters
from fastapi_admin.i18n import _
from typing import List

class AdminLogProvider(Provider):
    """
    管理日志Provider，用于提供日志资源和模型
    """
    name = 'admin_log_provider'
    
    def __init__(self, log_model):
        """
        初始化管理日志Provider
        
        Args:
            log_model: 日志模型类，必须是AbstractLog的子类
        """
        self.log_model = log_model
    
    async def register(self, app: 'FastAPIAdmin'):
        """
        注册Provider
        
        Args:
            app: FastAPIAdmin应用实例
        """
        await super(AdminLogProvider, self).register(app)
        logger.info(f"注册AdminLogProvider，使用日志模型: {self.log_model.__name__}")
        
        # 注册日志资源
        self.register_log_resources(app)
        
        # 添加中间件
        app.add_middleware(BaseHTTPMiddleware, dispatch=self.admin_log_middleware)
    
    def register_log_resources(self, app: 'FastAPIAdmin'):
        """
        注册日志相关资源
        """
        logger.info(f"开始注册日志资源")
        
        # 注册LogResource日志资源类
        @app.register
        class LogResource(Model):
            label = _("Admin_Log")
            model = self.log_model
            icon = "fas fa-history"
            page_pre_title = _("System_Log")
            page_title = _("View_Admin_Operations")
            # 默认按照创建时间倒序排列
            order_by = ["-created_at"]
            filters = [
                filters.Search(name="resource", label=_("Resource_Type")),
                filters.Search(name="action", label=_("Action_Type")),
                filters.Search(name="user__username", label=_("Username")),
                filters.Datetime(name="created_at", label=_("Operation_Time")),
            ]
            fields = [
                "id",
                Field(name="user", label=_("User")),
                Field(name="resource", label=_("Resource_Type")),
                Field(name="action", label=_("Action_Type")),
                Field(name="content", label=_("Operation_Content"), display=displays.Json()),
                Field(name="created_at", label=_("Operation_Time")),
            ]
            
            async def get_toolbar_actions(self, request: Request) -> List:
                # 不允许创建日志
                return []
            
            async def get_actions(self, request: Request) -> List:
                # 不允许编辑和删除日志
                return []
    
    async def admin_log_middleware(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """
        管理日志中间件，用于在请求上下文中存储当前管理员信息
        
        Args:
            request: 请求对象
            call_next: 下一个处理器
            
        Returns:
            Response: 响应对象
        """
        # 将当前管理员信息存储在请求状态中
        user = getattr(request.state, 'user', None)
        if user:
            request.state.admin_for_log = user
        
        response = await call_next(request)
        return response