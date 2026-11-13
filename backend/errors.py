"""API 오류 형식. 모든 오류는 {"detail": {"code", "message"}} 로 응답한다."""

from __future__ import annotations

from fastapi import HTTPException


class ApiError(HTTPException):
    def __init__(self, status: int, code: str, message: str, **extra):
        super().__init__(status_code=status, detail={"code": code, "message": message, **extra})
        self.code = code
