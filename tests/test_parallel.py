"""Test chạy song song."""

from __future__ import annotations

import threading
import time

from lifeos.parallel import DEFAULT_MAX_WORKERS, map_parallel


def test_empty_job_list():
    result = map_parallel([])
    assert result.values == []
    assert result.errors == []
    assert result.ok is True
    assert result.duration_s == 0.0


def test_single_job_returns_value():
    result = map_parallel([lambda: 42])
    assert result.values == [42]
    assert result.ok is True


def test_results_preserve_input_order():
    jobs = [lambda i=i: i for i in range(6)]
    result = map_parallel(jobs)
    assert result.values == [0, 1, 2, 3, 4, 5]


def test_order_preserved_even_when_slowness_is_reversed():
    """Job đầu chậm nhất vẫn phải đứng đầu kết quả."""

    def slow() -> str:
        time.sleep(0.15)
        return "cham"

    def fast() -> str:
        return "nhanh"

    result = map_parallel([slow, fast, fast, fast])
    assert result.values == ["cham", "nhanh", "nhanh", "nhanh"]


# --- xử lý lỗi ---


def test_one_failure_does_not_break_others():
    def boom() -> int:
        raise ValueError("hỏng")

    result = map_parallel([lambda: 1, boom, lambda: 3])
    assert result.values == [1, None, 3]
    assert result.ok is False
    assert result.failed is True


def test_error_message_records_type_and_text():
    def boom() -> None:
        raise ValueError("hỏng cụ thể")

    result = map_parallel([boom])
    assert result.errors[0] is not None
    assert "ValueError" in result.errors[0]
    assert "hỏng cụ thể" in result.errors[0]


def test_error_is_placed_at_correct_index():
    def boom() -> None:
        raise RuntimeError("x")

    result = map_parallel([lambda: "a", boom, lambda: "c"])
    assert result.errors[0] is None
    assert result.errors[1] is not None
    assert result.errors[2] is None


def test_successes_filters_out_failures():
    def boom() -> None:
        raise RuntimeError("x")

    result = map_parallel([lambda: "a", boom, lambda: "c"])
    assert result.successes == ["a", "c"]


def test_all_fail():
    def boom() -> None:
        raise RuntimeError("x")

    result = map_parallel([boom, boom])
    assert result.successes == []
    assert result.failed is True


def test_error_summary_lists_positions():
    def boom() -> None:
        raise RuntimeError("x")

    result = map_parallel([lambda: 1, boom])
    summary = result.error_summary()
    assert "#1" in summary
    assert "RuntimeError" in summary


def test_error_summary_when_clean():
    assert map_parallel([lambda: 1]).error_summary() == "không có lỗi"


# --- thực sự chạy song song ---


def test_jobs_run_concurrently_faster_than_sequential():
    """4 việc, mỗi việc ngủ 0.3s: tuần tự mất ~1.2s, song song phải nhanh hơn nhiều."""
    delay = 0.3
    jobs = [_sleeper(delay) for _ in range(4)]

    started = time.perf_counter()
    result = map_parallel(jobs)
    elapsed = time.perf_counter() - started

    assert result.ok is True
    # Ngưỡng rộng rãi để không chập chờn trên máy chậm.
    assert elapsed < delay * 4 * 0.75, f"mất {elapsed:.2f}s, có vẻ chạy tuần tự"


def test_sequential_mode_when_max_workers_is_one():
    delay = 0.2
    jobs = [_sleeper(delay) for _ in range(3)]

    started = time.perf_counter()
    map_parallel(jobs, max_workers=1)
    elapsed = time.perf_counter() - started

    assert elapsed >= delay * 3 * 0.9, "max_workers=1 phải chạy tuần tự"


def test_threads_are_actually_different():
    """Xác nhận các job chạy trên nhiều thread, không phải cùng một thread."""
    seen: set[int] = set()
    lock = threading.Lock()

    def record() -> None:
        time.sleep(0.05)
        with lock:
            seen.add(threading.get_ident())

    map_parallel([record for _ in range(4)])
    assert len(seen) > 1


def test_max_workers_capped_by_job_count():
    """Xin nhiều worker hơn số việc vẫn phải chạy đúng, không lỗi."""
    result = map_parallel([lambda: 1, lambda: 2], max_workers=16)
    assert result.values == [1, 2]


def test_default_workers_constant_is_sane():
    assert DEFAULT_MAX_WORKERS >= 2


def _sleeper(seconds: float):
    def job() -> str:
        time.sleep(seconds)
        return "xong"

    return job
