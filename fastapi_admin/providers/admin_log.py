from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from tortoise import signals
from fastapi_admin.providers import Provider
from fastapi_admin.utils.logger import logger
from fastapi_admin.resources import Model, Field
from fastapi_admin.widgets import displays, filters
from fastapi_admin.i18n import _
from typing import List

class AdminLogProvider(Provider):
    """
    管理日志Provider，用于记录数据库的CUD（创建、更新、删除）操作
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
        
        # 添加信号处理器
        for model_class in app.model_resources.keys():
            model_name = model_class.__name__
            logger.debug(f"为模型 {model_name} 添加信号处理器")
            
            # 创建操作日志
            signals.post_save(model_class)(self.log_create_or_update)
            
            # 删除操作日志
            signals.pre_delete(model_class)(self.log_delete)
        
        app.add_middleware(BaseHTTPMiddleware, dispatch=self.admin_log_middleware)
    
    def register_log_resources(self, app: 'FastAPIAdmin'):
        """
        注册日志相关资源
        """
        logger.info(f"开始注册日志资源")
        
        # 注册LogResource日志资源类
        @app.register
        class LogResource(Model):
            label = _("操作日志")
            model = self.log_model
            icon = "fas fa-history"
            page_pre_title = _("系统操作日志")
            page_title = _("查看管理员操作记录")
            filters = [
                filters.Search(name="resource", label=_("资源类型")),
                filters.Search(name="action", label=_("操作类型")),
                filters.Search(name="admin__username", label=_("管理员用户名")),
                filters.Datetime(name="created_at", label=_("操作时间")),
            ]
            fields = [
                "id",
                Field(name="admin", label=_("管理员")),
                Field(name="resource", label=_("资源类型")),
                Field(name="action", label=_("操作类型")),
                Field(name="content", label=_("操作内容"), display=displays.Json()),
                Field(name="created_at", label=_("操作时间")),
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
        admin = getattr(request.state, 'admin', None)
        if admin:
            request.state.admin_for_log = admin
        
        response = await call_next(request)
        return response
    
    async def log_create_or_update(self, sender, instance, created, using_db, update_fields):
        """
        创建或更新操作的日志记录
        
        Args:
            sender: 发送信号的模型类
            instance: 实例对象
            created: 是否是新创建的实例
            using_db: 使用的数据库连接
            update_fields: 更新的字段
        """
        try:
            action = "create" if created else "edit"
            await self._log_action(sender, instance, action)
        except Exception as e:
            logger.error(f"记录{sender.__name__}的{action}操作日志失败: {str(e)}")
    
    async def log_delete(self, sender, instance, using_db):
        """
        删除操作的日志记录
        
        Args:
            sender: 发送信号的模型类
            instance: 实例对象
            using_db: 使用的数据库连接
        """
        try:
            await self._log_action(sender, instance, "delete")
        except Exception as e:
            logger.error(f"记录{sender.__name__}的删除操作日志失败: {str(e)}")
    
    async def _log_action(self, model_class, instance, action):
        """
        记录操作日志的核心方法
        
        Args:
            model_class: 模型类
            instance: 实例对象
            action: 操作类型（create, edit, delete）
        """
        from starlette.concurrency import run_in_threadpool
        import inspect
        
        # 获取当前请求的上下文
        frame = inspect.currentframe()
        while frame:
            if frame.f_locals.get('request'):
                request = frame.f_locals.get('request')
                break
            frame = frame.f_back
        
        # 如果没有找到请求上下文，则无法记录日志
        if not frame:
            logger.debug(f"无法获取请求上下文，跳过日志记录")
            return
        
        # 获取当前管理员
        admin = getattr(request.state, 'admin_for_log', None)
        if not admin:
            logger.debug(f"当前请求无管理员信息，跳过日志记录")
            return
        
        # 获取模型名称作为资源标识
        resource = model_class.__name__.lower()
        
        # 准备日志内容
        try:
            # 将实例转换为字典
            if hasattr(instance, 'to_dict'):
                content = await run_in_threadpool(instance.to_dict)
            else:
                content = {}
                for field in model_class._meta.fields:
                    field_name = field
                    try:
                        content[field_name] = str(getattr(instance, field_name))
                    except Exception:
                        content[field_name] = None
            
            # 添加主键信息
            if hasattr(instance, 'pk'):
                content['pk'] = instance.pk
            
            # 创建日志记录
            await self.log_model.create(
                admin=admin,
                content=content,
                resource=resource,
                action=action
            )
            
            logger.debug(f"成功记录{resource}的{action}操作日志")
        except Exception as e:
            logger.error(f"记录操作日志时发生错误: {str(e)}")