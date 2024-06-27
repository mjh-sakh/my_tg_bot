# import redis.asyncio as redis
import redis.asyncio as redis


class RedisClient:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(RedisClient, cls).__new__(cls)
            default_kwargs = {
                'host': 'localhost',
                'port': 6379,
                'db': 0
            }
            kwargs = default_kwargs | kwargs
            cls._instance.client = redis.Redis(*args, **kwargs)
        else:
            assert args == () and kwargs == {}, 'RedisClient singleton already initialized with args and kwargs'
        return cls._instance

    def get_client(self):
        return self.client
