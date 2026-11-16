"""Synchronous state polling for browser smoke tests, without Promise truthiness."""
import time


def wait_for_api_state(page, url, predicate, *, description='API state condition',
                       timeout_ms=30000, poll_interval_ms=100):
    """Return a snapshot only when predicate(snapshot) is literally True.

    The predicate runs after the HTTP response has completed and must return a
    Python bool. A coroutine, JSHandle or other truthy object is a test error.
    """
    if timeout_ms <= 0 or poll_interval_ms <= 0:
        raise ValueError('Polling timeout and interval must be positive')
    deadline = time.monotonic() + timeout_ms / 1000
    snapshot = None
    while (remaining := deadline - time.monotonic()) > 0.005:
        response = page.request.get(url.rstrip('/') + '/api/state',
                                    timeout=min(10000, max(1, int(remaining * 1000))))
        if not response.ok:
            raise AssertionError(f'State request failed: HTTP {response.status}')
        snapshot = response.json()
        matched = predicate(snapshot)
        if type(matched) is not bool:
            raise TypeError('API state predicate must return bool, not an awaitable or truthy object')
        if matched:
            return snapshot
        remaining = deadline - time.monotonic()
        if remaining > 0:
            page.wait_for_timeout(min(poll_interval_ms, remaining * 1000))
    raise AssertionError(f'Timed out waiting for {description}; last status='
                         f'{snapshot.get("status") if snapshot else None!r}')
