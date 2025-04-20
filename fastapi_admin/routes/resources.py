from typing import Optional

from fastapi import APIRouter, Depends, Path, HTTPException
from jinja2 import TemplateNotFound
from starlette.requests import Request
from starlette.responses import RedirectResponse
from starlette.status import HTTP_303_SEE_OTHER, HTTP_404_NOT_FOUND
from tortoise import Model
from tortoise.fields import ManyToManyRelation
from tortoise.transactions import in_transaction

from fastapi_admin.depends import get_model, get_model_resource, get_resources
from fastapi_admin.resources import Model as ModelResource
from fastapi_admin.resources import render_values
from fastapi_admin.responses import redirect
from fastapi_admin.template import templates
from fastapi_admin.utils.logger import logger
from fastapi_admin.models import AbstractAdmin
from fastapi_admin.depends import get_current_user

router = APIRouter()


async def log_admin_action(request: Request, model_class, instance, action):
    """
    记录管理员操作日志
    
    Args:
        request: 请求对象
        model_class: 模型类
        instance: 实例对象
        action: 操作类型（create, edit, delete）
    """
    try:
        # 获取应用实例
        app = request.app
        
        # 获取AdminLogProvider - 直接通过名称获取
        admin_log_provider = getattr(app, 'admin_log_provider', None)
        
        if not admin_log_provider:
            logger.warning("未找到AdminLogProvider，无法记录操作日志")
            return
        
        # 获取当前用户
        user = getattr(request.state, 'user', None)
        if not user:
            logger.debug(f"当前请求无用户信息，跳过日志记录")
            return
        
        # 跳过对AdminLog模型本身的记录
        if model_class.__name__.lower() == 'adminlog':
            logger.debug(f"跳过对AdminLog模型本身的日志记录")
            return
        
        # 获取模型名称作为资源标识
        resource = model_class.__name__.lower()
        
        # 准备日志内容
        content = {}
        for field in model_class._meta.fields:
            field_name = field
            try:
                value = getattr(instance, field_name)
                # 确保值可以序列化
                if value is not None:
                    content[field_name] = str(value)
                else:
                    content[field_name] = None
            except Exception as e:
                logger.debug(f"获取字段 {field_name} 值时出错: {str(e)}")
                content[field_name] = None
        
        # 添加主键信息
        if hasattr(instance, 'pk'):
            content['pk'] = str(instance.pk)
        
        logger.debug(f"准备记录 {resource} 的 {action} 操作日志，内容: {content}")
        
        # 创建日志记录
        await admin_log_provider.log_model.create(
            user=user,
            content=content,
            resource=resource,
            action=action
        )
        
        logger.debug(f"成功记录 {resource} 的 {action} 操作日志")
    except Exception as e:
        logger.error(f"记录操作日志时发生错误: {str(e)}")


@router.get("/{resource}/list")
async def list_view(
    request: Request,
    model: Model = Depends(get_model),
    resources=Depends(get_resources),
    model_resource: ModelResource = Depends(get_model_resource),
    resource: str = Path(...),
    page_size: int = 10,
    page_num: int = 1,
    order_by: Optional[str] = None,
):
    fields_label = model_resource.get_fields_label()
    fields = model_resource.get_fields()
    fk_fields = model_resource.get_fk_field()
    qs = model.all()
    params, qs = await model_resource.resolve_query_params(request, dict(request.query_params), qs)
    filters = await model_resource.get_filters(request, params)
    total = await qs.count()
    if order_by:
        qs = qs.order_by(order_by)
    if page_size:
        qs = qs.limit(page_size)
    else:
        page_size = model_resource.page_size
    qs = qs.offset((page_num - 1) * page_size)
    if fk_fields:
        objects = await qs.select_related(*fk_fields)
        values = []
        for obj in objects:
            obj_as_dict = dict(obj)
            for attr in fk_fields:
                obj_as_dict[attr] = getattr(obj, attr)
            values.append(obj_as_dict)
    else:
        values = await qs.values()

    (
        rendered_values,
        row_attributes,
        column_attributes,
        cell_attributes,
    ) = await render_values(request, model_resource, fields, values)
    context = {
        "request": request,
        "resources": resources,
        "fields_label": fields_label,
        "fields": fields,
        "values": values,
        "row_attributes": row_attributes,
        "column_attributes": column_attributes,
        "cell_attributes": cell_attributes,
        "rendered_values": rendered_values,
        "filters": filters,
        "resource": resource,
        "model_resource": model_resource,
        "resource_label": model_resource.label,
        "page_size": page_size,
        "page_num": page_num,
        "total": total,
        "from": page_size * (page_num - 1) + 1,
        "to": page_size * page_num,
        "page_title": model_resource.page_title,
        "page_pre_title": model_resource.page_pre_title,
    }
    try:
        return templates.TemplateResponse(
            f"{resource}/list.html",
            context=context,
        )
    except TemplateNotFound:
        return templates.TemplateResponse(
            "list.html",
            context=context,
        )


