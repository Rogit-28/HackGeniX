"""
MongoDB database connection and utilities.

Uses Motor for async MongoDB operations.
"""
import logging
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo.errors import ServerSelectionTimeoutError

from src.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class MongoDBClient:
    """
    Async MongoDB client wrapper with connection management.
    """
    
    def __init__(self):
        self._client: Optional[AsyncIOMotorClient] = None
        self._db: Optional[AsyncIOMotorDatabase] = None
    
    @property
    def client(self) -> AsyncIOMotorClient:
        """Get the MongoDB client instance."""
        if self._client is None:
            raise RuntimeError("MongoDB client not initialized. Call connect() first.")
        return self._client
    
    @property
    def db(self) -> AsyncIOMotorDatabase:
        """Get the database instance."""
        if self._db is None:
            raise RuntimeError("MongoDB database not initialized. Call connect() first.")
        return self._db
    
    async def connect(self) -> None:
        """
        Establish connection to MongoDB.
        """
        try:
            self._client = AsyncIOMotorClient(
                settings.mongodb_uri,
                serverSelectionTimeoutMS=5000,
            )
            # Verify connection
            await self._client.admin.command("ping")
            self._db = self._client[settings.mongodb_db_name]
            logger.info(f"Connected to MongoDB: {settings.mongodb_db_name}")
        except ServerSelectionTimeoutError as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            raise
    
    async def disconnect(self) -> None:
        """Close MongoDB connection."""
        if self._client:
            self._client.close()
            self._client = None
            self._db = None
            logger.info("MongoDB connection closed")
    
    async def health_check(self) -> bool:
        """Check if MongoDB connection is healthy."""
        try:
            await self._client.admin.command("ping")
            return True
        except Exception:
            return False
    
    # Collection accessors
    @property
    def resumes(self):
        """Access the resumes collection."""
        return self.db["resumes"]
    
    @property
    def job_descriptions(self):
        """Access the job_descriptions collection."""
        return self.db["job_descriptions"]
    
    @property
    def interviews(self):
        """Access the interviews collection."""
        return self.db["interviews"]
    
    @property
    def candidates(self):
        """Access the candidates collection."""
        return self.db["candidates"]
    
    @property
    def interview_sessions(self):
        """Access the interview_sessions collection."""
        return self.db["interview_sessions"]
    
    @property
    def reports(self):
        """Access the reports collection."""
        return self.db["reports"]


# Global client instance
mongodb_client = MongoDBClient()


# Dependency for FastAPI
async def get_db() -> AsyncIOMotorDatabase:
    """FastAPI dependency to get database instance."""
    return mongodb_client.db
