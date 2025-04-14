from fastapi_admin.utils.logger import logger
import typing
import uuid
import os
from typing import Type
from fastapi import Depends, Form, UploadFile
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import RedirectResponse
from starlette.status import HTTP_303_SEE_OTHER, HTTP_401_UNAUTHORIZED
from tortoise import signals
from fastapi_admin import constants
from fastapi_admin.depends import get_current_user, get_storage, get_resources
from fastapi_admin.i18n import _
from fastapi_admin.models import AbstractAdmin
from fastapi_admin.providers import Provider
from fastapi_admin.utils.storage import MemoryStorage
from fastapi_admin.template import templates
from fastapi_admin.utils import check_password, hash_password
if typing.TYPE_CHECKING:
    from fastapi_admin.app import FastAPIAdmin

class UsernamePasswordProvider(Provider):
    name = 'login_provider'
    access_token = 'access_token'

    def __init__(self, user_model: Type[AbstractAdmin], login_path='/login', logout_path='/logout', template='providers/login/login.html', login_title=_('Login to your account'), login_logo_url: str=None):
        self.login_path = login_path
        self.logout_path = logout_path
        self.template = template
        self.user_model = user_model
        self.login_title = login_title
        self.login_logo_url = login_logo_url

    async def login_view(self, request: Request):
        return templates.TemplateResponse(self.template, context={'request': request, 'login_logo_url': self.login_logo_url, 'login_title': self.login_title})

    async def register(self, app: 'FastAPIAdmin'):
        (await super(UsernamePasswordProvider, self).register(app))
        login_path = self.login_path
        app.get(login_path)(self.login_view)
        app.post(login_path)(self.login)
        app.get(self.logout_path)(self.logout)
        app.add_middleware(BaseHTTPMiddleware, dispatch=self.authenticate)
        app.get('/init')(self.init_view)
        app.post('/init')(self.init)
        
        # 个人信息相关路由
        app.get('/profile')(self.profile_view)
        app.post('/profile/info')(self.profile_info_update)
        app.post('/profile/password')(self.profile_password_update)
        
        # 原有的密码修改路由，保留向后兼容性
        app.get('/password')(self.password_view)
        app.post('/password')(self.password)
        
        signals.pre_save(self.user_model)(self.pre_save_admin)

    async def pre_save_admin(self, _, instance: AbstractAdmin, using_db, update_fields):
        if instance.pk:
            db_obj = (await instance.get(pk=instance.pk))
            if (db_obj.password != instance.password):
                instance.password = hash_password(instance.password)
        else:
            instance.password = hash_password(instance.password)

    async def login(self, request: Request, storage: MemoryStorage=Depends(get_storage)):
        form = (await request.form())
        username = form.get('username')
        password = form.get('password')
        remember_me = form.get('remember_me')
        user = (await self.user_model.get_or_none(username=username))
        if ((not user) or (not check_password(password, user.password))):
            return templates.TemplateResponse(self.template, status_code=HTTP_401_UNAUTHORIZED, context={'request': request, 'error': _('login_failed')})
        response = RedirectResponse(url=request.app.admin_path, status_code=HTTP_303_SEE_OTHER)
        if (remember_me == 'on'):
            expire = ((3600 * 24) * 30)
            response.set_cookie('remember_me', 'on')
        else:
            expire = 3600
            response.delete_cookie('remember_me')
        token = uuid.uuid4().hex
        response.set_cookie(self.access_token, token, expires=expire, path=request.app.admin_path, httponly=True)
        (await storage.set(constants.LOGIN_USER.format(token=token), user.pk, ex=expire))
        return response

    async def logout(self, request: Request):
        response = self.redirect_login(request)
        response.delete_cookie(self.access_token, path=request.app.admin_path)
        token = request.cookies.get(self.access_token)
        (await request.app.storage.delete(constants.LOGIN_USER.format(token=token)))
        return response

    async def authenticate(self, request: Request, call_next: RequestResponseEndpoint):
        storage = request.app.storage
        token = request.cookies.get(self.access_token)
        path = request.scope['path']
        user = None
        if token:
            token_key = constants.LOGIN_USER.format(token=token)
            admin_id = (await storage.get(token_key))
            user = (await self.user_model.get_or_none(pk=admin_id))
        request.state.user = user
        admin_path = request.app.admin_path
        logger.info(f' Path: {path}, User path: {admin_path}, User: {user}')
        if (((path == (admin_path + self.login_path)) or (path == self.login_path)) and user):
            return RedirectResponse(url=admin_path, status_code=HTTP_303_SEE_OTHER)
        is_init_page = ((path == '/init') or (path == (admin_path + '/init')))
        is_login_page = ((path == self.login_path) or (path == (admin_path + self.login_path)))
        logger.info(f' is_init_page: {is_init_page}, is_login_page: {is_login_page}')
        has_users = (await self.user_model.all().limit(1).exists())
        logger.info(f' System has users: {has_users}')
        if ((not has_users) and (not is_init_page)):
            logger.info(f' No users in system, redirecting to init page from: {path}')
            return RedirectResponse(url=(admin_path + '/init'), status_code=HTTP_303_SEE_OTHER)
        if (is_init_page or is_login_page):
            logger.info(f' Allowing access to special page: {path}')
            response = (await call_next(request))
            return response
        if ((not user) and path.startswith(admin_path)):
            logger.info(f' Redirecting to login page from: {path}')
            return self.redirect_login(request)
        response = (await call_next(request))
        return response

    async def create_user(self, username: str, password: str, **kwargs):
        return (await self.user_model.create(username=username, password=password, **kwargs))

    async def init_view(self, request: Request):
        exists = (await self.user_model.all().limit(1).exists())
        if exists:
            logger.info(f' User exists, redirecting to login from init_view')
            return self.redirect_login(request)
        logger.info(f' Rendering init template')
        return templates.TemplateResponse('init.html', context={'request': request})

    async def init(self, request: Request):
        exists = (await self.user_model.all().limit(1).exists())
        if exists:
            logger.info(f' User exists, redirecting to login from init')
            return self.redirect_login(request)
        logger.info(f' Processing init form')
        form = (await request.form())
        password = form.get('password')
        confirm_password = form.get('confirm_password')
        username = form.get('username')
        logger.info(f" Form data: username={username}, password={(('*' * len(password)) if password else 'None')}")
        if (password != confirm_password):
            logger.info(f' Password mismatch')
            return templates.TemplateResponse('init.html', context={'request': request, 'error': _('confirm_password_different')})
        try:
            logger.info(f' Creating new user: {username}')
            (await self.create_user(username, password, is_superuser=True, is_active=True))
            logger.info(f' User created successfully')
            return self.redirect_login(request)
        except Exception as e:
            logger.info(f' Error creating user: {str(e)}')
            return templates.TemplateResponse('init.html', context={'request': request, 'error': f'创建用户失败: {str(e)}'})

    def redirect_login(self, request: Request):
        return RedirectResponse(url=(request.app.admin_path + self.login_path), status_code=HTTP_303_SEE_OTHER)

    async def password_view(self, request: Request, resources=Depends(get_resources)):
        return templates.TemplateResponse('providers/login/password.html', context={'request': request, 'resources': resources})

    async def password(self, request: Request, old_password: str=Form(...), new_password: str=Form(...), re_new_password: str=Form(...), user: AbstractAdmin=Depends(get_current_user), resources=Depends(get_resources)):
        error = None
        if (not check_password(old_password, user.password)):
            error = _('old_password_error')
        elif (new_password != re_new_password):
            error = _('new_password_different')
        if error:
            return templates.TemplateResponse('password.html', context={'request': request, 'resources': resources, 'error': error})
        user.password = new_password
        (await user.save(update_fields=['password']))
        return (await self.logout(request))

    async def profile_view(self, request: Request, user: AbstractAdmin=Depends(get_current_user), resources=Depends(get_resources)):
        """个人信息页面"""
        return templates.TemplateResponse('providers/login/profile.html', context={
            'request': request, 
            'resources': resources, 
            'user': user,
            'page_title': _('profile'),
            'page_pre_title': _('user_settings')
        })
        
    async def profile_info_update(self, request: Request, user: AbstractAdmin=Depends(get_current_user), resources=Depends(get_resources)):
        """更新个人信息"""
        form = await request.form()
        
        # 更新基本信息
        user.email = form.get('email', user.email)
        user.intro = form.get('intro', user.intro)
        
        # 处理头像上传
        avatar = form.get('avatar')
        if avatar and isinstance(avatar, UploadFile) and avatar.filename:
            try:
                # 这里可以添加文件上传处理逻辑
                # 例如保存文件到静态目录并设置URL
                file_ext = avatar.filename.split('.')[-1]
                filename = f"avatar_{user.pk}_{uuid.uuid4()}.{file_ext}"
                file_path = f"/static/uploads/avatars/{filename}"
                
                # 确保目录存在
                avatar_dir = os.path.join("static", "uploads", "avatars")
                os.makedirs(avatar_dir, exist_ok=True)
                
                # 保存文件
                content = await avatar.read()
                with open(f"{avatar_dir}/{filename}", "wb") as f:
                    f.write(content)
                
                user.avatar = file_path
            except Exception as e:
                logger.error(f"头像上传失败: {str(e)}")
                return templates.TemplateResponse('providers/login/profile.html', context={
                    'request': request, 
                    'resources': resources, 
                    'user': user,
                    'error': f"头像上传失败: {str(e)}",
                    'page_title': _('profile'),
                    'page_pre_title': _('user_settings')
                })
        
        # 保存更新
        try:
            await user.save(update_fields=['email', 'intro', 'avatar'])
            return templates.TemplateResponse('providers/login/profile.html', context={
                'request': request, 
                'resources': resources, 
                'user': user,
                'success': _('profile_updated'),
                'page_title': _('profile'),
                'page_pre_title': _('user_settings')
            })
        except Exception as e:
            logger.error(f"个人信息更新失败: {str(e)}")
            return templates.TemplateResponse('providers/login/profile.html', context={
                'request': request, 
                'resources': resources, 
                'user': user,
                'error': f"个人信息更新失败: {str(e)}",
                'page_title': _('profile'),
                'page_pre_title': _('user_settings')
            })
    
    async def profile_password_update(self, request: Request, user: AbstractAdmin=Depends(get_current_user), resources=Depends(get_resources)):
        """更新密码"""
        form = await request.form()
        old_password = form.get('old_password')
        new_password = form.get('new_password')
        re_new_password = form.get('re_new_password')
        
        error = None
        if not old_password or not new_password or not re_new_password:
            error = _('password_fields_required')
        elif not check_password(old_password, user.password):
            error = _('old_password_error')
        elif new_password != re_new_password:
            error = _('new_password_different')
            
        if error:
            return templates.TemplateResponse('providers/login/profile.html', context={
                'request': request, 
                'resources': resources, 
                'user': user,
                'error': error,
                'page_title': _('profile'),
                'page_pre_title': _('user_settings')
            })
            
        # 更新密码
        user.password = new_password
        await user.save(update_fields=['password'])
        
        return templates.TemplateResponse('providers/login/profile.html', context={
            'request': request, 
            'resources': resources, 
            'user': user,
            'success': _('password_updated'),
            'page_title': _('profile'),
            'page_pre_title': _('user_settings')
        })
