# apps/api/core/connections.py
"""
External service connections with support for both MinIO and local storage
"""

import logging
from typing import Optional
import redis.asyncio as redis
from qdrant_client import AsyncQdrantClient
from minio import Minio

from apps.api.core.config import settings
from apps.api.services.storage.local_storage import LocalStorageService

logger = logging.getLogger(__name__)

# Global connection instances
_redis_client: Optional[redis.Redis] = None
_qdrant_client: Optional[AsyncQdrantClient] = None
_minio_client: Optional[Minio] = None
_storage_service = None


async def init_redis() -> redis.Redis:
    """Initialize Redis connection"""
    global _redis_client
    
    try:
        _redis_client = redis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            password=settings.redis_password or None,
            db=settings.redis_db,
            decode_responses=True
        )
        
        # Test connection
        await _redis_client.ping()
        logger.info("✅ Redis connection established")
        return _redis_client
        
    except Exception as e:
        logger.error(f"❌ Redis connection failed: {e}")
        raise


async def init_qdrant() -> AsyncQdrantClient:
    """Initialize Qdrant connection"""
    global _qdrant_client
    
    try:
        _qdrant_client = AsyncQdrantClient(
            host=settings.qdrant_host,
            port=settings.qdrant_port
        )
        
        # Test connection
        collections = await _qdrant_client.get_collections()
        logger.info(f"✅ Qdrant connection established. Collections: {len(collections.collections)}")
        return _qdrant_client
        
    except Exception as e:
        logger.error(f"❌ Qdrant connection failed: {e}")
        raise


async def init_storage():
    """Initialize storage service (local or MinIO based on configuration)"""
    global _storage_service, _minio_client
    
    try:
        if settings.storage_type == "local":
            # Use local filesystem storage
            from apps.api.services.storage.local_storage import local_storage_service
            _storage_service = local_storage_service
            logger.info("✅ Local storage service initialized")
            
        elif settings.storage_type == "minio":
            # Use MinIO storage
            _minio_client = Minio(
                settings.minio_endpoint,
                access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key,
                secure=settings.minio_secure
            )
            
            # Create bucket if it doesn't exist
            if not _minio_client.bucket_exists(settings.minio_bucket_name):
                _minio_client.make_bucket(settings.minio_bucket_name)
                
            logger.info("✅ MinIO connection established")
            
            # Create MinIO wrapper service
            from apps.api.services.storage.minio_storage import MinIOStorageService
            _storage_service = MinIOStorageService(_minio_client)
        
        else:
            raise ValueError(f"Unknown storage type: {settings.storage_type}")
            
        return _storage_service
        
    except Exception as e:
        logger.error(f"❌ Storage initialization failed: {e}")
        # Fallback to local storage
        if settings.storage_type == "minio":
            logger.warning("Falling back to local storage due to MinIO connection failure")
            from apps.api.services.storage.local_storage import local_storage_service
            _storage_service = local_storage_service
            return _storage_service
        raise


async def get_redis_client() -> Optional[redis.Redis]:
    """Get Redis client instance"""
    if _redis_client is None:
        await init_redis()
    return _redis_client


async def get_qdrant_client() -> Optional[AsyncQdrantClient]:
    """Get Qdrant client instance"""
    if _qdrant_client is None:
        await init_qdrant()
    return _qdrant_client


def get_storage_service():
    """Get storage service instance"""
    if _storage_service is None:
        raise RuntimeError("Storage service not initialized. Call init_storage() first.")
    return _storage_service


async def close_connections():
    """Close all connections"""
    global _redis_client, _qdrant_client, _minio_client, _storage_service
    
    if _redis_client:
        await _redis_client.close()
        _redis_client = None
        logger.info("Redis connection closed")
    
    if _qdrant_client:
        # Qdrant client doesn't have async close
        _qdrant_client = None
        logger.info("Qdrant connection closed")
    
    if _minio_client:
        # MinIO client doesn't need closing
        _minio_client = None
        logger.info("MinIO connection closed")
    
    _storage_service = None