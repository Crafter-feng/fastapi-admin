from typing import Any, Dict, List, Optional, Tuple, Type, Union

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


class ComputeField(Field):
    async def get_value(self, request: Request, obj: dict):
        return obj.get(self.name)


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
    fields: List[Union[str, Field, ComputeField]] = []
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
        # 默认返回空字典，子类可扩展此方法
        return {}
        
    @classmethod
    async def save(cls, request: Request, obj, data, **kwargs):
        """保存模型实例，处理一对多和多对多关系
        
        Args:
            request: HTTP请求对象
            obj: 模型实例，为None时表示创建新实例
            data: 要保存的数据字典
            **kwargs: 其他参数
            
        Returns:
            保存后的模型实例
        """
        m2m_data = kwargs.get('m2m_data', {})
        
        if obj:
            # 更新现有实例
            await obj.update_from_dict(data).save()
            saved_obj = obj
        else:
            # 创建新实例
            saved_obj = await cls.model.create(**data)
        
        # 处理多对多关系
        if m2m_data and saved_obj:
            for field_name, related_objects in m2m_data.items():
                if hasattr(saved_obj, field_name):
                    relation = getattr(saved_obj, field_name)
                    
                    try:
                        # 清除现有关联
                        await relation.clear()
                        
                        # 添加新关联
                        if related_objects:
                            for rel_obj in related_objects:
                                await relation.add(rel_obj)
                            
                            logger.debug(f"为 {cls.model.__name__} #{saved_obj.pk} 更新 {field_name} 关系: 添加 {len(related_objects)} 个对象")
                    except Exception as e:
                        logger.error(f"更新多对多关系 {field_name} 失败: {str(e)}")
        
        return saved_obj
            
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
        
        ret = []
        for field in cls.get_fields(is_display=False):
            input_ = field.input
            name = input_.context.get("name")
            # 如果该字段在全局排除列表中，则跳过
            if name in cls.exclude_fields:
                continue
            # 如果该字段在编辑排除列表中且存在对象（编辑模式），则跳过
            if name in cls.exclude_fields_on_edit and obj is not None:
                continue
            if isinstance(input_, inputs.DisplayOnly):
                continue
            if isinstance(input_, inputs.File):
                cls.enctype = "multipart/form-data"
            if (
                isinstance(input_, inputs.ForeignKey)
                and (obj is not None)
                and name in obj._meta.fk_fields
            ):
                await obj.fetch_related(name)
                # Value must be the string representation of the fk obj
                value = str(getattr(obj, name, None))
                ret.append(await input_.render(request, value))
                continue
            
            # 处理多对多关系
            if (
                obj is not None
                and hasattr(obj._meta, "m2m_fields")
                and name in obj._meta.m2m_fields
            ):
                # 确保先加载关联数据
                try:
                    # 获取ManyToManyRelation对象
                    value = getattr(obj, name)
                    # 直接将关系对象传递给render方法处理
                    ret.append(await input_.render(request, value))
                    continue
                except Exception as e:
                    logger.error(f"加载多对多关系 {name} 失败: {str(e)}")
            
            ret.append(await input_.render(request, getattr(obj, name, None)))

        # 处理自定义表单字段
        if hasattr(request.state, "form_init"):
            for field_name, field_data in request.state.form_init.items():
                # 只处理有options属性的字段，这些通常是下拉菜单或多选框
                if "options" in field_data and isinstance(field_data["options"], list):
                    # 检查是否已存在该字段（确保比较的对象是Field类型）
                    existing_field = False
                    for item in ret:
                        # 检查item是否为Field对象或者字符串对象
                        if hasattr(item, 'name') and item.name == field_name:
                            existing_field = True
                            break
                        elif isinstance(item, str) and field_name in item:
                            existing_field = True
                            break
                    
                    if not existing_field:
                        # 创建多选组件
                        from fastapi_admin.widgets.inputs import MultiSelect
                        
                        # 获取选中项
                        selected = field_data.get("selected", [])
                        
                        # 创建输入控件
                        input_widget = MultiSelect(
                            options=field_data["options"],
                            label=field_name.title(),
                            placeholder="请选择" + field_name.title()
                        )
                        input_widget.context.update(name=field_name)
                        
                        # 添加到返回列表
                        rendered = await input_widget.render(request, selected)
                        ret.append(rendered)
        
        return ret

    @classmethod
    async def resolve_query_params(cls, request: Request, values: dict, qs: QuerySet):
        ret = {}
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
        m2m_ret = {}
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
            if isinstance(input_, inputs.ForeignKey):
                v = data.getlist(name)[0]
                ret[name] = int(v) if v else None
                continue
            if isinstance(input_, inputs.ManyToMany):
                v = data.getlist(name)
                value = await input_.parse_value(request, v)
                m2m_ret[name] = await input_.model.filter(pk__in=value)
                continue
            if isinstance(input_, inputs.MultiSelect):
                # 获取多选值，可能是列表或字符串
                values = data.getlist(name)
                # 从自定义字段中获取值
                if not values and name in custom_fields:
                    values = custom_fields[name]
                
                if not values:
                    values = []
                elif len(values) == 1 and values[0] == '':
                    values = []
                
                # 处理多选值
                parsed_values = await input_.parse_value(request, values)
                
                # 如果字段是模型中的多对多字段，则处理多对多关系
                if name in cls.model._meta.m2m_fields:
                    # 确保parsed_values是列表，即使是空列表
                    if not parsed_values:
                        parsed_values = []
                    
                    related_model = cls.model._meta.fields_map[name].related_model
                    m2m_ret[name] = await related_model.filter(pk__in=parsed_values)
                else:
                    # 否则作为普通字段处理
                    ret[name] = parsed_values
                continue
            else:
                v = data.get(name)
                value = await input_.parse_value(request, v)
                if value is None:
                    continue
                ret[name] = value
        
        # 处理表单中的非模型字段，记得移除当前方法上半部分已处理的自定义字段
        # 以及确保roles和permissions使用自定义字段处理
        for name, value in data.items():
            if (name not in ret and name not in m2m_ret and 
                name != "save" and name != "saveandedit" and 
                name not in custom_fields and not name.endswith('[]')):
                # 处理特殊字段：roles和permissions
                if name in ['roles', 'permissions']:
                    # 这些字段应该由自定义字段处理，记录一个警告
                    logger.warning(f"字段 {name} 应该由自定义字段处理，但未被处理")
                    continue
                
                # 检查是否是多值字段
                values = data.getlist(name)
                if len(values) > 1:
                    # 将多个值作为列表保存
                    parsed_values = [int(v) if v.isdigit() else v for v in values if v]
                    
                    # 检查是否是多对多字段
                    if cls.model and hasattr(cls.model, '_meta') and name in cls.model._meta.m2m_fields:
                        related_model = cls.model._meta.fields_map[name].related_model
                        m2m_ret[name] = await related_model.filter(pk__in=parsed_values)
                    else:
                        ret[name] = parsed_values
                else:
                    # 单个值直接保存
                    if value:
                        ret[name] = int(value) if value.isdigit() else value
        
        return ret, m2m_ret

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
            display, input_ = displays.InputOnly(), inputs.ManyToMany(field.related_model)
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
            if isinstance(field, ComputeField) and not is_display:
                continue
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
            if isinstance(field, ComputeField):
                v = await field.get_value(request, value)
            else:
                v = value.get(field.name)
            cell_item.append(await model.cell_attributes(request, value, field))
            if display:
                item.append(await field.display.render(request, v))
            else:
                item.append(await field.input.render(request, v))
        ret.append(item)
        cell_attributes.append(cell_item)
    return ret, row_attributes, column_attributes, cell_attributes
