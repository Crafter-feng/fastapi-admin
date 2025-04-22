import abc
import json
from enum import Enum as EnumCLS
from typing import Any, List, Optional, Tuple, Type

from starlette.datastructures import UploadFile
from starlette.requests import Request
from tortoise import Model

from fastapi_admin.file_upload import FileUpload
from fastapi_admin.widgets import Widget
from fastapi_admin.utils.logger import logger

class Input(Widget):
    template = "widgets/inputs/input.html"

    def __init__(
        self, help_text: Optional[str] = None, default: Any = None, null: bool = False, **context
    ):
        super().__init__(null=null, help_text=help_text, **context)
        self.default = default

    async def parse_value(self, request: Request, value: Any):
        """
        Parse value from frontend
        :param value:
        :return:
        """
        return value

    async def render(self, request: Request, value: Any):
        if value is None:
            value = self.default
        return await super(Input, self).render(request, value)


class DisplayOnly(Input):
    """
    Only display without input in edit or create
    """


class Text(Input):
    input_type: Optional[str] = "text"

    def __init__(
        self,
        help_text: Optional[str] = None,
        default: Any = None,
        null: bool = False,
        placeholder: str = "",
        disabled: bool = False,
    ):
        super().__init__(
            null=null,
            default=default,
            input_type=self.input_type,
            placeholder=placeholder,
            disabled=disabled,
            help_text=help_text,
        )


class Select(Input):
    template = "widgets/inputs/select.html"

    def __init__(
        self,
        help_text: Optional[str] = None,
        default: Any = None,
        null: bool = False,
        disabled: bool = False,
    ):
        super().__init__(help_text=help_text, null=null, default=default, disabled=disabled)

    @abc.abstractmethod
    async def get_options(self):
        """
        return list of tuple with display and value

        [("on",1),("off",2)]

        :return: list of tuple with display and value
        """

    async def render(self, request: Request, value: Any):
        options = await self.get_options()
        self.context.update(options=options)
        return await super(Select, self).render(request, value)


class ForeignKey(Select):
    def __init__(
        self,
        model: Type[Model],
        default: Any = None,
        null: bool = False,
        disabled: bool = False,
        help_text: Optional[str] = None,
    ):
        super().__init__(help_text=help_text, default=default, null=null, disabled=disabled)
        self.model = model

    async def get_options(self):
        ret = await self.get_queryset()
        options = [(str(x), x.pk) for x in ret]
        if self.context.get("null"):
            options = [("", "")] + options
        return options

    async def get_queryset(self):
        return await self.model.all()

class Enum(Select):
    def __init__(
        self,
        enum: Type[EnumCLS],
        default: Any = None,
        enum_type: Type = int,
        null: bool = False,
        disabled: bool = False,
        help_text: Optional[str] = None,
    ):
        super().__init__(help_text=help_text, default=default, null=null, disabled=disabled)
        self.enum = enum
        self.enum_type = enum_type

    async def parse_value(self, request: Request, value: Any):
        return self.enum(self.enum_type(value))

    async def get_options(self):
        options = [(v.name, v.value) for v in self.enum]
        if self.context.get("null"):
            options = [("", "")] + options
        return options


class Email(Text):
    input_type = "email"


class Json(Input):
    template = "widgets/inputs/json.html"

    def __init__(
        self,
        help_text: Optional[str] = None,
        null: bool = False,
        options: Optional[dict] = None,
    ):
        """
        options config to jsoneditor, see https://github.com/josdejong/jsoneditor
        :param options:
        """
        super().__init__(null=null, help_text=help_text)
        if not options:
            options = {}
        self.context.update(options=options)

    async def render(self, request: Request, value: Any):
        if value:
            value = json.dumps(value)
        return await super().render(request, value)


class TextArea(Text):
    template = "widgets/inputs/textarea.html"
    input_type = "textarea"


class Editor(Text):
    template = "widgets/inputs/editor.html"


class DateTime(Text):
    template = "widgets/inputs/datetime.html"


class Date(Text):
    template = "widgets/inputs/date.html"


class File(Input):
    input_type = "file"

    def __init__(
        self,
        upload: FileUpload,
        default: Any = None,
        null: bool = False,
        disabled: bool = False,
        help_text: Optional[str] = None,
    ):
        super().__init__(
            null=null,
            default=default,
            input_type=self.input_type,
            disabled=disabled,
            help_text=help_text,
        )
        self.upload = upload

    async def parse_value(self, request: Request, value: Optional[UploadFile]):
        if value and value.filename:
            return await self.upload.upload(value)
        return None


