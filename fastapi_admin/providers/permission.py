from fastapi_admin.utils.logger import logger


import typing
from typing import Type, Dict, Optional, Any
import json
from fastapi import Depends, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response, JSONResponse
from starlette.status import HTTP_403_FORBIDDEN
from fastapi_admin.depends import get_current_admin
from fastapi_admin.models import AbstractAdmin
from fastapi_admin.providers import Provider
from fastapi_admin.resources import Model, Dropdown, Field
from fastapi_admin.template import templates
from fastapi_admin import constants
from fastapi_admin.utils.permissions import sync_permissions_to_db
from fastapi_admin.i18n import _
if typing.TYPE_CHECKING:
    from fastapi_admin.app import FastAPIAdmin

class PermissionAction():
    '权限操作定义类'
    READ = 'read'
    CREATE = 'create'
    UPDATE = 'update'
    DELETE = 'delete'
    ALL = [READ, CREATE, UPDATE, DELETE]

class PermissionProvider(Provider):
    name = 'permission_provider'

    def __init__(self, admin_model: Type[AbstractAdmin], permission_model=None, role_model=None, resource_model=None, get_admin_permissions=None, admin_role_relation_model=None, role_permission_relation_model=None):
        '初始化权限控制Provider\n        \n        Args:\n            admin_model: 管理员模型类\n            permission_model: 权限模型类\n            role_model: 角色模型类\n            resource_model: 资源模型类\n            get_admin_permissions: 可选的获取管理员权限的自定义函数\n            admin_role_relation_model: 管理员-角色关系模型\n            role_permission_relation_model: 角色-权限关系模型\n        '
        self.admin_model = admin_model
        self.permission_model = permission_model
        self.role_model = role_model
        self.resource_model = resource_model
        self.get_admin_permissions = get_admin_permissions
        self.admin_role_relation_model = admin_role_relation_model
        self.role_permission_relation_model = role_permission_relation_model

    async def register(self, app: 'FastAPIAdmin'):
        '向FastAPI Admin注册权限控制'
        (await super(PermissionProvider, self).register(app))
        app.add_middleware(BaseHTTPMiddleware, dispatch=self.permission_middleware)
        if (self.permission_model and self.role_model):
            logger.info(f' 注册权限Provider: {self.permission_model}, {self.role_model}')
            
            # 使用权限收集器同步权限
            if self.permission_model and hasattr(app, 'resources') and app.resources:
                # 应用已注册资源，使用权限收集器同步权限到数据库
                logger.info(f' 使用权限收集器同步权限到数据库')
                await sync_permissions_to_db(
                    permission_model=self.permission_model,
                    resource_model=self.resource_model,
                    role_model=self.role_model
                )
            
            self.register_permission_resources(app)
            self.register_permission_api(app)

    def register_permission_resources(self, app: 'FastAPIAdmin'):
        '注册权限相关资源'
        logger.info(f' 开始注册权限资源')

        class PermissionResource(Model):
            label = _('Permission')
            model = self.permission_model
            fields = [
                "id", 
                Field(name="resource", label=_("resource")),
                Field(name="permission", label=_("permission")),
                Field(name="label", label=_("Label"))
            ]

        class RoleResource(Model):
            label = _('Role')
            model = self.role_model
            fields = [
                "id", 
                Field(name="label", label=_("Label"))
            ]

        class ResourceResource(Model):
            label = _('Resource')
            model = self.resource_model
            fields = [
                "id", 
                Field(name="label", label=_("Label")),
                Field(name="path", label=_("path"))
            ]

        class AdminResource(Model):
            label = _('Admin')
            model = self.admin_model

            fields = [
                "id", 
                Field(name="username", label=_("username")),
                Field(name="email", label=_("email")), 
                Field(name="is_superuser", label=_("is_superuser")), 
                Field(name="is_active", label=_("is_active")), 
                Field(name="last_login", label=_("last_login")), 
                Field(name="created_at", label=_("created_at")), 
                Field(name="permissions", label=_("permissions"))
            ]
            exclude_fields = ["last_login", "created_at"]

        @app.register
        class Auth(Dropdown):
            label = _('Auth')
            icon = 'fas fa-users-cog'
            resources = [AdminResource, ResourceResource, PermissionResource, RoleResource]

    def register_permission_api(self, app: 'FastAPIAdmin'):
        '注册权限相关API'
        logger.info(f' 开始注册权限API路由')

        @app.get('/api/permissions')
        async def get_permissions(request: Request, admin=Depends(get_current_admin)):
            '获取所有权限API'
            if self.permission_model:
                permissions = (await self.permission_model.all())
                return {'permissions': [{'id': perm.pk, 'resource': perm.resource, 'permission': perm.permission, 'label': perm.label} for perm in permissions]}
            return {'permissions': []}

        @app.get('/api/roles')
        async def get_roles(request: Request, admin=Depends(get_current_admin)):
            '获取所有角色API'
            if self.role_model:
                roles = (await self.role_model.all())
                return {'roles': [{'id': role.pk, 'label': role.label} for role in roles]}
            return {'roles': []}

        @app.get('/api/roles/{role_id}/permissions')
        async def get_role_permissions(request: Request, role_id: int, admin=Depends(get_current_admin)):
            '获取角色权限API'
            if (not self.role_model):
                return {'permissions': []}
            role = (await self.role_model.get(pk=role_id))
            if (not role):
                return {'permissions': []}
            permission_ids = (await self._get_role_permissions(role))
            return {'permissions': permission_ids}

        @app.post('/api/roles/{role_id}/permissions')
        async def update_role_permissions(request: Request, role_id: int, admin=Depends(get_current_admin)):
            '更新角色权限API'
            if (not self.role_model):
                return {'status': 'error', 'message': '未配置角色模型'}
            role = (await self.role_model.get(pk=role_id))
            if (not role):
                return {'status': 'error', 'message': '角色不存在'}
            data = (await request.json())
            permission_ids = data.get('permissions', [])
            (await self._update_role_permissions(role, permission_ids))
            return {'status': 'success', 'message': '权限更新成功'}

        @app.get('/api/admins/{admin_id}/roles')
        async def get_admin_roles(request: Request, admin_id: int, admin=Depends(get_current_admin)):
            '获取管理员角色API'
            if (not self.admin_model):
                return {'roles': []}
            target_admin = (await self.admin_model.get(pk=admin_id))
            if (not target_admin):
                return {'roles': []}
            role_ids = (await self._get_admin_roles(target_admin))
            return {'roles': role_ids}

        @app.post('/api/admins/{admin_id}/roles')
        async def update_admin_roles(request: Request, admin_id: int, admin=Depends(get_current_admin)):
            '更新管理员角色API'
            if ((not self.admin_model) or (not self.role_model)):
                return {'status': 'error', 'message': '未配置管理员或角色模型'}
            target_admin = (await self.admin_model.get(pk=admin_id))
            if (not target_admin):
                return {'status': 'error', 'message': '管理员不存在'}
            data = (await request.json())
            role_ids = data.get('roles', [])
            (await self._update_admin_roles(target_admin, role_ids))
            return {'status': 'success', 'message': '角色更新成功'}

        @app.get('/assign_permissions/{role_id}')
        async def assign_permissions_page(request: Request, role_id: int, admin=Depends(get_current_admin)):
            '分配权限页面'
            if ((not self.role_model) or (not self.permission_model)):
                raise HTTPException(status_code=404, detail='角色或权限模型未配置')
            role = (await self.role_model.get_or_none(pk=role_id))
            if (not role):
                raise HTTPException(status_code=404, detail='角色不存在')
            permissions = (await self.permission_model.all())
            role_permissions = (await self._get_role_permissions(role))
            return templates.TemplateResponse('providers/permission/assign_permissions.html', context={'request': request, 'role': role, 'permissions': permissions, 'role_permissions': role_permissions})

        @app.get('/assign_roles/{admin_id}')
        async def assign_roles_page(request: Request, admin_id: int, admin=Depends(get_current_admin)):
            '分配角色页面'
            if ((not self.admin_model) or (not self.role_model)):
                raise HTTPException(status_code=404, detail='管理员或角色模型未配置')
            target_admin = (await self.admin_model.get_or_none(pk=admin_id))
            if (not target_admin):
                raise HTTPException(status_code=404, detail='管理员不存在')
            roles = (await self.role_model.all())
            admin_roles = (await self._get_admin_roles(target_admin))
            return templates.TemplateResponse('providers/permission/assign_roles.html', context={'request': request, 'admin': target_admin, 'roles': roles, 'admin_roles': admin_roles})

        @app.get('/admin/edit/{admin_id}')
        async def edit_admin_page(request: Request, admin_id: int, admin=Depends(get_current_admin)):
            '编辑管理员页面'
            if (not self.admin_model):
                raise HTTPException(status_code=404, detail='管理员模型未配置')
            target_admin = (await self.admin_model.get_or_none(pk=admin_id))
            if (not target_admin):
                raise HTTPException(status_code=404, detail='管理员不存在')
            return templates.TemplateResponse('providers/permission/edit_admin.html', context={'request': request, 'admin': target_admin, 'title': f'编辑管理员: {target_admin.username}'})

        @app.get('/admin/create')
        async def create_admin_page(request: Request, admin=Depends(get_current_admin)):
            '创建管理员页面'
            if (not self.admin_model):
                raise HTTPException(status_code=404, detail='管理员模型未配置')
            return templates.TemplateResponse('providers/permission/edit_admin.html', context={'request': request, 'admin': None, 'title': '创建新管理员'})

    async def _get_role_permissions(self, role):
        '获取角色权限ID列表，根据具体ORM关系实现'
        try:
            if (hasattr(role, 'permissions') and role.permissions):
                permissions = (await role.permissions.all())
                if permissions:
                    return [p.pk for p in permissions]
            logger.info(f' 获取角色权限: 角色 {role.pk} 没有权限')
            return []
        except Exception as e:
            logger.info(f' 获取角色权限出错: {str(e)}')
            return []

    async def _update_role_permissions(self, role, permission_ids):
        '更新角色权限，根据具体ORM关系实现'
        try:
            if hasattr(role, 'permissions'):
                (await role.permissions.clear())
                logger.info(f' 清除角色 {role.pk} 的权限')
                if permission_ids:
                    logger.info(f' 为角色 {role.pk} 添加权限 {permission_ids}')
                    permissions = (await self.permission_model.filter(pk__in=permission_ids))
                    for perm in permissions:
                        (await role.permissions.add(perm))
            return True
        except Exception as e:
            logger.info(f' 更新角色权限出错: {str(e)}')
            return False

    async def _get_admin_roles(self, admin):
        '获取管理员角色ID列表，根据具体ORM关系实现'
        if hasattr(admin, 'roles'):
            return [r.pk for r in (await admin.roles.all())]
        return []

    async def _update_admin_roles(self, admin, role_ids):
        '更新管理员角色，根据具体ORM关系实现'
        if hasattr(admin, 'roles'):
            (await admin.roles.clear())
            if role_ids:
                roles = (await self.role_model.filter(pk__in=role_ids))
                (await admin.roles.add(*roles))
        return True

    async def permission_middleware(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        '权限控制中间件\n\n        检查用户是否有权限访问请求的资源和方法\n        '
        admin = getattr(request.state, 'admin', None)
        path = request.scope['path']
        method = request.scope['method']
        logger.info(f' 进入权限中间件: Path: {path}, Method: {method}, Admin: {admin}')
        admin_path = request.app.admin_path
        logger.info(f' 应用admin_path是: {admin_path}')
        full_permission_path = f'{admin_path}/permission'
        if ((path == full_permission_path) or path.startswith(f'{full_permission_path}/')):
            logger.info(f' 允许访问权限页面: {path}')
            return (await call_next(request))
        if (path == '/init'):
            logger.info(f' 允许访问初始化页面: {path}')
            return (await call_next(request))
        base_paths = []
        for p in ['/', '/password', '/login', '/logout']:
            base_paths.append(f'{admin_path}{p}')
        if (path in base_paths):
            logger.info(f' 允许访问基本页面: {path}')
            return (await call_next(request))
        if ((not admin) or (not path.startswith(admin_path))):
            logger.info(f' 不是管理路径或未登录: {path}')
            return (await call_next(request))
        resource_path = path.removeprefix(admin_path).strip('/')
        resource_parts = resource_path.split('/')
        if (not resource_parts):
            logger.info(f' 没有资源路径: {path}')
            return (await call_next(request))
        resource_type = resource_parts[0]
        logger.info(f' 资源类型: {resource_type}')
        if (resource_type in ['static', 'statics', 'uploads', 'media']):
            logger.info(f' 允许访问静态资源: {resource_type}')
            return (await call_next(request))
        action = None
        if (len(resource_parts) > 1):
            action = resource_parts[1]
        logger.info(f' 检查权限: 资源={resource_type}, 操作={action}, 方法={method}')
        has_permission = (await self.check_permission(request, admin, resource_type, action, method))
        if (not has_permission):
            logger.info(f' 权限拒绝: {admin} 无权访问 {path}')
            return JSONResponse(status_code=HTTP_403_FORBIDDEN, content={'detail': '权限拒绝'})
        logger.info(f' 权限检查通过，允许访问: {path}')
        return (await call_next(request))

    async def check_permission(self, request: Request, admin: AbstractAdmin, resource_type: str, action: Optional[str]=None, method: Optional[str]=None) -> bool:
        '检查用户是否有权限执行操作\n        \n        Args:\n            request: 请求对象\n            admin: 管理员对象\n            resource_type: 资源类型\n            action: 动作类型\n            method: HTTP方法\n            \n        Returns:\n            bool: 是否有权限\n        '
        if self.get_admin_permissions:
            permissions = (await self.get_admin_permissions(admin))
            return self._check_with_permissions(permissions, resource_type, action, method)
        if (hasattr(admin, 'is_superuser') and getattr(admin, 'is_superuser')):
            return True
        if (self.role_model and self.permission_model and hasattr(admin, 'roles')):
            roles = (await admin.roles.all())
            if ((not roles) and hasattr(admin, 'permissions')):
                permissions = getattr(admin, 'permissions', {})
                if isinstance(permissions, str):
                    try:
                        permissions = json.loads(permissions)
                    except:
                        permissions = {}
                return self._check_with_permissions(permissions, resource_type, action, method)
            for role in roles:
                if hasattr(role, 'permissions'):
                    role_permissions = (await role.permissions.all())
                    required_permission = self._get_required_permission(method, action)
                    for perm in role_permissions:
                        if (((perm.resource == resource_type) or (perm.resource == '*')) and ((perm.permission == required_permission) or (perm.permission == '*'))):
                            return True
            return False
        if hasattr(admin, 'permissions'):
            permissions = getattr(admin, 'permissions', {})
            if isinstance(permissions, str):
                try:
                    permissions = json.loads(permissions)
                except:
                    permissions = {}
            return self._check_with_permissions(permissions, resource_type, action, method)
        return True

    def _get_required_permission(self, method: str, action: Optional[str]=None) -> str:
        '根据HTTP方法和操作类型获取所需权限\n        \n        Args:\n            method: HTTP方法\n            action: 操作类型\n            \n        Returns:\n            str: 所需权限\n        '
        if (method == 'GET'):
            return constants.PERMISSION_READ
        elif (method == 'POST'):
            if (action == 'bulk'):
                return constants.PERMISSION_UPDATE
            else:
                return constants.PERMISSION_CREATE
        elif (method == 'PUT'):
            return constants.PERMISSION_UPDATE
        elif (method == 'DELETE'):
            return constants.PERMISSION_DELETE
        return constants.PERMISSION_READ

    def _check_with_permissions(self, permissions: Dict[(str, Any)], resource_type: str, action: Optional[str]=None, method: Optional[str]=None) -> bool:
        '根据权限字典检查权限\n        \n        Args:\n            permissions: 权限字典，格式如 {"resource_type": ["read", "create"]}\n            resource_type: 资源类型\n            action: 操作类型\n            method: HTTP方法\n            \n        Returns:\n            bool: 是否有权限\n        '
        if ((permissions.get('admin', False) is True) or ('*' in permissions)):
            return True
        resource_permissions = permissions.get(resource_type, [])
        if ('*' in resource_permissions):
            return True
        required_permission = self._get_required_permission(method, action)
        return (required_permission in resource_permissions)
