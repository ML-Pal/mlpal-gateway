"""
Asset Storage Service for MLPal Assistants Service.

This module provides temporary storage for AI-generated assets (images, audio)
using AWS S3 with presigned URLs.

Design Principles:
- Like OpenAI: URLs expire after a configurable TTL (default 1 hour)
- User responsibility: Users must download files before expiration
- No database tracking: S3 lifecycle rules handle cleanup
- Presigned URLs: Secure, time-limited access without public bucket

Path Structure:
    s3://{bucket}/generated/{user_id}/{trace_id}/{uuid}_{filename}

Example:
    >>> storage = AssetStorageService(bucket="mlpal-assets", region="us-east-2")
    >>> asset = await storage.upload_asset(
    ...     data=image_bytes,
    ...     filename="image.png",
    ...     content_type="image/png",
    ...     user_id="123",
    ...     trace_id="abc-def",
    ... )
    >>> print(asset.url)  # Presigned URL valid for 1 hour
    >>> print(asset.expires_at)  # When URL stops working
"""

import mimetypes
import structlog
from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from types_aiobotocore_s3 import S3Client

from mlpal_assistants_service.schemas.assets import GeneratedAsset

logger = structlog.get_logger()


class AssetStorageError(Exception):
    """Raised when asset storage operations fail."""

    def __init__(self, message: str, cause: Exception | None = None):
        super().__init__(message)
        self.message = message
        self.cause = cause


