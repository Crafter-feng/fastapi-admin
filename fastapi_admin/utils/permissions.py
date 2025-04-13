"""
权限管理工具模块，用于自动收集和管理权限
"""
from typing import Dict, List, Set, Type, Optional, Any
from fastapi_admin.resources import Model, Resource, Dropdown
from fastapi_admin.constants import PERMISSION_READ, PERMISSION_CREATE, PERMISSION_UPDATE, PERMISSION_DELETE
from fastapi_admin.utils.logger import logger

# 全局权限收集器
class PermissionCollector:
    """权限收集器，用于自动收集资源的权限信息"""
    
    def __init__(self):
        # 存储收集到的权限: {resource_path: {permission_type}}
        self._permissions: Dict[str, Set[str]] = {}
        # 存储资源路径到显示标签的映射
        self._resource_labels: Dict[str, str] = {}
        # 存储收集到的资源路径
        self._resources: List[str] = []
        # 是否已初始化到数据库
        self._initialized = False
    
    def collect_resource(self, resource: Type[Resource]):
        """收集单个资源的权限信息"""
        if isinstance(resource, type) and issubclass(resource, Dropdown):
            # 对于下拉菜单，递归收集其子资源
            for sub_resource in resource.resources:
                self.collect_resource(sub_resource)
        elif isinstance(resource, type) and issubclass(resource, Model):
            # 对于模型资源，收集CRUD权限
            resource_name = getattr(resource, 'name', None) or resource.__name__.lower().replace('resource', '')
            label = getattr(resource, 'label', None) or resource_name.title()
            
            # 记录资源路径和标签
            self._resource_labels[resource_name] = label
            if resource_name not in self._resources:
                self._resources.append(resource_name)
            
            # 如果模型资源不存在，则添加
            if resource_name not in self._permissions:
                self._permissions[resource_name] = set()
            
            # 添加基本CRUD权限
            self._permissions[resource_name].add(PERMISSION_READ)
            self._permissions[resource_name].add(PERMISSION_CREATE)
            self._permissions[resource_name].add(PERMISSION_UPDATE)
            self._permissions[resource_name].add(PERMISSION_DELETE)
            
            logger.info(f" 已收集资源权限: {resource_name} - {label}")
    
    def get_all_permissions(self) -> Dict[str, List[str]]:
        """获取所有收集到的权限"""
        return {k: list(v) for k, v in self._permissions.items()}
    
    def get_all_resources(self) -> List[str]:
        """获取所有收集到的资源路径"""
        return self._resources
    
    def get_resource_label(self, resource_path: str) -> str:
        """获取资源的显示标签"""
        return self._resource_labels.get(resource_path, resource_path.title())
    
    def mark_initialized(self):
        """标记权限已初始化到数据库"""
        self._initialized = True
    
    def is_initialized(self) -> bool:
        """检查权限是否已初始化到数据库"""
        return self._initialized


# 创建全局权限收集器实例
permission_collector = PermissionCollector()


async def sync_permissions_to_db(permission_model, resource_model=None, role_model=None):
    """同步收集到的权限到数据库
    
    Args:
        permission_model: 权限模型类
        resource_model: 资源模型类，可选
        role_model: 角色模型类，可选
    """
    if permission_collector.is_initialized():
        return
    
    # 同步资源
    if resource_model:
        for resource_path in permission_collector.get_all_resources():
            label = permission_collector.get_resource_label(resource_path)
            await resource_model.get_or_create(
                path=resource_path,
                defaults={"label": label}
            )
    
    # 同步权限
    permissions = permission_collector.get_all_permissions()
    for resource, actions in permissions.items():
        for action in actions:
            label = f"{permission_collector.get_resource_label(resource)} {action}"
            await permission_model.get_or_create(
                resource=resource,
                permission=action,
                defaults={"label": label}
            )
    
    # 添加通配符权限
    await permission_model.get_or_create(
        resource="*",
        permission="*",
        defaults={"label": "All permissions"}
    )
    
    # 如果角色模型存在，创建默认角色
    if role_model:
        # 创建管理员角色
        admin_role, _ = await role_model.get_or_create(label="Administrator")

        # 分配权限
        # 管理员角色拥有所有权限
        all_perms = await permission_model.filter(resource="*", permission="*").first()
        if all_perms:
            await admin_role.permissions.add(all_perms)
        
    
    # 标记已初始化
    permission_collector.mark_initialized()
    logger.info(f" 权限同步完成，共 {len(permissions)} 个资源，{sum(len(p) for p in permissions.values())} 个权限") 