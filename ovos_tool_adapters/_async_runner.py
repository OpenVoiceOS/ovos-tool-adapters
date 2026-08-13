# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Async bridge: runs a persistent asyncio event loop in a daemon thread."""

import asyncio
import concurrent.futures
import threading
from typing import Any, Callable, Coroutine


class _AsyncRunner:
    """
    Owns a daemon thread running a private asyncio event loop.

    Provides a synchronous ``run`` method that submits a coroutine to that loop
    and blocks until completion. This avoids ``asyncio.run()`` (which destroys
    the loop and all managed resources after each call) and is safe to call
    from any synchronous context.
    """

    def __init__(self) -> None:
        """Start the daemon thread and its event loop."""
        self._loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()
        self._thread: threading.Thread = threading.Thread(
            target=self._loop.run_forever,
            daemon=True,
            name="ovos-adapter-async",
        )
        self._thread.start()

    def run(self, coro: Coroutine[Any, Any, Any], timeout: int = 30) -> Any:
        """
        Submit *coro* to the runner loop and block until it completes.

        Args:
            coro: An unawaited coroutine object.
            timeout: Maximum seconds to wait for the result.

        Returns:
            Whatever the coroutine returns.

        Raises:
            TimeoutError: If the coroutine does not finish within *timeout* seconds.
            Exception: Any exception raised inside the coroutine.
        """
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    def submit(self, coro: Coroutine[Any, Any, Any]) -> "concurrent.futures.Future":
        """
        Schedule *coro* to run on the runner loop as a single, long-lived task
        and return immediately without waiting for it to finish.

        Unlike :meth:`run`, the caller does not block, and the coroutine is
        free to `await` indefinitely (e.g. waiting on a shutdown signal). This
        is required whenever a coroutine must open and later close an async
        context manager whose implementation cares about being entered and
        exited from the *same* ``asyncio.Task`` (anyio cancel scopes do) — the
        whole lifetime then lives inside one task instead of being split
        across the separate tasks that :meth:`run` would create per call.

        Args:
            coro: An unawaited coroutine object.

        Returns:
            A ``concurrent.futures.Future`` resolved when *coro* completes.
        """
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def call_soon(self, callback: Callable[..., Any], *args: Any) -> None:
        """
        Thread-safely schedule *callback(*args)* to run on the runner loop.

        Use this to poke state (e.g. set an ``asyncio.Event`` or push onto an
        ``asyncio.Queue``) that belongs to a coroutine running on the loop,
        from any other thread.
        """
        self._loop.call_soon_threadsafe(callback, *args)

    def close(self) -> None:
        """Stop the event loop and wait for the daemon thread to finish."""
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)
