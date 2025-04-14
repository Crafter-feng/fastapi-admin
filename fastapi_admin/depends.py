from typing import List, Optional, Type

from fastapi import Depends, HTTPException
from fastapi.params import Path
from starlette.requests import Request
from starlette.status import HTTP_401_UNAUTHORIZED, HTTP_403_FORBIDDEN, HTTP_404_NOT_FOUND
from tortoise import Tortoise

from fastapi_admin.exceptions import InvalidResource
from fastapi_admin.resources import Dropdown, Link, Model, Resource
from fastapi_admin.utils.logger import logger


def get_model(resource: Optional[str] = Path(...)):
    if not resource:
        logger.debug(f"资源名为空，返回None")
        return
    logger.debug(f"尝试获取资源: {resource}")
    for app, models in Tortoise.apps.items():
        models = {key.lower(): val for key, val in models.items()}
        model = models.get(resource)
        if model:
            logger.debug(f"找到模型: {model.__name__}")
            return model
    logger.warning(f"未找到对应的模型: {resource}")
    return None


async def get_model_resource(request: Request, model=Depends(get_model)):
    logger.debug(f"开始获取模型资源, 模型: {model}")
    model_resource = request.app.get_model_resource(model)  # type:Model
    if not model_resource:
        logger.warning(f"未找到模型资源: {model}")
        raise HTTPException(status_code=HTTP_404_NOT_FOUND)
    logger.debug(f"找到模型资源: {model_resource}")
    actions = await model_resource.get_actions(request)
    bulk_actions = await model_resource.get_bulk_actions(request)
    toolbar_actions = await model_resource.get_toolbar_actions(request)
    setattr(model_resource, "toolbar_actions", toolbar_actions)
    setattr(model_resource, "actions", actions)
    setattr(model_resource, "bulk_actions", bulk_actions)
    return model_resource


def _get_resources(resources: List[Type[Resource]]):
    logger.debug(f"开始处理资源列表，共 {len(resources)} 个资源")
    ret = []
    for resource in resources:
        logger.debug(f"处理资源: {resource.__name__}")
        item = {
            "icon": resource.icon,
            "label": resource.label,
        }
        if issubclass(resource, Link):
            logger.debug(f"资源类型: Link, URL: {resource.url}")
            item["type"] = "link"
            item["url"] = resource.url
            item["target"] = resource.target
        elif issubclass(resource, Model):
            logger.debug(f"资源类型: Model")
            item["type"] = "model"
            if resource.model is None:
                logger.warning(f"警告: 资源 {resource.__name__} 的 model 属性为 None，使用默认值 'unknown'")
                item["model"] = "unknown"
            else:
                model_name = resource.model.__name__.lower()
                logger.debug(f"模型名称: {model_name}")
                item["model"] = model_name
        elif issubclass(resource, Dropdown):
            logger.debug(f"资源类型: Dropdown, 子资源数量: {len(resource.resources)}")
            item["type"] = "dropdown"
            item["resources"] = _get_resources(resource.resources)
        else:
            logger.error(f"无效的资源类型: {resource.__name__}")
            raise InvalidResource("Should be subclass of Resource")
        ret.append(item)
    return ret


def get_resources(request: Request) -> List[dict]:
    logger.debug("获取所有资源")
    resources = request.app.resources
    return _get_resources(resources)


def get_storage(request: Request):
    logger.debug("获取存储实例")
    return request.app.storage


def get_current_user(request: Request):
    logger.debug("获取当前管理员")
    user = request.state.user
    if not user:
        logger.warning("未获取到管理员信息，返回401未授权错误")
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED)
    logger.debug(f"当前管理员: {user}")
    return user


async def check_permission(
    request: Request,
    permission_type: str,
    resource_type: str,
    admin=Depends(get_current_user),
):
    """检查用户是否有特定资源的特定权限
    
    Args:
        request: 请求对象
        permission_type: 权限类型（read, create, update, delete）
        resource_type: 资源类型
        admin: 管理员对象（通过依赖注入）
        
    Raises:
        HTTPException: 如果没有权限，抛出403错误
    """
    logger.debug(f"检查权限: 资源={resource_type}, 操作={permission_type}, 管理员={admin}")
    
    permission_provider = getattr(request.app, "permission_provider", None)
    
    if not permission_provider:
        logger.debug("未配置权限提供者，跳过权限检查")
        return
    
    has_permission = await permission_provider.check_permission(
        request, admin, resource_type, permission_type
    )
    
    if not has_permission:
        logger.warning(f"权限检查失败: 管理员 {admin} 没有 {resource_type} 资源的 {permission_type} 权限")
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN,
            detail="Permission denied",
        )
    
    logger.debug("权限检查通过")


async def check_resource_permission(
    request: Request,
    permission_type: str,
    model_resource=Depends(get_model_resource),
    admin=Depends(get_current_user),
):
    """用于在路由中检查权限的依赖函数
    
    Args:
        request: 请求对象
        permission_type: 权限类型（read, create, update, delete）
        model_resource: 资源模型对象
        admin: 管理员对象
    
    Raises:
        HTTPException: 如果没有权限，抛出403错误
    """
    logger.debug(f"检查资源权限: 操作={permission_type}, 管理员={admin}")
    
    permission_provider = getattr(request.app, "permission_provider", None)
    
    if not permission_provider:
        logger.debug("未配置权限提供者，跳过权限检查")
        return
    
    # 添加对model属性的检查
    if model_resource.model is None:
        logger.warning(f"警告: 资源 {model_resource.__class__.__name__} 的 model 属性为 None")
        resource_type = "unknown"
    else:
        resource_type = model_resource.model.__name__.lower()
        
    logger.debug(f"资源类型: {resource_type}")
    
    has_permission = await permission_provider.check_permission(
        request, admin, resource_type, permission_type
    )
    
    if not has_permission:
        logger.warning(f"资源权限检查失败: 管理员 {admin} 没有 {resource_type} 资源的 {permission_type} 权限")
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN,
            detail="Permission denied",
        )
    
    logger.debug("资源权限检查通过")