@router.post("/{resource}/update/{pk}")
async def update(
    request: Request,
    resource: str = Path(...),
    pk: str = Path(...),
    model_resource: ModelResource = Depends(get_model_resource),
    resources=Depends(get_resources),
    model=Depends(get_model),
):
    logger.info(f"接收到更新请求: resource={resource}, pk={pk}")
    
    # 强制使用JSON格式
    content_type = request.headers.get("content-type", "")
    if "application/json" not in content_type:
        logger.error(f"请求格式错误，仅支持JSON格式: {content_type}")
        return {"status": "error", "message": "仅支持JSON格式，请设置Content-Type: application/json"}
    
    # 处理JSON数据
    try:
        logger.info("处理JSON格式更新请求")
        data, m2m_data = await model_resource.resolve_data(request, None)
    except Exception as e:
        logger.error(f"解析JSON数据失败: {str(e)}")
        return {"status": "error", "message": f"数据解析错误: {str(e)}"}
    
    # 获取要更新的对象
    try:
        obj = await model.get(pk=pk)
    except Exception as e:
        logger.error(f"获取对象失败: {str(e)}")
        return {"status": "error", "message": f"未找到ID为{pk}的对象"}
    
    # 更新对象
    try:
        await model_resource.save(request, obj, data, m2m_data=m2m_data)
        logger.info(f"成功更新对象: {resource} #{pk}")
        
        # 记录更新操作日志
        await log_admin_action(request, model, obj, "edit")
    except Exception as e:
        logger.error(f"更新对象时出错: {str(e)}")
        return {"status": "error", "message": f"更新失败: {str(e)}"}
    
    # 返回成功响应
    return {"status": "success", "message": "更新成功", "data": {"id": pk}}


@router.get("/{resource}/update/{pk}")
async def update_view(
    request: Request,
    resource: str,
    pk: str,
    model=Depends(get_model),
    model_resource=Depends(get_model_resource),
    resources=Depends(get_resources),
    admin: AbstractAdmin = Depends(get_current_user),
):
    logger.info(f"开始获取 {resource} id={pk} 数据用于编辑")
    
    # 查询对象时预加载多对多关系
    obj = None
    
    try:
        # 检查模型是否有多对多字段
        has_m2m = hasattr(model, '_meta') and hasattr(model._meta, 'm2m_fields') and model._meta.m2m_fields
        
        if has_m2m:
            # 记录多对多字段
            m2m_fields = model._meta.m2m_fields
            logger.info(f"模型 {model.__name__} 有 {len(m2m_fields)} 个多对多字段: {m2m_fields}")
            
            # 使用prefetch_related预加载所有多对多关系
            # 首先获取基本对象
            obj = await model.get(pk=pk)
            
            # 然后预加载每个多对多关系
            for field_name in m2m_fields:
                try:
                    relation = getattr(obj, field_name)
                    related_objs = await relation.all()
                    logger.info(f"预加载字段 {field_name} 成功，获取到 {len(related_objs)} 个关联对象")
                except Exception as e:
                    logger.error(f"预加载字段 {field_name} 失败: {str(e)}")
        else:
            # 没有多对多字段，直接获取对象
            obj = await model.get(pk=pk)
    except Exception as e:
        logger.error(f"获取对象失败: {str(e)}")
        raise HTTPException(status_code=404, detail=f"未找到 {resource} id={pk} 的对象")
    
    inputs = await model_resource.get_inputs(request, obj)
    
    # 对于单对象视图，我们需要重新获取操作，并传入具体对象
    try:
        # 尝试获取对象的操作
        if hasattr(model_resource.__class__, 'get_actions'):
            actions = await model_resource.__class__.get_actions(request, obj)
            setattr(model_resource, "actions", actions)
    except Exception as e:
        logger.error(f"获取对象操作时出错: {str(e)}")
        
    context = {
        "request": request,
        "resources": resources,
        "resource_label": model_resource.label,
        "resource": resource,
        "model_resource": model_resource,
        "inputs": inputs,
        "pk": pk,
        "page_title": model_resource.page_title,
        "page_pre_title": model_resource.page_pre_title,
    }
    
    try:
        return templates.TemplateResponse(
            f"{resource}/update.html",
            context=context,
        )
    except TemplateNotFound:
        return templates.TemplateResponse(
            "update.html",
            context=context,
        )


