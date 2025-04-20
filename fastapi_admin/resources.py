from typing import Any, Dict, List, Optional, Tuple, Type, Union
import json
import inspect

from pydantic import BaseModel, validator
from starlette.datastructures import FormData
from starlette.requests import Request
from tortoise import ForeignKeyFieldInstance, ManyToManyFieldInstance
from tortoise import Model as TortoiseModel
from tortoise.fields import BooleanField, DateField, DatetimeField, JSONField
from tortoise.fields.data import CharEnumFieldInstance, IntEnumFieldInstance, IntField, TextField
from tortoise.queryset import QuerySet

from fastapi_admin.enums import Method
from fastapi_admin.exceptions import NoSuchFieldFound
from fastapi_admin.i18n import _
from fastapi_admin.widgets import Widget, displays, inputs
from fastapi_admin.widgets.filters import Filter, Search
from fastapi_admin.utils.logger import logger

class Resource:
    """
    Base Resource
    """

    label: str
    icon: str = ""


class Link(Resource):
    url: str
    target: str = "_self"


class Field:
    name: str
    label: str
    display: displays.Display
    input: inputs.Input

    def __init__(
        self,
        name: str,
        label: Optional[str] = None,
        display: Optional[displays.Display] = None,
        input_: Optional[Widget] = None,
    ):
        self.name = name
        self.label = label or name.title()
        if not display:
            display = displays.Display()
        display.context.update(label=self.label)
        self.display = display
        if not input_:
            input_ = inputs.Input()
        input_.context.update(label=self.label, name=name)
        self.input = input_


class Action(BaseModel):
    icon: str
    label: str
    name: str
    method: Method = Method.POST
    ajax: bool = True

    @validator("ajax")
    def ajax_validate(cls, v: bool, values: dict, **kwargs):
        if not v and values["method"] != Method.GET:
            raise ValueError("ajax is False only available when method is Method.GET")


class ToolbarAction(Action):
    class_: Optional[str]


