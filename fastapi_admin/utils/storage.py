from typing import Dict, Any, Optional, Union, cast
import time
from typing_extensions import TypedDict  # 兼容Python 3.7

# 为Python 3.7定义存储项的类型
class StorageItem(TypedDict, total=False):
    value: Any  
    expire_time: Optional[float]

class MemoryStorage:
    """
    内存存储类，作为Redis的替代方案
    提供异步接口以兼容原有的Redis使用
    使用单例模式确保全局只有一个实例
    """
    _instance = None
    
    def __new__(cls):
        """
        单例模式实现，确保全局只有一个MemoryStorage实例
        保证在多次初始化时使用相同的存储空间
        """
        if cls._instance is None:
            cls._instance = super(MemoryStorage, cls).__new__(cls)
            # 使用字典注解以兼容Python 3.7
            cls._instance.storage = cast(Dict[str, StorageItem], {})
        return cls._instance
        
    def __init__(self):
        # __new__已经初始化了storage，这里不需要重复初始化
        # 仅当_instance为None时初始化storage
        pass
        
    async def set(self, key: str, value: Any, ex: Optional[int] = None) -> None:
        """
        设置键值对，支持过期时间
        
        Args:
            key: 键名
            value: 值
            ex: 过期时间(秒)
        """
        expire_time = None
        if ex is not None:
            expire_time = time.time() + ex
        self.storage[key] = {
            'value': value,
            'expire_time': expire_time
        }
        
    async def get(self, key: str) -> Any:
        """
        获取值，自动检查过期时间
        
        Args:
            key: 键名
            
        Returns:
            如果键存在且未过期，返回值；否则返回None
        """
        data = self.storage.get(key)
        if data is None:
            return None
        
        # 检查是否过期
        if data['expire_time'] is not None and time.time() > data['expire_time']:
            del self.storage[key]
            return None
            
        return data['value']
        
    async def delete(self, key: str) -> None:
        """
        删除键值对
        
        Args:
            key: 键名
        """
        if key in self.storage:
            del self.storage[key] 