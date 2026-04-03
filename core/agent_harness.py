"""⚡ JARVIS Agent Harness Primitives
Inspired by Mastra: Built-in primitives for agent behavior.

Instead of writing manual retry/fallback logic, use these primitives:
- Retry: Automatic retry with backoff
- Timeout: Time-limited execution
- Fallback: Automatic fallback on failure
- Circuit Breaker: Prevent repeated failures
- Debounce: Rate-limit operations
- Queue: Serialize concurrent operations
"""

import asyncio
import logging
import time
from typing import Any, Callable, Optional, List, Dict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from functools import wraps
import random

logger = logging.getLogger(__name__)


class RetryStrategy(Enum):
    """Strategies for retry behavior."""

    FIXED = "fixed"  # Wait same time between retries
    LINEAR = "linear"  # Increase wait linearly
    EXPONENTIAL = "exponential"  # Multiply wait each time
    FIBONACCI = "fibonacci"  # Fibonacci-based backoff


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""

    max_attempts: int = 3
    initial_delay: float = 1.0  # seconds
    max_delay: float = 60.0
    strategy: RetryStrategy = RetryStrategy.EXPONENTIAL
    jitter: bool = True  # Add randomness to prevent thundering herd
    retryable_exceptions: tuple = (Exception,)  # Which exceptions trigger retry


@dataclass
class TimeoutConfig:
    """Configuration for timeout behavior."""

    timeout: float = 30.0  # seconds
    timeout_exception: str = "Operation timed out"


@dataclass
class CircuitState:
    """State of a circuit breaker."""

    state: str = "closed"  # closed, open, half-open
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: Optional[float] = None
    last_success_time: Optional[float] = None


