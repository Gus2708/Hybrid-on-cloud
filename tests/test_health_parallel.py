"""Behavior of the parallel health-check runner.

/health used to chain checks serially (worst case ~14s) which made the widget
(5s timeout) report false 'API down' and paint healthy services red.
"""
import time

from network_util import run_checks_parallel


def test_returns_each_check_result_by_name():
    out = run_checks_parallel({"a": lambda: {"ok": True}, "b": lambda: {"ok": False}})
    assert out == {"a": {"ok": True}, "b": {"ok": False}}


def test_total_time_is_the_slowest_check_not_the_sum():
    def slow():
        time.sleep(0.3)
        return {"ok": True}

    start = time.time()
    run_checks_parallel({"a": slow, "b": slow, "c": slow})
    assert time.time() - start < 0.7


def test_a_raising_check_is_reported_as_not_ok_without_breaking_others():
    def boom():
        raise RuntimeError("x")

    out = run_checks_parallel({"bad": boom, "good": lambda: {"ok": True}})
    assert out["bad"]["ok"] is False
    assert out["good"] == {"ok": True}


def test_a_hung_check_is_cut_at_the_timeout():
    def hang():
        time.sleep(2)
        return {"ok": True}

    start = time.time()
    out = run_checks_parallel({"hang": hang}, timeout=0.2)
    assert time.time() - start < 1.0
    assert out["hang"]["ok"] is False