class Image(File):
    template = "widgets/inputs/image.html"
    input_type = "file"


class Radio(Select):
    template = "widgets/inputs/radio.html"

    def __init__(
        self,
        options: List[Tuple[str, Any]],
        help_text: Optional[str] = None,
        default: Any = None,
        disabled: bool = False,
    ):
        super().__init__(default=default, disabled=disabled, help_text=help_text)
        self.options = options

    async def get_options(self):
        return self.options


class RadioEnum(Enum):
    template = "widgets/inputs/radio.html"


class Switch(Input):
    template = "widgets/inputs/switch.html"

    async def parse_value(self, request: Request, value: str):
        if value == "on":
            return True
        return False


class Password(Text):
    input_type = "password"


class Number(Text):
    input_type = "number"


class Color(Text):
    template = "widgets/inputs/color.html"


class MultiSelect(Input):
    """多选下拉框组件"""
    template = "widgets/inputs/multiselect.html"
    
    def __init__(
        self,
        options=None,
        default=None,
        null=False,
        help_text=None,
        label="",
        placeholder="请选择",
        disabled=False,
    ):
        super().__init__(
            null=null,
            default=default,
            help_text=help_text,
            disabled=disabled,
            label=label,
            placeholder=placeholder
        )
        self.options = options or []
        
    async def render(self, request: Request, value: Any,_options:list=[]):
        if value is None:
            value = self.default or []
        
        # 将value转换为列表
        if isinstance(value, (int, str)):
            value = [value]
        elif not isinstance(value, list):
            try:
                value = list(value)
            except:
                value = []
        
        # 如果传入的是函数，动态获取选项
        options = self.options or _options
        if callable(options):
            options = await options(request)
        
        # 记录当前字段名和值
        name = self.context.get("name", "未知字段")
        logger.debug(f"渲染字段 {name}, 初始值: {value}, 选项数量: {len(options) if options else 0}")
            
        # 支持从表单初始化数据中获取选项
        if hasattr(request.state, "form_init") and request.state.form_init.get(self.context.get("name"), {}).get("options"):
            options = request.state.form_init[self.context.get("name")]["options"]
            logger.debug(f"从form_init获取字段 {name} 的选项: {options}")
        
        # 标准化选项格式
        normalized_options = []
        
        # 检查选项格式并规范化
        if options:
            for opt in options:
                if isinstance(opt, dict):
                    # 如果是字典格式，确保有value和label字段
                    if "value" in opt:
                        item = {"value": opt["value"]}
                        # 确保每个选项都有label属性
                        if "label" in opt:
                            item["label"] = opt["label"]
                        elif "text" in opt:
                            item["label"] = opt["text"]
                        else:
                            item["label"] = str(opt["value"])
                        normalized_options.append(item)
                elif isinstance(opt, (list, tuple)) and len(opt) >= 2:
                    # 如果是元组格式 (label, value)
                    normalized_options.append({"value": str(opt[1]), "label": opt[0]})
                else:
                    # 简单值
                    normalized_options.append({"value": str(opt), "label": str(opt)})
        
        options = normalized_options
        logger.debug(f"字段 {name} 规范化后的选项: {options}")
            
        # 支持从表单初始化数据中获取选中值
        selected = []
        if hasattr(request.state, "form_init") and request.state.form_init.get(self.context.get("name"), {}).get("selected"):
            selected = request.state.form_init[self.context.get("name")]["selected"]
            logger.debug(f"从form_init获取字段 {name} 的选中项: {selected}")
        
        # 确保选中值是字符串列表
        selected = [str(s) for s in selected]
        value = [str(v) for v in value]
            
        # 更新context但不包含value，避免和模板渲染时的显式参数重复
        self.context.update(options=options, selected=selected)
        
        # 记录最终渲染数据
        logger.debug(f"字段 {name} 最终渲染数据: options={len(options)}项, selected={selected}, value={value}")
        
        return await super(MultiSelect, self).render(request, value)
        
    async def parse_value(self, request: Request, value: Any):
        """处理表单提交的值"""
        if not value:
            return []
        
        if isinstance(value, list):
            return value
            
        # 处理表单提交的字符串值
        if isinstance(value, str):
            if value.startswith("[") and value.endswith("]"):
                try:
                    return json.loads(value)
                except:
                    pass
            
            # 处理逗号分隔的值
            if "," in value:
                return [v.strip() for v in value.split(",")]
                
            # 单个值
            return [value]
            
        return []