class AssetStorageService:
    """
    Manages temporary storage of AI-generated assets.

    Features:
    - S3 upload with automatic content type handling
    - Presigned URL generation with configurable TTL
    - Organized path structure for user/request isolation
    - Async-first design using aiobotocore

    Configuration:
    - bucket: S3 bucket name
    - region: AWS region
    - url_expiration: Presigned URL TTL in seconds (default: 3600 = 1 hour)

    Thread Safety:
    - Service is stateless except for lazy-loaded S3 client
    - Safe to share across requests

    Error Handling:
    - Raises AssetStorageError with context on failures
    - Logs errors with structured context
    """

    def __init__(
        self,
        bucket: str,
        region: str,
        url_expiration: int = 3600,
    ):
        """
        Initialize asset storage service.

        Args:
            bucket: S3 bucket name
            region: AWS region (e.g., "us-east-2")
            url_expiration: URL expiration in seconds (default: 3600 = 1 hour)
        """
        self.bucket = bucket
        self.region = region
        self.url_expiration = url_expiration
        self._session = None
        self._client: "S3Client | None" = None
        self._logger = logger.bind(service="asset_storage", bucket=bucket)

    async def _get_client(self) -> "S3Client":
        """
        Get or create async S3 client.

        Uses aiobotocore for proper async support.
        Client is lazily created and reused.
        """
        if self._client is None:
            try:
                from aiobotocore.session import get_session
                from botocore.config import Config

                self._session = get_session()
                # Use regional endpoint for proper presigned URL generation
                # This ensures URLs work without signature issues
                endpoint_url = f"https://s3.{self.region}.amazonaws.com"

                # Create client context manager - we keep it open for reuse
                self._client = await self._session.create_client(
                    "s3",
                    region_name=self.region,
                    endpoint_url=endpoint_url,
                    config=Config(signature_version="s3v4"),
                ).__aenter__()
            except ImportError:
                raise AssetStorageError(
                    "aiobotocore is required for async S3 operations. "
                    "Install with: pip install aiobotocore"
                )
            except Exception as e:
                raise AssetStorageError(
                    f"Failed to create S3 client: {e}",
                    cause=e,
                )
        return self._client

    async def close(self) -> None:
        """Close the S3 client connection."""
        if self._client is not None:
            try:
                await self._client.__aexit__(None, None, None)
            except Exception:
                pass  # Ignore cleanup errors
            finally:
                self._client = None
                self._session = None

    def _generate_s3_key(
        self,
        filename: str,
        user_id: str,
        trace_id: str,
    ) -> str:
        """
        Generate S3 object key with proper structure.

        Format: generated/{user_id}/{trace_id}/{uuid}_{filename}

        The UUID ensures uniqueness even with same filenames.
        """
        # Sanitize filename (remove path separators, limit length)
        safe_filename = filename.replace("/", "_").replace("\\", "_")
        if len(safe_filename) > 100:
            ext = safe_filename.rsplit(".", 1)[-1] if "." in safe_filename else ""
            safe_filename = safe_filename[:90] + ("." + ext if ext else "")

        file_key = f"{uuid4()}_{safe_filename}"
        return f"generated/{user_id}/{trace_id}/{file_key}"

    def _guess_content_type(self, filename: str) -> str:
        """Guess content type from filename, with sensible defaults."""
        content_type, _ = mimetypes.guess_type(filename)
        if content_type:
            return content_type

        # Common defaults for AI-generated content
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        defaults = {
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "webp": "image/webp",
            "gif": "image/gif",
            "mp3": "audio/mpeg",
            "wav": "audio/wav",
            "opus": "audio/opus",
            "flac": "audio/flac",
            "aac": "audio/aac",
            "mp4": "video/mp4",
            "webm": "video/webm",
        }
        return defaults.get(ext, "application/octet-stream")

    async def upload_asset(
        self,
        data: bytes,
        filename: str,
        content_type: str | None,
        user_id: str,
        trace_id: str,
    ) -> GeneratedAsset:
        """
        Upload asset to S3 and return presigned URL.

        This is the primary method for storing generated content.
        The returned URL is valid for the configured expiration time.

        Args:
            data: Binary content to upload
            filename: Desired filename (UUID prefix added automatically)
            content_type: MIME type. If None, guessed from filename.
            user_id: User ID for path organization
            trace_id: Request trace ID for grouping related files

        Returns:
            GeneratedAsset with presigned URL and expiration info

        Raises:
            AssetStorageError: On upload or URL generation failure

        Example:
            >>> asset = await storage.upload_asset(
            ...     data=png_bytes,
            ...     filename="generated.png",
            ...     content_type="image/png",
            ...     user_id="user_123",
            ...     trace_id="req_abc",
            ... )
            >>> # URL valid for 1 hour
            >>> requests.get(asset.url)
        """
        s3_key = self._generate_s3_key(filename, user_id, trace_id)

        # Determine content type
        if content_type is None:
            content_type = self._guess_content_type(filename)

        self._logger.debug(
            "Uploading asset",
            s3_key=s3_key,
            content_type=content_type,
            size_bytes=len(data),
            user_id=user_id,
            trace_id=trace_id,
        )

        try:
            client = await self._get_client()

            # Upload to S3
            await client.put_object(
                Bucket=self.bucket,
                Key=s3_key,
                Body=BytesIO(data),
                ContentType=content_type,
                # Metadata for debugging (not exposed to users)
                Metadata={
                    "user_id": user_id,
                    "trace_id": trace_id,
                    "original_filename": filename[:256],
                },
            )

            # Generate presigned URL
            url = await client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": s3_key},
                ExpiresIn=self.url_expiration,
            )

            # Calculate expiration time
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=self.url_expiration)

            self._logger.info(
                "Asset uploaded successfully",
                s3_key=s3_key,
                size_bytes=len(data),
                expires_at=expires_at.isoformat(),
            )

            return GeneratedAsset(
                url=url,
                expires_at=expires_at,
                content_type=content_type,
                size_bytes=len(data),
            )

        except AssetStorageError:
            raise
        except Exception as e:
            self._logger.error(
                "Failed to upload asset",
                s3_key=s3_key,
                error=str(e),
                error_type=type(e).__name__,
            )
            raise AssetStorageError(
                f"Failed to upload asset: {e}",
                cause=e,
            )

    async def upload_multiple(
        self,
        items: list[tuple[bytes, str, str | None]],
        user_id: str,
        trace_id: str,
    ) -> list[GeneratedAsset]:
        """
        Upload multiple assets efficiently.

        Args:
            items: List of (data, filename, content_type) tuples
            user_id: User ID for path organization
            trace_id: Request trace ID for grouping

        Returns:
            List of GeneratedAsset objects in same order as input

        Example:
            >>> assets = await storage.upload_multiple(
            ...     [
            ...         (img1_bytes, "image_1.png", "image/png"),
            ...         (img2_bytes, "image_2.png", "image/png"),
            ...     ],
            ...     user_id="123",
            ...     trace_id="abc",
            ... )
        """
        results = []
        for data, filename, content_type in items:
            asset = await self.upload_asset(
                data=data,
                filename=filename,
                content_type=content_type,
                user_id=user_id,
                trace_id=trace_id,
            )
            results.append(asset)
        return results

    async def health_check(self) -> bool:
        """
        Check if S3 is accessible.

        Returns:
            True if S3 bucket is accessible, False otherwise
        """
        try:
            client = await self._get_client()
            await client.head_bucket(Bucket=self.bucket)
            return True
        except Exception as e:
            self._logger.warning("S3 health check failed", error=str(e))
            return False
