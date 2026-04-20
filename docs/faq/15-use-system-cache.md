# 如何在插件中使用系统级统一缓存？

返回 [README](../../README.md) | [FAQ 索引](../FAQ.md)

**（仅支持 `v2.7.4+` 版本）**
- MoviePilot提供了统一的缓存系统，支持内存缓存、文件系统缓存和Redis缓存自动管理，当有Redis时优先使用Redis，否则使用内存或文件系统。插件可以通过系统提供的缓存接口实现高效的缓存管理，无需关心系统设置。

- 1. 使用缓存装饰器：
    ```python
    from app.core.cache import cached
    
    class MyPlugin(_PluginBase):
        @cached(region="my_plugin", ttl=3600)
        def get_data(self, key: str):
            """
            使用缓存装饰器，缓存结果1小时
            """
            # 复杂的计算或网络请求
            return expensive_operation(key)
        
        @cached(region="my_plugin_async", ttl=1800, skip_none=True)
        async def get_async_data(self, key: str):
            """
            异步函数缓存，跳过None值
            """
            return await async_expensive_operation(key)
    ```

- 2. 使用TTLCache类：
    ```python
    from app.core.cache import TTLCache
    
    class MyPlugin(_PluginBase):
        def __init__(self):
            super().__init__()
            # 创建缓存实例，最大128项，TTL 30分钟
            self.cache = TTLCache(region="my_plugin", maxsize=128, ttl=1800)
        
        def process_data(self, key: str):
            # 检查缓存
            if key in self.cache:
                return self.cache[key]
            
            # 计算并缓存结果
            result = expensive_operation(key)
            self.cache[key] = result
            return result
        
        def clear_cache(self):
            """
            清理插件缓存
            """
            self.cache.clear()
    ```

- 3. 使用文件缓存后端（适用于大文件缓存）：
    ```python
    from app.core.cache import FileCache, AsyncFileCache
    from pathlib import Path
    
    class MyPlugin(_PluginBase):
        def __init__(self):
            super().__init__()
            # 获取文件缓存后端，支持Redis和文件系统
            self.file_cache = FileCache(
                base=Path("/tmp/my_plugin_cache"),
                ttl=86400  # 24小时
            )
        
        def cache_large_file(self, key: str, data: bytes):
            """
            缓存大文件数据
            """
            self.file_cache.set(key, data, region="large_files")
        
        def get_cached_file(self, key: str) -> Optional[bytes]:
            """
            获取缓存的文件数据
            """
            return self.file_cache.get(key, region="large_files")
        
        async def async_cache_operations(self):
            """
            异步文件缓存操作
            """
            async_cache = AsyncFileCache(
                base=Path("/tmp/my_plugin_async_cache"),
                ttl=3600
            )
            
            # 异步设置缓存
            await async_cache.set("async_key", b"async_data", region="async_files")
            
            # 异步获取缓存
            data = await async_cache.get("async_key", region="async_files")
            
            await async_cache.close()
    ```

- 4. 直接使用缓存后端（高级用法）：
    ```python
    from app.core.cache import Cache
    
    class MyPlugin(_PluginBase):
        def __init__(self):
            super().__init__()
            # 直接获取缓存后端实例，系统自动选择Redis或内存缓存
            self.cache_backend = Cache(maxsize=256, ttl=3600)
        
        def custom_cache_operation(self, key: str, value: Any):
            """
            自定义缓存操作
            """
            # 设置缓存
            self.cache_backend.set(key, value, region="custom_region")
            
            # 检查缓存是否存在
            if self.cache_backend.exists(key, region="custom_region"):
                # 获取缓存
                cached_value = self.cache_backend.get(key, region="custom_region")
                return cached_value
            
            return None
        
        def iterate_cache_items(self):
            """
            遍历缓存项
            """
            for key, value in self.cache_backend.items(region="custom_region"):
                print(f"缓存键: {key}, 值: {value}")
        
        def cleanup(self):
            """
            清理缓存
            """
            self.cache_backend.clear(region="custom_region")
            self.cache_backend.close()
    ```

- 5. 缓存装饰器参数说明：
    ```python
    @cached(
        region="my_plugin",           # 缓存区域，用于隔离不同插件的缓存
        maxsize=512,                  # 最大缓存条目数（仅内存缓存有效）
        ttl=1800,                     # 缓存存活时间（秒）
        skip_none=True,               # 是否跳过None值缓存
        skip_empty=False              # 是否跳过空值缓存（空列表、空字典等）
    )
    def my_function(self, param):
        pass
    ```

- 6. 缓存管理功能：
    ```python
    class MyPlugin(_PluginBase):
        @cached(region="my_plugin")
        def cached_function(self, param):
            return expensive_operation(param)
        
        def clear_my_cache(self):
            """
            清理指定区域的缓存
            """
            self.cached_function.cache_clear()
        
        def get_cache_info(self):
            """
            获取缓存信息
            """
            cache_region = self.cached_function.cache_region
            return f"缓存区域: {cache_region}"
    ```

- 7. 缓存后端自动选择：
    - 系统会根据配置自动选择缓存后端：
        - `CACHE_BACKEND_TYPE=redis`：使用Redis作为缓存后端
        - `CACHE_BACKEND_TYPE=memory`：使用内存缓存（cachetools）
    - 插件代码无需修改，系统会自动处理缓存后端的切换

- 8. 最佳实践：
    - 为每个插件使用独立的缓存区域（region），避免缓存键冲突
    - 合理设置TTL，避免缓存过期时间过长导致数据过期
    - 对于频繁访问的数据使用较长的TTL，对于实时性要求高的数据使用较短的TTL
    - 使用`skip_none=True`避免缓存无意义的None值
    - 大文件或二进制数据建议使用文件缓存后端
    - 在插件卸载时清理相关缓存，避免内存泄漏
