"""SceneChoice 接口统一响应模型。"""

from typing import Any

from pydantic import BaseModel


class ApiResponse(BaseModel):
    code: int = 0
    message: str = "ok"
    data: Any = None

    @staticmethod
    def ok(data: Any = None) -> "ApiResponse":
        """成功响应：code=0，message='ok'，data 原样带回。"""
        return ApiResponse(code=0, message="ok", data=data)

    @staticmethod
    def error(message: str, code: int = 500) -> "ApiResponse":
        """失败响应：data 固定为 None，code 默认 500。"""
        return ApiResponse(code=code, message=message, data=None)
