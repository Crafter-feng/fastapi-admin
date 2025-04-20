from fastapi_admin.utils.logger import logger

import typing
from typing import Type, Dict, Optional, Any, List
import json
from fastapi import Depends, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response, JSONResponse
from starlette.status import HTTP_403_FORBIDDEN
from fastapi_admin.depends import get_current_user
from fastapi_admin.models import AbstractAdmin
from fastapi_admin.providers import Provider
from fastapi_admin.resources import Model, Dropdown, Field, ComputeField, Action, Method
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

    def __init__(self, user_model: Type[AbstractAdmin], permission_model=None, role_model=None, resource_model=None, get_admin_permissions=None, admin_role_relation_model=None, role_permission_relation_model=None):
        '初始化权限控制Provider\n        \n        Args:\n            user_model: 管理员模型类\n            permission_model: 权限模型类\n            role_model: 角色模型类\n            resource_model: 资源模型类\n            get_admin_permissions: 可选的获取管理员权限的自定义函数\n            admin_role_relation_model: 管理员-角色关系模型\n            role_permission_relation_model: 角色-权限关系模型\n        '
        self.user_model = user_model
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
        
        # 将权限提供者实例存储在应用状态中，以便资源类可以访问
        app.state.permission_provider = self
        
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
                "resource",
                "permission",
                "label"
            ]

        class RolePermissionsField(ComputeField):
            """自定义计算字段，用于显示角色的权限"""
            
            async def get_value(self, request: Request, obj: dict):
                """获取权限列表的字符串表示"""
                role_id = obj.get("id")
                if not role_id:
                    # 处理新角色的情况（没有ID）
                    return ""
                
                try:
                    permission_provider = request.app.state.permission_provider
                    role_model = permission_provider.role_model
                    
                    # 尝试获取角色，如果不存在则返回空字符串
                    role = await role_model.get_or_none(pk=role_id)
                    if not role:
                        return ""
                    
                    # 获取角色的所有权限
                    await role.fetch_related("permissions")
                    permissions = await role.permissions.all()
                    
                    # 返回权限标签的逗号分隔列表
                    return ", ".join([p.label for p in permissions]) if permissions else ""
                except Exception as e:
                    logger.error(f"获取角色权限出错: {str(e)}")
                    return ""

        class RoleResource(Model):
            label = _('Role')
            model = self.role_model
            
            # 添加自定义计算字段显示角色的权限
            fields = [
                "id", 
                "label",
                "description",
                RolePermissionsField(name="role_permissions", label=_("Permissions"))
            ]
            
            @classmethod
            async def get_actions(cls, request: Request, obj=None) -> List[Action]:
                """自定义操作 - 注意这是一个类方法，以与资源列表页面兼容
                
                Args:
                    request: 请求对象
                    obj: 可选的对象，在列表视图中为None
                    
                Returns:
                    操作列表
                """
                # 首先获取基本操作 
                actions = [
                    Action(
                        label=_("update"), icon="ti ti-edit", name="update", method=Method.GET, ajax=False
                    ),
                    Action(label=_("delete"), icon="ti ti-trash", name="delete", method=Method.DELETE),
                ]
                
                # 只有在有具体对象时才添加"分配权限"操作
                if obj is not None:
                    actions.append(Action(
                        label=_("Assign Permissions"),
                        icon="ti ti-key",
                        name="assign_permissions",
                        method=Method.GET,
                        ajax=False,
                        url=f"{request.app.admin_path}/assign_permissions/{obj.id}"
                    ))
                return actions
                
            @classmethod
            async def get_form_init(cls, request: Request, obj=None):
                """获取表单初始化数据，包括权限选项"""
                form_init = await super().get_form_init(request, obj)
                
                # 获取所有权限
                permission_model = request.app.state.permission_provider.permission_model
                if permission_model:
                    try:
                        permissions = await permission_model.all()
                        
                        # 确保存在permissions字段
                        if "permissions" not in form_init:
                            form_init["permissions"] = {}
                        
                        # 添加选项列表
                        form_init["permissions"]["options"] = [
                            {"value": str(perm.pk), "label": f"{perm.label} ({perm.resource}.{perm.permission})"} 
                            for perm in permissions
                        ]
                        
                        # 如果是编辑模式，获取当前角色的权限
                        if obj and hasattr(obj, "permissions"):
                            role_permissions = await obj.permissions.all()
                            # 确保selected是一个id列表（字符串格式）
                            form_init["permissions"]["selected"] = [str(perm.pk) for perm in role_permissions]
                            
                            # 记录调试信息
                            logger.debug(f"角色 {obj.pk} 的权限: {form_init['permissions']['selected']}")
                    except Exception as e:
                        logger.error(f"获取权限选项出错: {str(e)}")
                        
                return form_init
            
            @classmethod
            async def save(cls, request: Request, obj, data, **kwargs):
                """保存角色数据，包括权限关联"""
                try:
                    # 首先保存基本信息
                    saved_obj = await super().save(request, obj, data, **kwargs)
                    
                    # 保存权限关联
                    if hasattr(saved_obj, "permissions"):
                        # 获取选中的权限ID
                        permission_ids = data.get("permissions", [])
                        logger.debug(f"保存角色 {saved_obj.pk} 的权限: {permission_ids}")
                        
                        try:
                            # 清除现有权限
                            await saved_obj.permissions.clear()
                            
                            # 处理权限ID
                            if permission_ids:
                                # 确保权限ID是列表
                                if not isinstance(permission_ids, list):
                                    if isinstance(permission_ids, str):
                                        try:
                                            permission_ids = json.loads(permission_ids)
                                        except json.JSONDecodeError:
                                            permission_ids = [permission_ids]
                                    else:
                                        permission_ids = [permission_ids]
                                
                                # 确保所有ID都是整数
                                permission_ids = [int(pid) for pid in permission_ids if pid]
                                
                                if permission_ids:
                                    # 获取权限对象
                                    permission_model = request.app.state.permission_provider.permission_model
                                    if permission_model:
                                        permissions = await permission_model.filter(pk__in=permission_ids)
                                        
                                        # 添加新权限
                                        if permissions:
                                            for perm in permissions:
                                                await saved_obj.permissions.add(perm)
                                            logger.debug(f"成功添加 {len(permissions)} 个权限给角色 {saved_obj.pk}")
                        except Exception as e:
                            logger.error(f"保存角色权限关系出错: {str(e)}")
                            # 继续返回保存的对象，即使权限关系处理失败
                    
                    return saved_obj
                except Exception as e:
                    logger.error(f"保存角色数据出错: {str(e)}")
                    raise

        class ResourceResource(Model):
            label = _('Resource')
            model = self.resource_model
            fields = [
                "id", 
                "label",
                "path"
            ]

        class UserRolesField(ComputeField):
            """自定义计算字段，用于显示用户的角色"""
            
            async def get_value(self, request: Request, obj: dict):
                """获取角色列表的字符串表示"""
                user_id = obj.get("id")
                if not user_id:
                    return ""
                
                try:
                    permission_provider = request.app.state.permission_provider
                    user_model = permission_provider.user_model
                    user = await user_model.get(pk=user_id)
                    
                    # 获取用户的所有角色
                    await user.fetch_related("roles")
                    roles = await user.roles.all()
                    
                    # 返回角色标签的逗号分隔列表
                    return ", ".join([r.label for r in roles]) if roles else ""
                except Exception as e:
                    logger.error(f"获取用户角色出错: {str(e)}")
                    return ""

        class UserResource(Model):
            label = _('User')
            model = self.user_model

            # 添加自定义计算字段显示用户的角色
            fields = [
                "id", 
                "username",
                "email", 
                "is_superuser", 
                "is_active", 
                UserRolesField(name="user_roles", label=_("Roles")),
                "last_login", 
                "created_at"
            ]
            
            @classmethod
            async def get_actions(cls, request: Request, obj=None) -> List[Action]:
                """自定义操作 - 注意这是一个类方法，以与资源列表页面兼容
                
                Args:
                    request: 请求对象
                    obj: 可选的对象，在列表视图中为None
                    
                Returns:
                    操作列表
                """
                # 首先获取基本操作
                actions = [
                    Action(
                        label=_("update"), icon="ti ti-edit", name="update", method=Method.GET, ajax=False
                    ),
                    Action(label=_("delete"), icon="ti ti-trash", name="delete", method=Method.DELETE),
                ]
                
                # 只有在有具体对象时才添加"分配角色"操作
                if obj is not None:
                    actions.append(Action(
                        label=_("Assign Roles"),
                        icon="ti ti-user-cog",
                        name="assign_roles",
                        method=Method.GET,
                        ajax=False,
                        url=f"{request.app.admin_path}/assign_roles/{obj.id}"
                    ))
                return actions
            
            exclude_fields = ["last_login", "created_at"]
            
            @classmethod
            async def get_form_init(cls, request: Request, obj=None):
                """获取表单初始化数据，包括角色选项"""
                form_init = await super().get_form_init(request, obj)
                
                # 获取所有角色
                role_model = request.app.state.permission_provider.role_model
                if role_model:
                    try:
                        roles = await role_model.all()
                        
                        # 确保存在roles字段
                        if "roles" not in form_init:
                            form_init["roles"] = {}
                        
                        # 添加选项列表
                        form_init["roles"]["options"] = [
                            {"value": str(role.pk), "label": role.label} 
                            for role in roles
                        ]
                        
                        # 如果是编辑模式，获取当前用户的角色
                        if obj and hasattr(obj, "roles"):
                            user_roles = await obj.roles.all()
                            # 确保selected是一个id列表（字符串格式）
                            form_init["roles"]["selected"] = [str(role.pk) for role in user_roles]
                            
                            # 记录调试信息
                            logger.debug(f"用户 {obj.pk} 的角色: {form_init['roles']['selected']}")
                    except Exception as e:
                        logger.error(f"获取角色选项出错: {str(e)}")
                        
                return form_init
            
            @classmethod
            async def save(cls, request: Request, obj, data, **kwargs):
                """保存用户数据，包括角色关联"""
                try:
                    # 首先保存基本信息
                    saved_obj = await super().save(request, obj, data, **kwargs)
                    
                    # 保存角色关联
                    if hasattr(saved_obj, "roles"):
                        # 获取选中的角色ID
                        role_ids = data.get("roles", [])
                        logger.debug(f"保存用户 {saved_obj.pk} 的角色: {role_ids}")
                        
                        # 清除现有角色
                        await saved_obj.roles.clear()
                        
                        # 处理角色ID
                        if role_ids:
                            # 确保角色ID是列表
                            if not isinstance(role_ids, list):
                                if isinstance(role_ids, str):
                                    try:
                                        role_ids = json.loads(role_ids)
                                    except json.JSONDecodeError:
                                        role_ids = [role_ids]
                                else:
                                    role_ids = [role_ids]
                            
                            # 确保所有ID都是整数
                            role_ids = [int(rid) for rid in role_ids if rid]
                            
                            if role_ids:
                                # 获取角色对象
                                role_model = request.app.state.permission_provider.role_model
                                roles = await role_model.filter(pk__in=role_ids)
                                
                                # 添加新角色
                                if roles:
                                    await saved_obj.roles.add(*roles)
                                    logger.debug(f"成功添加 {len(roles)} 个角色给用户 {saved_obj.pk}")
                    
                    return saved_obj
                except Exception as e:
                    logger.error(f"保存用户数据出错: {str(e)}")
                    raise

        @app.register
        class Auth(Dropdown):
            label = _('Auth')
            icon = 'fas fa-users-cog'
            resources = [UserResource, RoleResource, PermissionResource, ResourceResource]

    def register_permission_api(self, app: 'FastAPIAdmin'):
        '注册权限相关API'
        logger.info(f' 开始注册权限API路由')

        @app.get('/api/permissions')
        async def get_permissions(request: Request, user=Depends(get_current_user)):
            '获取所有权限API'
            if self.permission_model:
                permissions = (await self.permission_model.all())
                return {'permissions': [{'id': perm.pk, 'resource': perm.resource, 'permission': perm.permission, 'label': perm.label} for perm in permissions]}
            return {'permissions': []}

        @app.get('/api/roles')
        async def get_roles(request: Request, user=Depends(get_current_user)):
            '获取所有角色API'
            if self.role_model:
                roles = (await self.role_model.all())
                return {'roles': [{'id': role.pk, 'label': role.label} for role in roles]}
            return {'roles': []}

        @app.get('/api/roles/{role_id}/permissions')
        async def get_role_permissions(request: Request, role_id: int, user=Depends(get_current_user)):
            '获取角色权限API'
            if (not self.role_model):
                return {'permissions': []}
            role = (await self.role_model.get(pk=role_id))
            if (not role):
                return {'permissions': []}
            permission_ids = (await self._get_role_permissions(role))
            return {'permissions': permission_ids}

        @app.post('/api/roles/{role_id}/permissions')
        async def update_role_permissions(request: Request, role_id: int, user=Depends(get_current_user)):
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

        @app.get('/api/users/{user_id}/roles')
        async def get_user_roles(request: Request, user_id: int, user=Depends(get_current_user)):
            '获取用户角色API'
            if (not self.user_model):
                return {'roles': []}
            target_admin = (await self.user_model.get(pk=user_id))
            if (not target_admin):
                return {'roles': []}
            role_ids = (await self._get_user_roles(target_admin))
            return {'roles': role_ids}

        @app.post('/api/users/{user_id}/roles')
        async def update_user_roles(request: Request, user_id: int, user=Depends(get_current_user)):
            '更新用户角色API'
            if ((not self.user_model) or (not self.role_model)):
                return {'status': 'error', 'message': '未配置用户或角色模型'}
            target_admin = (await self.user_model.get(pk=user_id))
            if (not target_admin):
                return {'status': 'error', 'message': '用户不存在'}
            data = (await request.json())
            role_ids = data.get('roles', [])
            (await self._update_user_roles(target_admin, role_ids))
            return {'status': 'success', 'message': '角色更新成功'}

        @app.get('/assign_permissions/{role_id}')
        async def assign_permissions_page(request: Request, role_id: int, user=Depends(get_current_user)):
            '分配权限页面'
            if ((not self.role_model) or (not self.permission_model)):
                raise HTTPException(status_code=404, detail='角色或权限模型未配置')
            role = (await self.role_model.get_or_none(pk=role_id))
            if (not role):
                raise HTTPException(status_code=404, detail='角色不存在')
            permissions = (await self.permission_model.all())
            role_permissions = (await self._get_role_permissions(role))
            return templates.TemplateResponse('providers/permission/assign_permissions.html', context={'request': request, 'role': role, 'permissions': permissions, 'role_permissions': role_permissions})

        @app.get('/assign_roles/{user_id}')
        async def assign_roles_page(request: Request, user_id: int, user=Depends(get_current_user)):
            '分配角色页面'
            if ((not self.user_model) or (not self.role_model)):
                raise HTTPException(status_code=404, detail='用户或角色模型未配置')
            target_admin = (await self.user_model.get_or_none(pk=user_id))
            if (not target_admin):
                raise HTTPException(status_code=404, detail='用户不存在')
            roles = (await self.role_model.all())
            user_roles = (await self._get_user_roles(target_admin))
            return templates.TemplateResponse('providers/permission/assign_roles.html', context={'request': request, 'user': target_admin, 'roles': roles, 'user_roles': user_roles})

        @app.get('/user/edit/{user_id}')
        async def edit_user_page(request: Request, user_id: int, user=Depends(get_current_user)):
            '编辑用户页面'
            if (not self.user_model):
                raise HTTPException(status_code=404, detail='用户模型未配置')
            
            # 获取用户信息并预加载角色关系
            target_admin = await self.user_model.get_or_none(pk=user_id).prefetch_related('roles')
            if (not target_admin):
                raise HTTPException(status_code=404, detail='用户不存在')
            
            # 获取所有角色和用户当前角色
            roles = await self.role_model.all() if self.role_model else []
            user_roles = [role.pk for role in await target_admin.roles.all()] if hasattr(target_admin, 'roles') else []
            
            return templates.TemplateResponse('providers/permission/edit_user.html', 
                context={
                    'request': request, 
                    'user': target_admin, 
                    'title': f'编辑用户: {target_admin.username}',
                    'roles': roles,
                    'user_roles': user_roles
                })

        @app.get('/user/create')
        async def create_user_page(request: Request, user=Depends(get_current_user)):
            '创建用户页面'
            if (not self.user_model):
                raise HTTPException(status_code=404, detail='用户模型未配置')
            
            # 获取所有角色
            roles = await self.role_model.all() if self.role_model else []
            
            return templates.TemplateResponse('providers/permission/edit_user.html', 
                context={
                    'request': request, 
                    'user': None, 
                    'title': '创建新用户',
                    'roles': roles,
                    'user_roles': []
                })

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
        """更新角色权限，根据具体ORM关系实现"""
        try:
            if hasattr(role, 'permissions'):
                await role.permissions.clear()
                logger.info(f" 清除角色 {role.pk} 的权限")
                if permission_ids:
                    # 确保permission_ids是列表
                    if isinstance(permission_ids, str):
                        try:
                            # 尝试解析JSON字符串
                            import json
                            permission_ids = json.loads(permission_ids)
                        except:
                            # 作为单个ID处理
                            permission_ids = [int(permission_ids)]
                    elif isinstance(permission_ids, int):
                        permission_ids = [permission_ids]
                    
                    # 确保所有ID都是整数
                    permission_ids = [int(pid) if isinstance(pid, str) and pid.isdigit() else pid for pid in permission_ids]
                    
                    logger.info(f" 为角色 {role.pk} 添加权限 {permission_ids}")
                    permissions = await self.permission_model.filter(pk__in=permission_ids)
                    if permissions:
                        for perm in permissions:
                            await role.permissions.add(perm)
            return True
        except Exception as e:
            logger.error(f" 更新角色权限出错: {str(e)}")
            return False

    async def _get_user_roles(self, user):
        '获取用户角色ID列表，根据具体ORM关系实现'
        if hasattr(user, 'roles'):
            return [r.pk for r in (await user.roles.all())]
        return []

    async def _update_user_roles(self, user, role_ids):
        """更新用户角色，根据具体ORM关系实现"""
        try:
            if hasattr(user, 'roles'):
                await user.roles.clear()
                logger.info(f" 清除用户 {user.pk} 的角色")
                if role_ids:
                    # 确保role_ids是列表
                    if isinstance(role_ids, str):
                        try:
                            # 尝试解析JSON字符串
                            import json
                            role_ids = json.loads(role_ids)
                        except:
                            # 作为单个ID处理
                            role_ids = [int(role_ids)]
                    elif isinstance(role_ids, int):
                        role_ids = [role_ids]
                    
                    # 确保所有ID都是整数
                    role_ids = [int(rid) if isinstance(rid, str) and rid.isdigit() else rid for rid in role_ids]
                    
                    logger.info(f" 为用户 {user.pk} 添加角色 {role_ids}")
                    roles = await self.role_model.filter(pk__in=role_ids)
                    if roles:
                        await user.roles.add(*roles)
            return True
        except Exception as e:
            logger.error(f" 更新用户角色出错: {str(e)}")
            return False

    async def permission_middleware(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        '权限控制中间件\n\n        检查用户是否有权限访问请求的资源和方法\n        '
        user = getattr(request.state, 'user', None)
        path = request.scope['path']
        method = request.scope['method']
        logger.info(f' 进入权限中间件: Path: {path}, Method: {method}, User: {user}')
        admin_path = request.app.admin_path
        logger.info(f' 应用admin_path是: {admin_path}')
        
        # 检查是否为权限管理相关路径
        full_permission_path = f'{admin_path}/permission'
        if ((path == full_permission_path) or path.startswith(f'{full_permission_path}/')):
            logger.info(f' 允许访问权限页面: {path}')
            return (await call_next(request))
            
        # 检查是否为初始化路径
        if path == f'{admin_path}/init' or path == '/init':
            logger.info(f' 允许访问初始化页面: {path}')
            return (await call_next(request))
            
        # 检查是否为基本路径
        base_paths = []
        for p in ['/', '/password', '/login', '/logout']:
            base_paths.append(f'{admin_path}{p}')
            
        if path in base_paths:
            logger.info(f' 允许访问基本页面: {path}')
            return (await call_next(request))
            
        # 如果不是管理路径或用户未登录，继续处理
        if not user or not path.startswith(admin_path):
            logger.info(f' 不是管理路径或未登录: {path}')
            return (await call_next(request))
            
        # 解析资源路径
        resource_path = path.removeprefix(admin_path).strip('/')
        resource_parts = resource_path.split('/')
        
        if not resource_parts:
            logger.info(f' 没有资源路径: {path}')
            return (await call_next(request))
            
        # 获取资源类型
        resource_type = resource_parts[0]
        logger.info(f' 资源类型: {resource_type}')
        
        # 允许访问静态资源
        if resource_type in ['static', 'statics', 'uploads', 'media']:
            logger.info(f' 允许访问静态资源: {resource_type}')
            return (await call_next(request))
            
        # 确定操作类型
        action = None
        if len(resource_parts) > 1:
            action = resource_parts[1]
            
        # 如果是模型列表页，资源类型可能是 "list"，需要从第二部分获取实际模型
        if resource_type == 'list' and len(resource_parts) > 1:
            resource_type = resource_parts[1]
            # 如果模型名称包含点，获取最后一部分作为资源类型
            if '.' in resource_type:
                resource_type = resource_type.split('.')[-1].lower()
            
            if len(resource_parts) > 2:
                action = resource_parts[2]
                
        # 检查 create 和 update 特殊路径
        if resource_type in ['create', 'update']:
            prev_resource_type = None
            if len(resource_parts) > 1:
                prev_resource_type = resource_parts[1]
                # 如果模型名称包含点，获取最后一部分作为资源类型
                if prev_resource_type and '.' in prev_resource_type:
                    prev_resource_type = prev_resource_type.split('.')[-1].lower()
                    
            if prev_resource_type:
                action = resource_type  # create 或 update 成为 action
                resource_type = prev_resource_type
            
        logger.info(f' 检查权限: 资源={resource_type}, 操作={action}, 方法={method}')
        
        # 执行权限检查
        try:
            has_permission = await self.check_permission(request, user, resource_type, action, method)
            if not has_permission:
                logger.info(f' 权限拒绝: {user} 无权访问 {path}')
                return JSONResponse(status_code=HTTP_403_FORBIDDEN, content={'detail': '权限拒绝'})
                
            logger.info(f' 权限检查通过，允许访问: {path}')
            return (await call_next(request))
        except Exception as e:
            logger.error(f' 权限检查出错: {str(e)}')
            # 在发生错误时继续请求处理，避免阻止用户访问
            return (await call_next(request))

    async def check_permission(self, request: Request, user: AbstractAdmin, resource_type: str, action: Optional[str]=None, method: Optional[str]=None) -> bool:
        '检查用户是否有权限执行操作\n        \n        Args:\n            request: 请求对象\n            user: 管理员对象\n            resource_type: 资源类型\n            action: 动作类型\n            method: HTTP方法\n            \n        Returns:\n            bool: 是否有权限\n        '
        # 如果是超级管理员，直接返回True
        if (hasattr(user, 'is_superuser') and getattr(user, 'is_superuser')):
            return True
            
        # 如果没有配置角色和权限模型，返回True
        if not (self.role_model and self.permission_model and hasattr(user, 'roles')):
            return True
            
        # 获取用户的所有角色
        roles = await user.roles.all()
        if not roles:
            return False
            
        # 检查每个角色的权限
        required_permission = self._get_required_permission(method, action)
        for role in roles:
            if hasattr(role, 'permissions'):
                role_permissions = await role.permissions.all()
                for perm in role_permissions:
                    if ((perm.resource == resource_type or perm.resource == '*') and 
                        (perm.permission == required_permission or perm.permission == '*')):
                        return True
        return False

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
        if ((permissions.get('user', False) is True) or ('*' in permissions)):
            return True
        resource_permissions = permissions.get(resource_type, [])
        if ('*' in resource_permissions):
            return True
        required_permission = self._get_required_permission(method, action)
        return (required_permission in resource_permissions)
