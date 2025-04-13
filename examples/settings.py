import os

from dotenv import load_dotenv

load_dotenv()
# 设置默认数据库为SQLite，方便快速启动
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite://./db.sqlite3")
