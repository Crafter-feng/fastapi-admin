import os
import typing

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# time format
DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
DATE_FORMAT = "%Y-%m-%d"
DATETIME_FORMAT_MOMENT = "YYYY-MM-DD HH:mm:ss"
DATE_FORMAT_MOMENT = "YYYY-MM-DD"

# storage cache
CAPTCHA_ID = "captcha:{captcha_id}"
LOGIN_ERROR_TIMES = "login_error_times:{ip}"
LOGIN_USER = "login_user:{token}"

# Login constants
TOKEN_KEY = "token"

# Permission action constants
PERMISSION_READ = "read"
PERMISSION_CREATE = "create"
PERMISSION_UPDATE = "update"
PERMISSION_DELETE = "delete"
PERMISSION_ALL = [PERMISSION_READ, PERMISSION_CREATE, PERMISSION_UPDATE, PERMISSION_DELETE]

# Resource path constants
RESOURCE_PATH = "/{resource_type}"
RESOURCE_ACTION_PATH = "/{resource_type}/{action}"
