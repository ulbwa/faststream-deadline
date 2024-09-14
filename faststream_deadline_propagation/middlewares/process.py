import asyncio
from datetime import datetime, timedelta
from functools import partial
from typing import Any, Callable, Mapping

from faststream import BaseMiddleware, context
from faststream.broker.message import StreamMessage
from faststream.log import logger
from faststream.types import AsyncFuncAny

from faststream_deadline_propagation.countdown import _DeadlineCountdown
from faststream_deadline_propagation.defaults import _COUNTDOWN_CONTEXT, DEFAULT_HEADER
from faststream_deadline_propagation.exceptions import DeadlineOccurred


class DeadlineProcessMiddleware(BaseMiddleware):
    header: str
    default_timeout: float | None

    __slots__ = "msg", "header", "default_timeout"

    def __init__(self, msg: Any, *, header: str, default_timeout: float | None = None):
        self.header = header
        self.default_timeout = default_timeout

        super().__init__(msg)

    @classmethod
    def make_middleware(
        cls, header: str = DEFAULT_HEADER, default_timeout: float | None = None
    ) -> Callable[[Any], "DeadlineProcessMiddleware"]:
        return partial(cls, header=header, default_timeout=default_timeout)

    def get_default_deadline(self) -> datetime | None:
        if not self.default_timeout:
            return
        return datetime.now() + timedelta(seconds=self.default_timeout)

    def get_deadline_from_header(self, header_value: str) -> datetime | None:
        try:
            deadline = datetime.fromisoformat(header_value)
        except ValueError:
            logger.warning(
                f"Invalid {self.header} header value received: {header_value!r}. "
                "Using default deadline."
            )
            return self.get_default_deadline()
        else:
            return deadline

    def get_deadline(self, headers: Mapping[str, str]) -> datetime | None:
        header_value = headers.get(self.header)
        if not header_value:
            return self.get_default_deadline()
        return self.get_deadline_from_header(header_value)

    async def consume_scope(
        self, call_next: "AsyncFuncAny", msg: "StreamMessage[Any]"
    ) -> Any:
        deadline = self.get_deadline(msg.headers)
        if not deadline:
            return await call_next(msg)

        countdown = _DeadlineCountdown(deadline=deadline)
        context.set_local(_COUNTDOWN_CONTEXT, countdown)

        if countdown() <= 0:
            raise DeadlineOccurred()

        try:
            async with asyncio.timeout(countdown()):
                return await call_next(msg)
        except TimeoutError as exc:
            raise DeadlineOccurred() from exc


__all__ = ("DeadlineProcessMiddleware",)
