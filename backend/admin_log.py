"""관리자 화면용 최근 로그 버퍼.

- 서버 로그(`dasimanna*` 로거)와 API 요청 한 줄 기록(메서드·경로·상태·처리 시간)을 프로세스 메모리에 최근 N건만 둔다.
- 저장소에 남기지 않으므로 서버가 재시작되면 비워지고, 서버 인스턴스가 여러 개면 각자 따로 갖는다.
- 쿼리 문자열·요청 본문·쿠키는 남기지 않는다(개인정보·토큰이 섞일 수 있음).
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any

MAX_ENTRIES = 1000


class LogBuffer(logging.Handler):
    def __init__(self, capacity: int = MAX_ENTRIES):
        super().__init__(level=logging.INFO)
        self._items: deque[dict[str, Any]] = deque(maxlen=capacity)
        self._lock_ = threading.Lock()
        self._seq = 0

    def add(self, level: str, source: str, message: str, **extra: Any) -> None:
        with self._lock_:
            self._seq += 1
            self._items.append({"seq": self._seq, "at": datetime.now(timezone.utc).isoformat(), "level": level,
                                "source": source, "message": message[:500], **extra})

    def emit(self, record: logging.LogRecord) -> None:  # logging.Handler
        try:
            message = record.getMessage()
        except Exception:  # 형식 오류가 있어도 서버를 멈추지 않는다
            message = str(record.msg)
        if record.exc_info and record.exc_info[0] is not None:
            message += f" ({record.exc_info[0].__name__})"
        self.add(record.levelname, record.name, message)

    def entries(self, level: str | None = None, source: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock_:
            items = list(self._items)
        if level:
            items = [i for i in items if i["level"] == level]
        if source == "request":
            items = [i for i in items if i["source"] == "request"]
        elif source == "server":
            items = [i for i in items if i["source"] != "request"]
        return list(reversed(items))[:limit]

    def clear(self) -> None:
        with self._lock_:
            self._items.clear()


LOG_BUFFER = LogBuffer()


def install() -> None:
    """`dasimanna` 로거에 버퍼를 한 번만 붙인다(INFO 이상)."""
    logger = logging.getLogger("dasimanna")
    if LOG_BUFFER not in logger.handlers:
        logger.addHandler(LOG_BUFFER)
    if logger.level == logging.NOTSET or logger.level > logging.INFO:
        logger.setLevel(logging.INFO)
