import datetime
import json

from tortoise import Model, fields

from examples.enums import ProductType, Status
from fastapi_admin.models import AbstractAdmin, AbstractAdminLog
from fastapi_admin.models import AbstractPermission 
from fastapi_admin.models import AbstractRole
from fastapi_admin.models import AbstractResource 


class Admin(AbstractAdmin):
    last_login = fields.DatetimeField(description="Last Login", default=datetime.datetime.now)
    email = fields.CharField(max_length=200, default="")
    avatar = fields.CharField(max_length=200, default="")
    intro = fields.TextField(default="")
    created_at = fields.DatetimeField(auto_now_add=True)
    is_superuser = fields.BooleanField(default=False, description="Is Superuser")
    is_active = fields.BooleanField(default=False, description="Is Active")
    permissions = fields.JSONField(default={}, description="Permissions")
    
    # 关联角色
    roles = fields.ManyToManyField("models.Role", related_name="admins")

    def __str__(self):
        return f"{self.pk}#{self.username}"
    
    async def get_permissions(self):
        """获取管理员权限"""
        # 如果是超级管理员，返回全部权限
        if self.is_superuser:
            return {"admin": True}
        
        # 从角色获取权限
        permissions = {}
        roles = await self.roles.all().prefetch_related("permissions")
        
        for role in roles:
            for perm in await role.permissions.all():
                if perm.resource not in permissions:
                    permissions[perm.resource] = []
                
                if perm.permission not in permissions[perm.resource]:
                    permissions[perm.resource].append(perm.permission)
        
        # 合并当前配置的权限
        if self.permissions:
            if isinstance(self.permissions, str):
                try:
                    user_perms = json.loads(self.permissions)
                except:
                    user_perms = {}
            else:
                user_perms = self.permissions
                
            for resource, perms in user_perms.items():
                if resource not in permissions:
                    permissions[resource] = []
                
                for perm in perms:
                    if perm not in permissions[resource]:
                        permissions[resource].append(perm)
        
        return permissions


class Category(Model):
    slug = fields.CharField(max_length=200)
    name = fields.CharField(max_length=200)
    created_at = fields.DatetimeField(auto_now_add=True)


class Product(Model):
    categories = fields.ManyToManyField("models.Category")
    name = fields.CharField(max_length=50)
    view_num = fields.IntField(description="View Num")
    sort = fields.IntField()
    is_reviewed = fields.BooleanField(description="Is Reviewed")
    type = fields.IntEnumField(ProductType, description="Product Type")
    image = fields.CharField(max_length=200)
    body = fields.TextField()
    created_at = fields.DatetimeField(auto_now_add=True)


class Config(Model):
    label = fields.CharField(max_length=200)
    key = fields.CharField(max_length=20, unique=True, description="Unique key for config")
    value = fields.JSONField()
    status: Status = fields.IntEnumField(Status, default=Status.on)


class Resource(AbstractResource):
    """资源模型"""
    is_public = fields.BooleanField(default=False)


class Permission(AbstractPermission):
    """权限模型"""
    pass


class Role(AbstractRole):
    """角色模型"""
    pass
    
    # 与权限的多对多关系
    permissions = fields.ManyToManyField("models.Permission", related_name="roles")


class AdminLog(AbstractAdminLog):
    """管理员操作日志"""
    
    class Meta:
        table = "admin_logs"
