import os
import sys
from pathlib import Path
from typing import Union, Dict, Any, Optional

from loguru import logger 


# 默认配置
log_level = os.environ.get("LOG_LEVEL", "DEBUG")
log_path = os.environ.get("LOG_PATH", "logs")

# 确保日志目录存在
Path(log_path).mkdir(exist_ok=True, parents=True)

logger.remove()

# 添加控制台处理器
logger.add(
    sys.stderr,
    level=log_level,
    format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
)
        
# 添加文件处理器
logger.add(
    os.path.join(log_path, "fastapi_admin_{time}.log"),
    rotation="100 MB",  # 当文件大小达到100MB时创建新文件
    retention="10 days",  # 保留10天的日志
    level=log_level,
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
    compression="zip",  # 压缩旧日志文件
        )

    
def logger_configure(**kwargs):
    """配置日志器
    
    Args:
        log_level: 日志级别
        log_path: 日志保存路径
            等其他loguru支持的配置
        """
    if "log_level" in kwargs:
        global log_level
        log_level = kwargs.pop("log_level")
        logger.level(log_level)
    if "log_path" in kwargs:
        global log_path
        log_path = kwargs.pop("log_path")
        Path(log_path).mkdir(exist_ok=True, parents=True)
    
    # 重新配置日志器
    logger.configure(**kwargs)
