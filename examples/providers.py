from fastapi_admin.utils.logger import logger

import datetime
import uuid
from fastapi import Depends, Form
from starlette.requests import Request
from starlette.responses import RedirectResponse
from starlette.status import HTTP_401_UNAUTHORIZED, HTTP_303_SEE_OTHER
from fastapi_admin.depends import get_current_user, get_resources, get_storage
from fastapi_admin.models import AbstractAdmin
from fastapi_admin.providers.login import UsernamePasswordProvider
from fastapi_admin import constants
from fastapi_admin.template import templates
from fastapi_admin.i18n import _
from fastapi_admin.utils import check_password

from examples.models import AdminLog  # 导入AdminLog模型

class LoginProvider(UsernamePasswordProvider):

    async def login(self, request: Request, storage=Depends(get_storage)):
        form = (await request.form())
        username = form.get('username')
        password = form.get('password')
        remember_me = form.get('remember_me')
        admin = (await self.user_model.get_or_none(username=username))
        if ((not admin) or (not check_password(password, admin.password))):
            logger.warning(f"登录失败: 用户名 {username} 认证失败")
            return templates.TemplateResponse(self.template, status_code=HTTP_401_UNAUTHORIZED, context={'request': request, 'error': _('login_failed')})
        
        # 记录登录日志
        try:
            # 获取客户端IP地址
            client_ip = request.client.host if hasattr(request, 'client') else "unknown"
            user_agent = request.headers.get("user-agent", "unknown")
            
            # 记录登录成功日志
            await AdminLog.create(
                admin=admin,
                content={
                    "ip": client_ip,
                    "user_agent": user_agent,
                    "remember_me": remember_me == "on"
                },
                resource="login",
                action="login"
            )
            
            # 更新最后登录时间
            admin.last_login = datetime.datetime.now()
            await admin.save(update_fields=["last_login"])
            
            logger.info(f"用户 {username} 登录成功，IP: {client_ip}")
        except Exception as e:
            logger.error(f"记录登录日志失败: {str(e)}")
            
        # 执行正常的登录流程
        response = RedirectResponse(url=request.app.admin_path, status_code=HTTP_303_SEE_OTHER)
        if (remember_me == 'on'):
            expire = ((3600 * 24) * 30)
            response.set_cookie('remember_me', 'on')
        else:
            expire = 3600
            response.delete_cookie('remember_me')
        token = uuid.uuid4().hex
        response.set_cookie(self.access_token, token, expires=expire, path=request.app.admin_path, httponly=True)
        (await storage.set(constants.LOGIN_USER.format(token=token), admin.pk, ex=expire))
        return response

    async def password(self, request: Request, old_password: str=Form(...), new_password: str=Form(...), re_new_password: str=Form(...), admin: AbstractAdmin=Depends(get_current_user), resources=Depends(get_resources)):
        return (await self.logout(request))

    async def create_user(self, username: str, password: str, **kwargs):
        '创建用户时，如果是第一个用户，自动赋予超级管理员权限'
        exists = (await self.user_model.all().count())
        if (exists == 0):
            kwargs['is_superuser'] = True
            logger.info(f' Creating first admin with superuser privileges: {username}')
        user = (await super().create_user(username, password, **kwargs))
        logger.info(f" User created: {username}, id: {user.pk}, superuser: {getattr(user, 'is_superuser', False)}")
        return user