class AgentHarness:
    """Collection of agent primitives for reliable execution."""

    # ═══════════════════════════════════════════════════════════════
    # RETRY PRIMITIVE
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    async def retry(func: Callable, *args, config: RetryConfig = None, **kwargs) -> Any:
        """
        Retry a function with configurable backoff strategy.

        Usage:
            result = await AgentHarness.retry(
                api_call,
                config=RetryConfig(max_attempts=5, strategy=RetryStrategy.EXPONENTIAL)
            )
        """
        config = config or RetryConfig()

        last_exception = None

        for attempt in range(config.max_attempts):
            try:
                if asyncio.iscoroutinefunction(func):
                    return await func(*args, **kwargs)
                else:
                    return func(*args, **kwargs)

            except config.retryable_exceptions as e:
                last_exception = e

                if attempt < config.max_attempts - 1:
                    delay = AgentHarness._calculate_delay(attempt, config)

                    logger.warning(
                        f"Retry attempt {attempt + 1}/{config.max_attempts} "
                        f"for {func.__name__ if hasattr(func, '__name__') else 'func'}: {e}. "
                        f"Waiting {delay:.2f}s"
                    )

                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        f"All {config.max_attempts} attempts failed for "
                        f"{func.__name__ if hasattr(func, '__name__') else 'func'}: {e}"
                    )

        raise last_exception

    @staticmethod
    def _calculate_delay(attempt: int, config: RetryConfig) -> float:
        """Calculate delay based on strategy."""
        if config.strategy == RetryStrategy.FIXED:
            delay = config.initial_delay
        elif config.strategy == RetryStrategy.LINEAR:
            delay = config.initial_delay * (attempt + 1)
        elif config.strategy == RetryStrategy.EXPONENTIAL:
            delay = config.initial_delay * (2**attempt)
        elif config.strategy == RetryStrategy.FIBONACCI:
            # Fibonacci: 1, 1, 2, 3, 5, 8...
            fib = [1, 1, 2, 3, 5, 8, 13, 21]
            delay = config.initial_delay * fib[min(attempt, len(fib) - 1)]
        else:
            delay = config.initial_delay

        # Cap at max_delay
        delay = min(delay, config.max_delay)

        # Add jitter
        if config.jitter:
            jitter_amount = delay * 0.2
            delay += random.uniform(-jitter_amount, jitter_amount)

        return max(0, delay)

    # ═══════════════════════════════════════════════════════════════
    # TIMEOUT PRIMITIVE
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    async def with_timeout(
        func: Callable, *args, config: TimeoutConfig = None, **kwargs
    ) -> Any:
        """
        Execute a function with timeout.

        Usage:
            result = await AgentHarness.with_timeout(
                long_operation,
                config=TimeoutConfig(timeout=10.0)
            )
        """
        config = config or TimeoutConfig()

        try:
            if asyncio.iscoroutinefunction(func):
                return await asyncio.wait_for(
                    func(*args, **kwargs), timeout=config.timeout
                )
            else:
                # For sync functions, run in executor
                loop = asyncio.get_event_loop()
                return await asyncio.wait_for(
                    loop.run_in_executor(None, lambda: func(*args, **kwargs)),
                    timeout=config.timeout,
                )
        except asyncio.TimeoutError:
            raise TimeoutError(f"{config.timeout_exception}: {config.timeout}s")

    # ═══════════════════════════════════════════════════════════════
    # FALLBACK PRIMITIVE
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    async def with_fallback(
        primary: Callable,
        fallback: Callable,
        *args,
        should_fallback: Callable[[Exception], bool] = None,
        **kwargs,
    ) -> Any:
        """
        Try primary function, fall back to fallback on failure.

        Usage:
            result = await AgentHarness.with_fallback(
                primary_api_call,
                fallback_cache_lookup,
                should_fallback=lambda e: isinstance(e, ConnectionError)
            )
        """
        should_fallback = should_fallback or (lambda e: True)

        try:
            if asyncio.iscoroutinefunction(primary):
                return await primary(*args, **kwargs)
            else:
                return primary(*args, **kwargs)
        except Exception as e:
            if should_fallback(e):
                logger.warning(f"Primary failed, using fallback: {e}")
                if asyncio.iscoroutinefunction(fallback):
                    return await fallback(*args, **kwargs)
                else:
                    return fallback(*args, **kwargs)
            else:
                raise

    # ═══════════════════════════════════════════════════════════════
    # CIRCUIT BREAKER PRIMITIVE
    # ═══════════════════════════════════════════════════════════════

    def __init__(self):
        self._circuits: Dict[str, CircuitState] = {}

    def circuit_breaker(
        self,
        name: str,
        failure_threshold: int = 5,
        success_threshold: int = 2,
        timeout: float = 60.0,
    ):
        """
        Circuit breaker decorator.

        Usage:
            harness = AgentHarness()

            @harness.circuit_breaker("api_service", failure_threshold=3)
            async def api_call():
                ...
        """

        def decorator(func: Callable) -> Callable:
            if name not in self._circuits:
                self._circuits[name] = CircuitState()

            @wraps(func)
            async def wrapper(*args, **kwargs):
                circuit = self._circuits[name]
                current_time = time.time()

                # Check if circuit is open
                if circuit.state == "open":
                    # Check if timeout has passed to try half-open
                    if (
                        circuit.last_failure_time
                        and current_time - circuit.last_failure_time > timeout
                    ):
                        circuit.state = "half-open"
                        logger.info(f"Circuit '{name}' transitioning to half-open")
                    else:
                        raise Exception(f"Circuit '{name}' is open - failing fast")

                # Execute function
                try:
                    if asyncio.iscoroutinefunction(func):
                        result = await func(*args, **kwargs)
                    else:
                        result = func(*args, **kwargs)

                    # Success
                    circuit.success_count += 1
                    circuit.last_success_time = current_time

                    if circuit.state == "half-open":
                        if circuit.success_count >= success_threshold:
                            circuit.state = "closed"
                            circuit.failure_count = 0
                            logger.info(f"Circuit '{name}' closed after recovery")

                    return result

                except Exception as e:
                    # Failure
                    circuit.failure_count += 1
                    circuit.last_failure_time = current_time
                    circuit.success_count = 0

                    if circuit.failure_count >= failure_threshold:
                        circuit.state = "open"
                        logger.warning(
                            f"Circuit '{name}' opened after {circuit.failure_count} failures"
                        )

                    raise

            return wrapper

        return decorator

    def get_circuit_state(self, name: str) -> Optional[Dict]:
        """Get current state of a circuit breaker."""
        circuit = self._circuits.get(name)
        if circuit:
            return {
                "state": circuit.state,
                "failures": circuit.failure_count,
                "successes": circuit.success_count,
            }
        return None

    def reset_circuit(self, name: str):
        """Manually reset a circuit breaker."""
        if name in self._circuits:
            self._circuits[name] = CircuitState()

    # ═══════════════════════════════════════════════════════════════
    # DEBOUNCE PRIMITIVE
    # ═══════════════════════════════════════════════════════════════

    def __init__(self):
        self._debounce_timers: Dict[str, asyncio.TimerHandle] = {}
        self._debounce_locks: Dict[str, asyncio.Lock] = {}

    async def debounce(
        self, key: str, func: Callable, *args, delay: float = 0.5, **kwargs
    ) -> Any:
        """
        Debounce rapid calls - only execute after delay of no calls.

        Usage:
            result = await harness.debounce(
                "save-file",
                save_function,
                delay=1.0
            )
        """
        # Cancel existing timer
        if key in self._debounce_timers:
            self._debounce_timers[key].cancel()

        # Create lock if needed
        if key not in self._debounce_locks:
            self._debounce_locks[key] = asyncio.Lock()

        # Create completion event
        completion_event = asyncio.Event()
        result_holder = [None]
        error_holder = [None]

        async def execute():
            async with self._debounce_locks[key]:
                try:
                    if asyncio.iscoroutinefunction(func):
                        result_holder[0] = await func(*args, **kwargs)
                    else:
                        result_holder[0] = func(*args, **kwargs)
                except Exception as e:
                    error_holder[0] = e
                finally:
                    completion_event.set()

        # Schedule execution
        loop = asyncio.get_event_loop()
        timer = loop.call_later(delay, lambda: asyncio.create_task(execute()))
        self._debounce_timers[key] = timer

        # Wait for completion
        await completion_event.wait()

        if error_holder[0]:
            raise error_holder[0]
        return result_holder[0]

    # ═══════════════════════════════════════════════════════════════
    # QUEUE PRIMITIVE
    # ═══════════════════════════════════════════════════════════════

    def __init__(self):
        self._queues: Dict[str, asyncio.Queue] = {}
        self._queue_tasks: Dict[str, asyncio.Task] = {}

    async def enqueue(
        self, queue_name: str, func: Callable, *args, maxsize: int = 0, **kwargs
    ) -> Any:
        """
        Serialize operations through a named queue.

        Usage:
            result = await harness.enqueue(
                "file-operations",
                write_file,
                data
            )
        """
        # Create queue if needed
        if queue_name not in self._queues:
            self._queues[queue_name] = asyncio.Queue(maxsize=maxsize)

            # Start queue processor
            async def process_queue():
                while True:
                    try:
                        item = await self._queues[queue_name].get()
                        func, args, kwargs, event, result_holder, error_holder = item

                        try:
                            if asyncio.iscoroutinefunction(func):
                                result_holder[0] = await func(*args, **kwargs)
                            else:
                                result_holder[0] = func(*args, **kwargs)
                        except Exception as e:
                            error_holder[0] = e
                        finally:
                            event.set()

                    except asyncio.CancelledError:
                        break
                    except Exception as e:
                        logger.error(f"Queue processor error: {e}")

            self._queue_tasks[queue_name] = asyncio.create_task(process_queue())

        # Enqueue item
        completion_event = asyncio.Event()
        result_holder = [None]
        error_holder = [None]

        await self._queues[queue_name].put(
            (func, args, kwargs, completion_event, result_holder, error_holder)
        )

        # Wait for completion
        await completion_event.wait()

        if error_holder[0]:
            raise error_holder[0]
        return result_holder[0]

    # ═══════════════════════════════════════════════════════════════
    # COMBINED PATTERNS
    # ═══════════════════════════════════════════════════════════════

    async def resilient_call(
        self,
        func: Callable,
        *args,
        retry_config: RetryConfig = None,
        timeout_config: TimeoutConfig = None,
        fallback: Callable = None,
        circuit_name: str = None,
        **kwargs,
    ) -> Any:
        """
        Combine multiple primitives for resilient execution.

        Usage:
            result = await harness.resilient_call(
                api_function,
                retry_config=RetryConfig(max_attempts=3),
                timeout_config=TimeoutConfig(timeout=30),
                fallback=cache_lookup,
                circuit_name="api"
            )
        """
        # Wrap with timeout
        if timeout_config:
            func = self._wrap_with_timeout(func, timeout_config)

        # Apply circuit breaker if specified
        if circuit_name:
            func = self.circuit_breaker(circuit_name)(func)

        # Apply retry
        if retry_config:
            func = self._wrap_with_retry(func, retry_config)

        # Apply fallback
        if fallback:
            return await self.with_fallback(func, fallback, *args, **kwargs)

        # Execute
        if asyncio.iscoroutinefunction(func):
            return await func(*args, **kwargs)
        else:
            return func(*args, **kwargs)

    def _wrap_with_timeout(self, func: Callable, config: TimeoutConfig) -> Callable:
        """Wrap function with timeout."""

        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await self.with_timeout(func, *args, config=config, **kwargs)

        return wrapper

    def _wrap_with_retry(self, func: Callable, config: RetryConfig) -> Callable:
        """Wrap function with retry."""

        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await self.retry(func, *args, config=config, **kwargs)

        return wrapper


