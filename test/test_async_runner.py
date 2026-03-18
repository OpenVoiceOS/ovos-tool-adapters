"""Tests for _AsyncRunner."""
import asyncio
import pytest
from ovos_tool_adapters._async_runner import _AsyncRunner


def test_run_simple_coroutine():
    runner = _AsyncRunner()
    try:
        result = runner.run(asyncio.sleep(0, result=42))
        assert result == 42
    finally:
        runner.close()


def test_run_raises_exception():
    runner = _AsyncRunner()
    try:
        async def _fail():
            raise ValueError("boom")
        with pytest.raises(ValueError, match="boom"):
            runner.run(_fail())
    finally:
        runner.close()


def test_run_timeout():
    runner = _AsyncRunner()
    try:
        async def _slow():
            await asyncio.sleep(10)
        with pytest.raises(Exception):  # concurrent.futures.TimeoutError
            runner.run(_slow(), timeout=0.05)
    finally:
        runner.close()


def test_close_is_idempotent():
    runner = _AsyncRunner()
    runner.close()
    runner.close()  # should not raise
