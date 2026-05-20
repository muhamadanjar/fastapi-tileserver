from pydantic import BaseModel, Field, ConfigDict
from typing import Generic, Optional, TypeVar, Any, Literal
from datetime import datetime
import time

DataType = TypeVar("DataType")
MetasType = TypeVar("MetasType")

class APIResponse(BaseModel, Generic[DataType]):
    """Standard API response wrapper with status, data, metas, message"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    status: Literal["success", "error"] = Field(default="success", description="Response status")
    data: Optional[DataType] = Field(default=None, description="Response data (list or dict)")
    metas: Optional[dict[str, Any]] = Field(default_factory=dict, description="Additional metadata (page, time_elapsed, etc)")
    message: str = Field(default="OK", description="General response message")

    @staticmethod
    def success(
        message: str = "OK",
        data: Optional[DataType] = None,
        metas: Optional[dict[str, Any]] = None
    ) -> "APIResponse[DataType]":
        """Create a success response"""
        return APIResponse(
            status="success",
            message=message,
            data=data,
            metas=metas or {}
        )

    @staticmethod
    def error(
        message: str = "Error",
        data: Optional[DataType] = None,
        metas: Optional[dict[str, Any]] = None
    ) -> "APIResponse[DataType]":
        """Create an error response"""
        return APIResponse(
            status="error",
            message=message,
            data=data,
            metas=metas or {}
        )


class ResponseBuilder:
    """Builder pattern for constructing consistent API responses"""

    def __init__(self):
        self._status: Literal["success", "error"] = "success"
        self._message: str = "OK"
        self._data: Optional[Any] = None
        self._metas: dict[str, Any] = {}
        self._start_time: float = time.time()

    def with_status(self, status: Literal["success", "error"]) -> "ResponseBuilder":
        self._status = status
        return self

    def with_message(self, message: str) -> "ResponseBuilder":
        self._message = message
        return self

    def with_data(self, data: Any) -> "ResponseBuilder":
        self._data = data
        return self

    def add_meta(self, key: str, value: Any) -> "ResponseBuilder":
        self._metas[key] = value
        return self

    def with_metas(self, metas: dict[str, Any]) -> "ResponseBuilder":
        self._metas.update(metas)
        return self

    def with_pagination(self, page: int, page_size: int, total: int) -> "ResponseBuilder":
        self._metas.update({
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size
        })
        return self

    def build(self) -> APIResponse:
        """Build response with auto time_elapsed"""
        self._metas.setdefault("time_elapsed", f"{(time.time() - self._start_time) * 1000:.2f}ms")

        return APIResponse(
            status=self._status,
            message=self._message,
            data=self._data,
            metas=self._metas
        )
