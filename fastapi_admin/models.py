from tortoise import Model, fields


class AbstractAdmin(Model):
    username = fields.CharField(max_length=50, unique=True)
    password = fields.CharField(max_length=200)

    class Meta:
        abstract = True

class AbstractResource(Model):
    """资源模型"""
    label = fields.CharField(max_length=200)
    path = fields.CharField(max_length=200)
    
    class Meta:
        abstract = True


class AbstractPermission(Model):
    """权限模型"""
    label = fields.CharField(max_length=200)
    resource = fields.CharField(max_length=200)
    permission = fields.CharField(max_length=50)
    
    class Meta:
        abstract = True


class AbstractRole(Model):
    """角色模型"""
    label = fields.CharField(max_length=200)
    
    class Meta:
        abstract = True

class AbstractAdminLog(Model):
    """
    抽象日志模型，用于记录管理员的操作日志
    
    用户应该继承这个模型创建自己的日志模型，例如：
    
    ```python
    class AdminLog(AbstractAdminLog):
        class Meta:
            table = "logs"
    ```
    """
    admin = fields.ForeignKeyField("models.Admin")
    content = fields.JSONField()
    resource = fields.CharField(max_length=50)
    action = fields.CharField(max_length=10, default="create")  # create, edit, delete
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        abstract = True
        ordering = ["-id"]