class Model(Resource):
    model: Type[TortoiseModel]
    fields: List[Union[str, Field]] = []
    page_size: int = 10
    page_pre_title: Optional[str] = None
    page_title: Optional[str] = None
    filters: List[Union[str, Filter]] = []
    exclude_fields_on_edit: List[str] = []  # 编辑页面需要排除的字段列表，这些字段在编辑时不会显示，但在创建时仍会显示
    exclude_fields: List[str] = []  # 需要排除的字段列表，这些字段在编辑和创建时都不会显示

    @classmethod
    async def get_bulk_actions(cls, request: Request) -> List[Action]:
        return [
            Action(
                label=_("delete_selected"),
                icon="ti ti-trash",
                name="delete",
                method=Method.DELETE,
            ),
        ]

    @classmethod
    async def get_toolbar_actions(cls, request: Request) -> List[ToolbarAction]:
        return [
            ToolbarAction(
                label=_("create"),
                icon="fas fa-plus",
                name="create",
                method=Method.GET,
                ajax=False,
                class_="btn-dark",
            )
        ]

    async def row_attributes(self, request: Request, obj: dict) -> dict:
        return {}

    async def column_attributes(self, request: Request, field: Field) -> dict:
        return {}

    async def cell_attributes(self, request: Request, obj: dict, field: Field) -> dict:
        return {}

    @classmethod
    async def get_actions(cls, request: Request, obj=None) -> List[Action]:
        """获取对象操作列表
        
        Args:
            request: 请求对象
            obj: 可选，当前操作的对象实例。在列表视图中可能为None
            
        Returns:
            操作列表
        """
        return [
            Action(
                label=_("update"), icon="ti ti-edit", name="update", method=Method.GET, ajax=False
            ),
            Action(label=_("delete"), icon="ti ti-trash", name="delete", method=Method.DELETE),
        ]

    @classmethod
    async def get_form_init(cls, request: Request, obj=None):
        """获取表单初始化数据，可被子类重写以提供额外数据
        
        Args:
            request: HTTP请求对象
            obj: 可选的模型实例，在编辑模式下提供
            
        Returns:
            包含表单初始化数据的字典
        """
        # 初始化表单数据字典
        form_init = {}
        
        # 记录日志
        if obj:
            logger.info(f"初始化表单数据，模型: {cls.model.__name__}, 对象ID: {obj.pk}")
        else:
            logger.info(f"初始化表单数据，模型: {cls.model.__name__}, 创建新对象")
        
        # 获取模型中定义的关联字段
        if not hasattr(cls.model, '_meta'):
            return form_init
            
        meta = cls.model._meta
        
        try:
            # 获取模型中定义的关联字段
            relation_fields = await cls._detect_relation_fields(meta)
            
            # 处理关联字段
            for field_name, field_info in relation_fields.items():
                # 跳过那些可能已经被排除的字段
                if field_name in cls.exclude_fields:
                    logger.info(f"字段 {field_name} 在排除列表中，跳过")
                    continue
                    
                if obj and field_name in cls.exclude_fields_on_edit:
                    logger.info(f"字段 {field_name} 在编辑排除列表中，跳过")
                    continue
                
                # 获取关联模型
                related_model = field_info["model"]
                logger.info(f"处理关联字段: {field_name} -> {related_model.__name__}")
                
                # 初始化字段配置
                if field_name not in form_init:
                    form_init[field_name] = {}
                
                # 获取已选中的项（编辑模式）
                selected_items = []
                if obj and hasattr(obj, field_name):
                    selected_items = await cls._get_related_items(obj, field_name, field_info)
                    
                    # 标记已选中的值
                    if selected_items:
                        selected_ids = [str(getattr(item, "pk")) for item in selected_items]
                        form_init[field_name]["selected"] = selected_ids
                        logger.info(f"已选中的 {field_name} IDs: {selected_ids}")
                
                # 获取选项列表
                options = []
                if selected_items:
                    # 显示已关联的对象
                    options = await cls._format_options(selected_items)
                    logger.info(f"查看模式: {field_name} 显示 {len(options)} 个已关联选项")
                else:
                    # 获取所有可选项
                    options = await cls._get_all_options(related_model)
                    logger.info(f"为 {field_name} 添加 {len(options)} 个选项")
                
                form_init[field_name]["options"] = options
            
        except Exception as e:
            logger.error(f"自动检测关联字段失败: {str(e)}")
        
        return form_init
    
    @classmethod
    async def _detect_relation_fields(cls, meta):
        """检测模型中的关联字段
        
        Args:
            meta: 模型元数据
            
        Returns:
            关联字段字典 {字段名: 字段信息}
        """
        relation_fields = {}
        
        # 1. 处理多对多字段
        if hasattr(meta, 'm2m_fields'):
            for field_name in meta.m2m_fields:
                field_obj = meta.fields_map.get(field_name)
                if field_obj and hasattr(field_obj, 'related_model'):
                    relation_fields[field_name] = {
                        "model": field_obj.related_model,
                        "is_many_to_many": True
                    }
                    logger.info(f"检测到多对多字段: {field_name} -> {field_obj.related_model.__name__}")
        
        # 2. 处理外键字段
        if hasattr(meta, 'fk_fields'):
            for field_name in meta.fk_fields:
                field_obj = meta.fields_map.get(field_name)
                if field_obj and hasattr(field_obj, 'related_model'):
                    relation_fields[field_name] = {
                        "model": field_obj.related_model,
                        "is_foreign_key": True
                    }
                    logger.info(f"检测到外键字段: {field_name} -> {field_obj.related_model.__name__}")
        
        return relation_fields
    
    @classmethod
    async def _get_related_items(cls, obj, field_name, field_info):
        """获取对象的关联项
        
        Args:
            obj: 模型实例
            field_name: 字段名
            field_info: 字段信息字典
            
        Returns:
            关联项列表
        """
        selected_items = []
        try:
            # 确保关联数据已加载
            await obj.fetch_related(field_name)
            logger.debug(f"已加载对象 {obj.__class__.__name__} #{obj.pk} 的关联数据 {field_name}")
            
            # 处理不同类型的关系
            if field_info.get("is_foreign_key", False):
                # 外键关系是一对多
                related_item = getattr(obj, field_name)
                selected_items = [related_item] if related_item else []
            else:
                # 多对多关系
                relation = getattr(obj, field_name)
                
                try:
                    # 标准方式
                    selected_items = await relation.all()
                except Exception as e1:
                    logger.error(f"使用relation.all()获取关联对象失败: {str(e1)}")
                    # 尝试其他方式
                    if hasattr(relation, "related_objects"):
                        selected_items = relation.related_objects
                    elif hasattr(relation, "_fetch_instance_attr"):
                        try:
                            # 尝试加载关联的属性
                            selected_items = await relation._fetch_instance_attr()
                        except Exception as e2:
                            logger.error(f"使用_fetch_instance_attr方法获取关联对象失败: {str(e2)}")
                    else:
                        logger.warning(f"无法获取多对多关系 {field_name} 的关联对象")
                        selected_items = []
            
            # 记录关联项信息
            if selected_items:
                logger.info(f"模型 {obj.__class__.__name__} #{obj.pk} 的 {field_name} 关联项数量: {len(selected_items)}")
            else:
                logger.warning(f"对象 {obj.__class__.__name__} #{obj.pk} 的 {field_name} 关联项为空")
                
        except Exception as e:
            logger.error(f"获取对象 {obj.__class__.__name__} #{obj.pk} 的 {field_name} 关联项失败: {str(e)}")
            
        return selected_items
    
    @classmethod
    async def _format_options(cls, items):
        """将模型实例列表格式化为选项列表
        
        Args:
            items: 模型实例列表
            
        Returns:
            格式化后的选项列表 [{"value": "1", "label": "Option 1"}, ...]
        """
        options = []
        for item in items:
            # 获取合适的显示属性
            display_value = None
            for attr in ["label", "name", "title", "display_name", "username", "email"]:
                if hasattr(item, attr):
                    display_value = getattr(item, attr)
                    break
            
            if display_value is None:
                display_value = str(item)
            
            # 添加选项
            options.append({
                "value": str(item.pk),
                "label": str(display_value)
            })
            
        return options
    
    @classmethod
    async def _get_all_options(cls, model):
        """获取模型的所有选项
        
        Args:
            model: 模型类
            
        Returns:
            格式化后的选项列表
        """
        try:
            # 获取所有对象
            objects = await model.all()
            logger.info(f"获取到 {len(objects)} 个 {model.__name__} 对象")
            
            if not objects:
                logger.warning(f"没有找到任何 {model.__name__} 对象! 将使用空选项列表。")
                return []
            
            # 选择显示属性
            display_attr = "pk"
            common_attrs = ["label", "name", "title", "display_name", "username", "email"]
            for attr in common_attrs:
                if all(hasattr(item, attr) for item in objects):
                    display_attr = attr
                    logger.info(f"选择显示属性: {attr}")
                    break
            
            # 构建选项列表
            options = []
            for item in objects:
                display_value = getattr(item, display_attr, str(item))
                options.append({
                    "value": str(item.pk),
                    "label": str(display_value)
                })
                
            return options
            
        except Exception as e:
            logger.error(f"获取 {model.__name__} 所有对象失败: {str(e)}")
            return []
    
    @classmethod
    def _get_relation_field_map(cls, meta):
        """获取关联字段映射
        
        Args:
            meta: 模型元数据
            
        Returns:
            关联字段映射 {字段名: 是否为外键}
        """
        relation_field_map = {}
        
        # 添加多对多字段
        if hasattr(meta, 'm2m_fields'):
            for field_name in meta.m2m_fields:
                relation_field_map[field_name] = False  # 多对多关系
                
        # 添加外键字段
        if hasattr(meta, 'fk_fields'):
            for field_name in meta.fk_fields:
                relation_field_map[field_name] = True  # 外键关系
                
        return relation_field_map
        
    @classmethod
    def _should_exclude_field(cls, name, obj):
        """判断字段是否应该被排除
        
        Args:
            name: 字段名
            obj: 模型实例，编辑模式下不为None
            
        Returns:
            是否应该排除
        """
        # 如果该字段在全局排除列表中，则跳过
        if name in cls.exclude_fields:
            return True
                
        # 如果该字段在编辑排除列表中且存在对象（编辑模式），则跳过
        if name in cls.exclude_fields_on_edit and obj is not None:
            return True
            
        return False
    
    @classmethod
    async def _render_multi_select(cls, name, label, options, selected, request, ret):
        """渲染多选控件
        
        Args:
            name: 字段名
            label: 字段标签
            options: 选项列表
            selected: 已选项列表
            request: 请求对象
            ret: 结果列表，渲染结果将添加到此列表
            
        Returns:
            是否成功渲染
        """
        multi_select = inputs.MultiSelect(
            options=options,
            label=label,
            placeholder=_("Please select") if "{field}" not in _("Please select {field}") else _("Please select {field}").format(field=label)
        )
        
        multi_select.context.update(name=name)
        
        try:
            rendered = await multi_select.render(request, selected)
            ret.append(rendered)
            logger.info(f"成功渲染多选字段 {name}, 选项数量: {len(options)}")
            return True
        except Exception as e:
            logger.error(f"渲染多选字段 {name} 失败: {str(e)}")
            return False
    
    @classmethod
    async def _handle_many_to_many_field(cls, name, field, form_init, request, ret):
        """处理多对多字段
        
        Args:
            name: 字段名
            field: 字段对象
            form_init: 表单初始化数据
            request: 请求对象
            ret: 返回列表，处理结果将添加到此列表
        """
        # 检查form_init中是否有该字段的选项和选中值
        field_options = []
        field_selected = []
        if name in form_init:
            field_data = form_init[name]
            field_options = field_data.get("options", [])
            field_selected = field_data.get("selected", [])
        
        # 使用共享的渲染方法
        await cls._render_multi_select(
            name=name,
            label=field.label,
            options=field_options,
            selected=field_selected,
            request=request,
            ret=ret
        )
            
    @classmethod
    async def _handle_custom_fields(cls, request, form_init, ret):
        """处理自定义表单字段
        
        Args:
            request: 请求对象 
            form_init: 表单初始化数据
            ret: 返回列表，处理结果将添加到此列表
        """
        if not hasattr(request.state, "form_init"):
            return
            
        for field_name, field_data in request.state.form_init.items():
            # 只处理有options属性的字段，这些通常是下拉菜单或多选框
            if "options" not in field_data or not isinstance(field_data["options"], list):
                continue
                
            # 检查是否已存在该字段
            existing_field = False
            for item in ret:
                # 检查item是否为字典或字符串
                if hasattr(item, 'name') and item.name == field_name:
                    existing_field = True
                    break
                elif isinstance(item, str) and field_name in item:
                    existing_field = True
                    break
            
            if existing_field:
                continue
                
            logger.info(f"添加自定义表单字段: {field_name}")
            
            # 获取选中项和选项
            selected = field_data.get("selected", [])
            options = field_data.get("options", [])
            
            logger.info(f"自定义字段 {field_name}: 选项数量 {len(options)}, 选中项数量 {len(selected)}")
            
            # 使用共享的渲染方法
            await cls._render_multi_select(
                name=field_name,
                label=field_name.title(),
                options=options,
                selected=selected,
                request=request,
                ret=ret
            )
                
    @classmethod
    def _is_foreign_key_field(cls, input_, obj, name, meta):
        """判断是否为外键字段
        
        Args:
            input_: 输入控件
            obj: 模型实例
            name: 字段名
            meta: 模型元数据
            
        Returns:
            是否为外键字段
        """
        return (
            isinstance(input_, inputs.ForeignKey)
            and (obj is not None)
            and meta 
            and hasattr(meta, 'fk_fields')
            and name in meta.fk_fields
        )

    @classmethod
    async def get_inputs(cls, request: Request, obj: Optional[TortoiseModel] = None):
        """
        获取表单输入控件列表
        
        Args:
            request: HTTP请求对象
            obj: 可选的模型实例，在编辑模式下提供
            
        Returns:
            表单输入控件列表
        """
        # 获取表单初始化数据
        form_init = await cls.get_form_init(request, obj)
        # 将表单初始化数据存储在请求状态中
        request.state.form_init = form_init
        
        # 获取模型元数据
        meta = getattr(cls.model, '_meta', None)
        logger.info(f"为模型 {cls.model.__name__} 获取输入控件，{'编辑' if obj else '创建'}模式")
        
        # 获取关联字段映射
        relation_field_map = cls._get_relation_field_map(meta) if meta else {}
        logger.info(f"检测到的关联字段: {relation_field_map}")
        
        ret = []
        for field in cls.get_fields(is_display=False):
            input_ = field.input
            name = input_.context.get("name")
            logger.debug(f"处理字段: {name}, 类型: {type(input_).__name__}")
            
            # 检查是否排除
            if cls._should_exclude_field(name, obj):
                logger.debug(f"字段 {name} 在排除列表中，跳过")
                continue
            
            if isinstance(input_, inputs.DisplayOnly):
                logger.debug(f"字段 {name} 是只读字段，跳过")
                continue
                
            if isinstance(input_, inputs.File):
                cls.enctype = "multipart/form-data"
                logger.debug(f"字段 {name} 是文件上传字段")
                
            # 处理外键关系
            if cls._is_foreign_key_field(input_, obj, name, meta):
                logger.debug(f"处理外键字段 {name}")
                await obj.fetch_related(name)
                value = getattr(obj, name, None)
                ret.append(await input_.render(request, value))
                continue
            
            # 处理多对多关系
            if name in relation_field_map and not relation_field_map[name]:  # 不是外键
                await cls._handle_many_to_many_field(name, field, form_init, request, ret)
                continue
            
            # 处理外键关系
            if name in relation_field_map and relation_field_map[name]:  # 是外键
                logger.debug(f"处理外键字段 {name}")
                if obj is not None:
                    await obj.fetch_related(name)
                    value = getattr(obj, name, None)
                    ret.append(await input_.render(request, value))
                    continue
            
            # 普通字段处理
            try:
                rendered = await input_.render(request, getattr(obj, name, None))
                ret.append(rendered)
                logger.debug(f"成功渲染普通字段 {name}")
            except Exception as e:
                logger.error(f"渲染字段 {name} 失败: {str(e)}")

        # 处理自定义表单字段
        await cls._handle_custom_fields(request, form_init, ret)
        
        return ret

    @classmethod
    async def resolve_query_params(cls, request: Request, values: dict, qs: QuerySet):
        ret = {}
        if values is None:
            values = {}
            
        for f in cls.filters:
            if isinstance(f, str):
                f = Search(name=f, label=f.title())
            name = f.context.get("name")
            v = values.get(name)
            if v is not None and v != "":
                ret[name] = await f.parse_value(request, v)
                qs = await f.get_queryset(request, v, qs)
        return ret, qs

    @classmethod
    async def resolve_data(cls, request: Request, data: FormData):
        ret = {}
        # 检查是否在编辑模式
        path = request.url.path
        is_update = '/update/' in path
        
        # 处理自定义表单字段，如角色和权限
        custom_fields = {}
        for name, values in data.multi_items():
            if name.endswith('[]'):
                base_name = name[:-2]
                if base_name not in custom_fields:
                    custom_fields[base_name] = []
                custom_fields[base_name].append(values)
        
        # 获取模型元数据
        meta = getattr(cls.model, '_meta', None)
        
        # 自动检测关联字段
        m2m_fields = set()
        fk_fields = set()
        if meta:
            if hasattr(meta, 'm2m_fields'):
                m2m_fields.update(meta.m2m_fields)
            if hasattr(meta, 'fk_fields'):
                fk_fields.update(meta.fk_fields)
        
        for field in cls.get_fields(is_display=False):
            input_ = field.input
            if input_.context.get("disabled") or isinstance(input_, inputs.DisplayOnly):
                continue
            name = input_.context.get("name")
            # 如果在全局排除列表中，则跳过
            if name in cls.exclude_fields:
                continue
            # 如果在编辑模式下且字段在编辑排除列表中，则跳过
            if is_update and name in cls.exclude_fields_on_edit:
                continue
                
            # 处理外键字段
            if name in fk_fields or isinstance(input_, inputs.ForeignKey):
                v = data.getlist(name)[0] if data.getlist(name) else None
                ret[name] = int(v) if v and v.isdigit() else None
                continue
                
            # 处理多对多字段和多选字段
            if name in m2m_fields or isinstance(input_, inputs.MultiSelect):
                # 获取多选值
                values = data.getlist(name)
                
                # 从自定义字段中获取值
                if not values and name in custom_fields:
                    values = custom_fields[name]
                    
                # 空值处理
                if not values:
                    values = []
                elif len(values) == 1 and values[0] == '':
                    values = []
                
                # 处理值列表，确保正确格式
                parsed_values = []
                for val in values:
                    if isinstance(val, list):
                        # 如果已经是列表，展平它
                        parsed_values.extend(val)
                    else:
                        # 单个值直接添加
                        parsed_values.append(val)
                
                # 过滤掉空值
                parsed_values = [v for v in parsed_values if v]
                
                # 如果有值，尝试使用MultiSelect的parse_value方法
                if parsed_values and isinstance(input_, inputs.MultiSelect):
                    try:
                        ret[name] = await input_.parse_value(request, parsed_values)
                    except Exception:
                        # 如果解析失败，直接使用原始值
                        ret[name] = parsed_values
                else:
                    # 直接使用过滤后的值列表
                    ret[name] = parsed_values
                    
                continue
                
            # 处理标准字段
            v = data.get(name)
            value = await input_.parse_value(request, v)
            if value is None:
                continue
            ret[name] = value
        
        # 处理表单中的非模型字段
        for name, value in data.items():
            if (name not in ret and name != "save" and name != "saveandedit" and 
                name not in custom_fields and not name.endswith('[]')):
                
                # 检查是否是多值字段
                values = data.getlist(name)
                if len(values) > 1:
                    # 将多个值作为列表保存
                    parsed_values = [int(v) if v.isdigit() else v for v in values if v]
                    ret[name] = parsed_values
                else:
                    # 单个值直接保存
                    if value:
                        ret[name] = int(value) if value.isdigit() else value
        
        return ret, {}

    @classmethod
    async def get_filters(cls, request: Request, values: Optional[dict] = None):
        if not values:
            values = {}
        ret = []
        for f in cls.filters:
            if isinstance(f, str):
                f = Search(name=f, label=f.title())
            name = f.context.get("name")
            value = values.get(name)
            ret.append(await f.render(request, value))
        return ret

    @classmethod
    def _get_fields_attr(cls, attr: str, display: bool = True):
        ret = []
        for field in cls.get_fields():
            if display and isinstance(field.display, displays.InputOnly):
                continue
            ret.append(getattr(field, attr))
        return ret or cls.model._meta.db_fields

    @classmethod
    def get_fields_name(cls, display: bool = True):
        return cls._get_fields_attr("name", display)

    @classmethod
    def _get_display_input_field(cls, field_name: str) -> Field:
        fields_map = cls.model._meta.fields_map
        field = fields_map.get(field_name)
        if not field:
            raise NoSuchFieldFound(f"Can't found field '{field_name}' in model {cls.model}")
        label = field_name
        null = field.null
        placeholder = field.description or ""
        display, input_ = displays.Display(), inputs.Input(
            placeholder=placeholder, null=null, default=field.default
        )
        logger.info(f"field: {field} type: {type(field)}")

        if field.pk or field.generated:
            display, input_ = displays.Display(), inputs.DisplayOnly()
        elif isinstance(field, BooleanField):
            display, input_ = displays.Boolean(), inputs.Switch(null=null, default=field.default)
        elif isinstance(field, DatetimeField):
            if field.auto_now or field.auto_now_add:
                input_ = inputs.DisplayOnly()
            else:
                input_ = inputs.DateTime(null=null, default=field.default)
            display, input_ = displays.DatetimeDisplay(), input_
        elif isinstance(field, DateField):
            display, input_ = displays.DateDisplay(), inputs.Date(null=null, default=field.default)
        elif isinstance(field, IntEnumFieldInstance):
            display, input_ = displays.Display(), inputs.Enum(
                field.enum_type, null=null, default=field.default
            )
        elif isinstance(field, CharEnumFieldInstance):
            display, input_ = displays.Display(), inputs.Enum(
                field.enum_type, enum_type=str, null=null, default=field.default
            )
        elif isinstance(field, JSONField):
            display, input_ = displays.Json(), inputs.Json(null=null)
        elif isinstance(field, TextField):
            display, input_ = displays.Display(), inputs.TextArea(
                placeholder=placeholder, null=null, default=field.default
            )
        elif isinstance(field, IntField):
            display, input_ = displays.Display(), inputs.Number(
                placeholder=placeholder, null=null, default=field.default
            )
        elif isinstance(field, ForeignKeyFieldInstance):
            display, input_ = displays.Display(), inputs.ForeignKey(
                field.related_model, null=null, default=field.default
            )
            field_name = field.source_field
        elif isinstance(field, ManyToManyFieldInstance):
            display, input_ = displays.InputOnly(), inputs.MultiSelect(
                options=[], 
                label=_(label),
                placeholder=_("Please select1")
            )
        logger.info(f"field_name: {field_name} label: {label} display: {display} input_: {input_}")
        return Field(name=field_name, label=_(label), display=display, input_=input_)

    @classmethod
    def get_fields(cls, is_display: bool = True):
        ret = []
        pk_column = cls.model._meta.db_pk_column
        for field in cls.fields or cls.model._meta.fields:
            if isinstance(field, str):
                if field == pk_column:
                    continue
                field = cls._get_display_input_field(field)
            elif isinstance(field, Field):
                if field.name == pk_column:
                    continue
                if (is_display and isinstance(field.display, displays.InputOnly)) or (
                    not is_display and isinstance(field.input, inputs.DisplayOnly)
                ):
                    continue
            if (
                field.name in cls.model._meta.fetch_fields
                and field.name not in cls.model._meta.fk_fields | cls.model._meta.m2m_fields
            ):
                continue
            ret.append(field)
        ret.insert(0, cls._get_display_input_field(pk_column))
        return ret

    @classmethod
    def get_fields_label(cls, display: bool = True):
        return cls._get_fields_attr("label", display)

    @classmethod
    def get_m2m_field(cls):
        ret = []
        for field in cls.fields or cls.model._meta.fields:
            if isinstance(field, Field):
                field = field.name
            if field in cls.model._meta.m2m_fields:
                ret.append(field)
        return ret

    @classmethod
    def get_fk_field(cls):
        ret = []
        for field in cls.fields or cls.model._meta.fields:
            if isinstance(field, Field):
                field = field.name
            if field in cls.model._meta.fk_fields:
                ret.append(field)
        return ret


