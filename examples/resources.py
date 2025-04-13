import os
from typing import List

from starlette.requests import Request

from examples import enums
from examples.constants import BASE_DIR
from examples.models import Admin, Category, Config, Product, Permission, Role, AdminLog
from fastapi_admin.app import app
from fastapi_admin.enums import Method
from fastapi_admin.file_upload import FileUpload
from fastapi_admin.resources import Action, Dropdown, Field, Link, Model, ToolbarAction
from fastapi_admin.widgets import displays, filters, inputs
from fastapi_admin.i18n import _

upload = FileUpload(uploads_dir=os.path.join(BASE_DIR, "static", "uploads"))


@app.register
class Dashboard(Link):
    label = _("Dashboard")
    icon = "fas fa-home"
    url = "/admin"


@app.register
class Content(Dropdown):
    class CategoryResource(Model):
        label = _("Category")
        model = Category
        fields = ["id", "name", "slug", "created_at"]

    class ProductResource(Model):
        label = _("Product")
        model = Product
        filters = [
            filters.Enum(enum=enums.ProductType, name="type", label=_("ProductType")),
            filters.Datetime(name="created_at", label=_("CreatedAt")),
        ]
        fields = [
            "id",
            "name",
            "view_num",
            "sort",
            "is_reviewed",
            "type",
            Field(name="image", label=_("Image"), display=displays.Image(width="40")),
            Field(name="body", label=_("Body"), input_=inputs.Editor()),
            "created_at",
        ]

    label = _("Content")
    icon = "fas fa-bars"
    resources = [ProductResource, CategoryResource]


@app.register
class ConfigResource(Model):
    label = _("Config")
    model = Config
    icon = "fas fa-cogs"
    filters = [
        filters.Enum(enum=enums.Status, name="status", label=_("Status")),
        filters.Search(name="key", label=_("Key"), search_mode="equal"),
    ]
    fields = [
        "id",
        "label",
        "key",
        "value",
        Field(
            name="status",
            label=_("Status"),
            input_=inputs.RadioEnum(enums.Status, default=enums.Status.on),
        ),
    ]

    async def row_attributes(self, request: Request, obj: dict) -> dict:
        if obj.get("status") == enums.Status.on:
            return {"class": "bg-green text-white"}
        return await super().row_attributes(request, obj)

    async def get_actions(self, request: Request) -> List[Action]:
        actions = await super().get_actions(request)
        switch_status = Action(
            label=_("Switch Status"),
            icon="ti ti-toggle-left",
            name="switch_status",
            method=Method.PUT,
        )
        actions.append(switch_status)
        return actions