@router.get("/{resource}/create")
async def create_view(
    request: Request,
    resource: str = Path(...),
    resources=Depends(get_resources),
    model_resource: ModelResource = Depends(get_model_resource),
):
    logger.info(f"开始创建 {resource} 表单")
    
    # 获取表单输入控件
    inputs = await model_resource.get_inputs(request)
    
    # 记录表单字段信息用于调试
    field_names = []
    for input_item in inputs:
        # 安全获取字段名称
        if hasattr(input_item, 'context') and isinstance(input_item.context, dict) and 'name' in input_item.context:
            field_names.append(input_item.context.get('name'))
        elif hasattr(input_item, 'name'):
            field_names.append(input_item.name)
        else:
            field_names.append(str(type(input_item)))
            
    logger.info(f"创建表单包含 {len(inputs)} 个字段: {field_names}")
    
    context = {
        "request": request,
        "resources": resources,
        "resource_label": model_resource.label,
        "resource": resource,
        "model_resource": model_resource,
        "inputs": inputs,
        "page_title": model_resource.page_title,
        "page_pre_title": model_resource.page_pre_title,
    }
    try:
        return templates.TemplateResponse(
            f"{resource}/create.html",
            context=context,
        )
    except TemplateNotFound:
        return templates.TemplateResponse(
            "create.html",
            context=context,
        )


@router.post("/{resource}/create")
async def create(
    request: Request,
    resource: str = Path(...),
    resources=Depends(get_resources),
    model_resource: ModelResource = Depends(get_model_resource),
    model=Depends(get_model),
):
    logger.info(f"接收到创建请求: resource={resource}")
    
    # 强制使用JSON格式
    content_type = request.headers.get("content-type", "")
    if "application/json" not in content_type:
        logger.error(f"请求格式错误，仅支持JSON格式: {content_type}")
        return {"status": "error", "message": "仅支持JSON格式，请设置Content-Type: application/json"}
    
    # 处理JSON数据
    try:
        logger.info("处理JSON格式创建请求")
        data, m2m_data = await model_resource.resolve_data(request, None)
    except Exception as e:
        logger.error(f"解析JSON数据失败: {str(e)}")
        return {"status": "error", "message": f"数据解析错误: {str(e)}"}
    
    # 创建对象
    try:
        obj = await model_resource.save(request, None, data, m2m_data=m2m_data)
        logger.info(f"成功创建对象: {resource} #{obj.pk if obj else 'unknown'}")
        
        # 记录创建操作日志
        await log_admin_action(request, model, obj, "create")
    except Exception as e:
        logger.error(f"创建对象时出错: {str(e)}")
        return {"status": "error", "message": f"创建失败: {str(e)}"}
    
    # 返回成功响应
    return {"status": "success", "message": "创建成功", "data": {"id": obj.pk if obj else None}}


@router.delete("/{resource}/delete/{pk}")
async def delete(request: Request, pk: str, model: Model = Depends(get_model)):
    # 先获取对象，以便在删除前记录日志
    obj = await model.get(pk=pk)
    
    # 记录删除操作日志
    await log_admin_action(request, model, obj, "delete")
    
    # 执行删除操作
    await model.filter(pk=pk).delete()
    return RedirectResponse(url=request.headers.get("referer"), status_code=HTTP_303_SEE_OTHER)


@router.delete("/{resource}/delete")
async def bulk_delete(request: Request, ids: str, model: Model = Depends(get_model)):
    # 获取要删除的所有对象
    id_list = ids.split(",")
    objects = await model.filter(pk__in=id_list).all()
    
    # 为每个对象记录删除操作日志
    for obj in objects:
        await log_admin_action(request, model, obj, "delete")
    
    # 执行批量删除操作
    await model.filter(pk__in=id_list).delete()
    return RedirectResponse(url=request.headers.get("referer"), status_code=HTTP_303_SEE_OTHER)
