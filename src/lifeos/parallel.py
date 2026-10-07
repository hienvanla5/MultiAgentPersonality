"""Chạy song song các bước agent độc lập.

Nhiều bước trong hệ thống không phụ thuộc nhau: ý kiến của Người Phản Biện và
Người Động Viên, hay việc nhiều agent cùng đánh giá một nhiệm vụ. Vì mỗi bước
là một lời gọi LLM qua mạng (I/O-bound), dùng thread cho tốc độ gần như tuyến
tính theo số bước mà **không cần** chuyển cả hệ thống sang async.

Lưu ý: chỉ dùng cho các bước **thực sự độc lập**. Nếu bước sau cần kết quả bước
trước thì phải chạy tuần tự.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Generic, Optional, Sequence, TypeVar

T = TypeVar("T")

#: Số luồng mặc định khi không chỉ định.
DEFAULT_MAX_WORKERS = 4


@dataclass
class ParallelResult(Generic[T]):
    """Kết quả chạy song song, giữ nguyên thứ tự đầu vào."""

    values: list[Optional[T]] = field(default_factory=list)
    errors: list[Optional[str]] = field(default_factory=list)
    duration_s: float = 0.0

    @property
    def failed(self) -> bool:
        return any(error is not None for error in self.errors)

    @property
    def ok(self) -> bool:
        return not self.failed

    @property
    def successes(self) -> list[T]:
        return [v for v in self.values if v is not None]

    def error_summary(self) -> str:
        parts = [
            f"#{i}: {error}"
            for i, error in enumerate(self.errors)
            if error is not None
        ]
        return "; ".join(parts) or "không có lỗi"


def map_parallel(
    jobs: Sequence[Callable[[], T]],
    *,
    max_workers: Optional[int] = None,
) -> ParallelResult[T]:
    """Chạy nhiều hàm không tham số cùng lúc, trả kết quả theo đúng thứ tự.

    Một job lỗi **không** làm hỏng các job khác: lỗi được ghi vào `errors` theo
    đúng vị trí, còn `values[i]` là `None`. Nhờ vậy bên gọi quyết định xử lý
    phần nào hỏng thay vì mất trắng cả lượt chạy.
    """
    if not jobs:
        return ParallelResult(values=[], errors=[], duration_s=0.0)

    started = time.perf_counter()
    workers = max_workers or min(DEFAULT_MAX_WORKERS, len(jobs))

    if workers <= 1 or len(jobs) == 1:
        # Không cần thread khi chỉ có một việc.
        values: list[Optional[T]] = []
        errors: list[Optional[str]] = []
        for job in jobs:
            try:
                values.append(job())
                errors.append(None)
            except Exception as exc:  # noqa: BLE001 - ghi lại rồi trả cho bên gọi
                values.append(None)
                errors.append(f"{type(exc).__name__}: {exc}")
        return ParallelResult(
            values=values,
            errors=errors,
            duration_s=time.perf_counter() - started,
        )

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(job) for job in jobs]
        values = []
        errors = []
        for future in futures:
            try:
                values.append(future.result())
                errors.append(None)
            except Exception as exc:  # noqa: BLE001
                values.append(None)
                errors.append(f"{type(exc).__name__}: {exc}")

    return ParallelResult(
        values=values,
        errors=errors,
        duration_s=time.perf_counter() - started,
    )