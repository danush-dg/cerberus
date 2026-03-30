from __future__ import annotations

import logging
import time
from typing import Any, Callable

from google.api_core.exceptions import Forbidden, NotFound, ServiceUnavailable, TooManyRequests

logger = logging.getLogger(__name__)

_RETRYABLE = (TooManyRequests, ServiceUnavailable)


class CerberusRetryExhausted(Exception):
    def __init__(self, fn_name: str, attempts: int, last_error: Exception):
        self.fn_name = fn_name
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(f"{fn_name} failed after {attempts} attempts: {last_error}")


def gcp_call_with_retry(fn: Callable, *args, max_retries: int = 3, **kwargs) -> Any:
    last_exc: Exception | None = None
    wait_times = [1, 2, 4]
    fn_name = getattr(fn, "__name__", repr(fn))

    for attempt in range(1, max_retries + 1):
        try:
            return fn(*args, **kwargs)
        except (Forbidden, NotFound):
            raise
        except _RETRYABLE as e:
            last_exc = e
            logger.warning(
                "GCP %s attempt %d/%d failed: %s. Retrying.",
                fn_name, attempt, max_retries, e,
            )
            if attempt < max_retries:
                time.sleep(wait_times[attempt - 1])
        except Exception:
            raise

    raise CerberusRetryExhausted(fn_name, max_retries, last_exc)