# Decorator versions for easy use
def retry(max_attempts: int = 3, strategy: RetryStrategy = RetryStrategy.EXPONENTIAL):
    """Decorator for easy retry."""
    config = RetryConfig(max_attempts=max_attempts, strategy=strategy)

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await AgentHarness.retry(func, *args, config=config, **kwargs)

        return wrapper

    return decorator


def with_timeout(timeout: float):
    """Decorator for easy timeout."""
    config = TimeoutConfig(timeout=timeout)

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await AgentHarness.with_timeout(func, *args, config=config, **kwargs)

        return wrapper

    return decorator


# Standalone test
if __name__ == "__main__":
    import asyncio

    async def test():
        harness = AgentHarness()

        # Test retry
        attempt_count = [0]

        async def flaky_function():
            attempt_count[0] += 1
            if attempt_count[0] < 3:
                raise ConnectionError("Simulated failure")
            return "Success!"

        result = await harness.retry(
            flaky_function,
            config=RetryConfig(max_attempts=5, strategy=RetryStrategy.EXPONENTIAL),
        )
        print(f"Retry result: {result}")

        # Test timeout
        async def slow_function():
            await asyncio.sleep(2)
            return "Done"

        try:
            result = await harness.with_timeout(
                slow_function, config=TimeoutConfig(timeout=0.5)
            )
        except TimeoutError as e:
            print(f"Timeout works: {e}")

        # Test circuit breaker
        harness2 = AgentHarness()

        @harness2.circuit_breaker("test-circuit", failure_threshold=2, timeout=5)
        async def circuit_function():
            raise ConnectionError("Fail")

        for i in range(5):
            try:
                await circuit_function()
            except Exception as e:
                print(f"Attempt {i + 1}: {e}")

        print(f"Circuit state: {harness2.get_circuit_state('test-circuit')}")

    asyncio.run(test())
