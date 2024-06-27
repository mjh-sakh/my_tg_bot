import os

from motor.motor_asyncio import AsyncIOMotorClient


class MongoClient:
    _instance = None

    def __new__(cls):
        if not cls._instance:
            cls._instance = super().__new__(cls)
            cls._instance.client = AsyncIOMotorClient(os.getenv('MONGO_URI', 'mongodb://localhost:27017'))
            cls._instance.db = cls._instance.client['tgbot']
        return cls._instance

    def get_db(self):
        return self.db
