"""Common schemas used across the API."""

from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class BaseSchema(BaseModel):
    """Base schema with common configuration."""

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        str_strip_whitespace=True,
    )


class ErrorDetail(BaseSchema):
    """Error detail for structured error responses."""

    code: str = Field(..., description="Error code")
    message: str = Field(..., description="Human-readable error message")
    details: dict[str, Any] | None = Field(default=None, description="Additional error details")


class ErrorResponse(BaseSchema):
    """Standard error response."""

    error: ErrorDetail


class HealthResponse(BaseSchema):
    """Health check response."""

    status: str = Field(..., description="Service status")
    version: str = Field(..., description="Service version")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    checks: dict[str, bool] | None = Field(default=None, description="Individual health checks")


class PaginatedResponse(BaseSchema, Generic[T]):
    """Generic paginated response."""

    items: list[T] = Field(..., description="List of items")
    total: int = Field(..., description="Total number of items")
    page: int = Field(..., description="Current page (1-indexed)")
    page_size: int = Field(..., description="Items per page")
    has_more: bool = Field(..., description="Whether more pages exist")

    @classmethod
    def create(
        cls,
        items: list[T],
        total: int,
        page: int,
        page_size: int,
    ) -> "PaginatedResponse[T]":
        """Create a paginated response."""
        return cls(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            has_more=(page * page_size) < total,
        )