class Dropdown(Resource):
    resources: List[Type[Resource]]


async def render_values(
    request: Request,
    model: "Model",
    fields: List["Field"],
    values: List[Dict[str, Any]],
    display: bool = True,
) -> Tuple[List[List[Any]], List[dict], List[dict], List[List[dict]]]:
    """
    render values with template render
    :params model:
    :params request:
    :params fields:
    :params values:
    :params display:
    :params request:
    :params model:
    :return:
    """
    ret = []
    cell_attributes: List[List[dict]] = []
    row_attributes: List[dict] = []
    column_attributes: List[dict] = []
    for field in fields:
        column_attributes.append(await model.column_attributes(request, field))
    for value in values:
        row_attributes.append(await model.row_attributes(request, value))
        item = []
        cell_item = []
        for field in fields:
            v = value.get(field.name)
            cell_item.append(await model.cell_attributes(request, value, field))
            if display:
                item.append(await field.display.render(request, v))
            else:
                item.append(await field.input.render(request, v))
        ret.append(item)
        cell_attributes.append(cell_item)
    return ret, row_attributes, column_attributes, cell_attributes

def debug_dump_object(obj, max_depth=2, current_depth=0):
    """调试函数，用于打印对象结构
    
    Args:
        obj: 要打印的对象
        max_depth: 最大递归深度
        current_depth: 当前递归深度
        
    Returns:
        对象的字符串表示
    """
    indent = "  " * current_depth
    result = []
    
    if current_depth >= max_depth:
        return f"{type(obj).__name__}(...)"
        
    if obj is None:
        return "None"
    
    if isinstance(obj, (str, int, float, bool)):
        return str(obj)
        
    if isinstance(obj, (list, tuple)):
        if not obj:
            return "[]"
        items = []
        for i, item in enumerate(obj[:5]):  # 只显示前5个元素
            items.append(f"{indent}  {i}: {debug_dump_object(item, max_depth, current_depth+1)}")
        if len(obj) > 5:
            items.append(f"{indent}  ... ({len(obj)} items total)")
        return f"[\n{', '.join(items)}\n{indent}]"
    
    if isinstance(obj, dict):
        if not obj:
            return "{}"
        items = []
        for k, v in list(obj.items())[:5]:  # 只显示前5个键值对
            items.append(f"{indent}  {k}: {debug_dump_object(v, max_depth, current_depth+1)}")
        if len(obj) > 5:
            items.append(f"{indent}  ... ({len(obj)} items total)")
        return f"{{\n{', '.join(items)}\n{indent}}}"
    
    # 处理其他类型的对象
    try:
        # 获取对象的所有属性
        attrs = {}
        for name in dir(obj):
            if name.startswith('_'):
                continue
                
            try:
                attr = getattr(obj, name)
                # 排除方法和内置属性
                if not inspect.ismethod(attr) and not inspect.isfunction(attr):
                    attrs[name] = attr
            except Exception:
                attrs[name] = "<error>"
                
        # 只显示前5个属性
        items = []
        for k, v in list(attrs.items())[:5]:
            items.append(f"{indent}  {k}: {debug_dump_object(v, max_depth, current_depth+1)}")
        if len(attrs) > 5:
            items.append(f"{indent}  ... ({len(attrs)} attrs total)")
            
        return f"{type(obj).__name__}{{\n{', '.join(items)}\n{indent}}}"
    except Exception as e:
        return f"{type(obj).__name__}(<error: {e}>)"
