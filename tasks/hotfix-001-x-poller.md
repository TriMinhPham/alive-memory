# HOTFIX-001: X Mention Poller — Rate Limit Backoff

## SCOPE RESTRICTION
You are ONLY fixing the X mention poller rate limiting.
Your ONLY deliverables: changes to `body/x_social.py` and its test.
If you touch any file not listed below — STOP. You are out of scope.

## Problem
`XMentionPoller` polls X API every 120 seconds. X Free tier allows 1 request per 15 minutes for user mention timeline. First call succeeds, every subsequent call gets 429. The poller has been hammering 429 every 2 minutes for 11+ hours because:

1. `fetch_mentions()` catches 429 internally, prints it, returns `[]` — doesn't raise
2. The polling loop always sleeps `self.poll_interval` (120s) regardless of errors
3. No exponential backoff, no Retry-After header respect

## Fix

### `body/x_social.py`

**Change 1:** Default `poll_interval` from 120 to 900 (15 min = X Free tier limit)

**Change 2:** In `fetch_mentions()`, on 429 response, propagate the rate limit info:
```python
if response.status_code == 429:
    retry_after = int(response.headers.get("Retry-After", 900))
    print(f"  [XMentions] Rate limited, backing off {retry_after}s")
    raise RateLimitError(retry_after=retry_after)
```

Create a simple exception class:
```python
class RateLimitError(Exception):
    def __init__(self, retry_after: int = 900):
        self.retry_after = retry_after
        super().__init__(f"Rate limited, retry after {retry_after}s")
```

**Change 3:** In the polling loop, handle RateLimitError with backoff:
```python
while self._running:
    try:
        await self._poll_once()
        self._current_interval = self.poll_interval  # reset on success
    except RateLimitError as e:
        self._current_interval = min(e.retry_after * 2, 3600)  # double it, cap 1h
        print(f"  [XMentions] Backing off to {self._current_interval}s")
    except Exception as e:
        print(f"  [XMentions] Poll error: {type(e).__name__}: {e}")
        self._current_interval = min(self._current_interval * 2, 3600)  # backoff on any error
    await asyncio.sleep(self._current_interval)
```

**Change 4:** Initialize `self._current_interval = self.poll_interval` in `__init__`.

## Context — Read These Files
- `body/x_social.py` — lines 150-200 (fetch_mentions + XMentionPoller)
- `body/x_client.py` — the underlying tweepy wrapper

## Test

### Update `tests/test_x_executors.py` (or create `tests/test_x_poller.py`)
- Test: 429 response → RateLimitError raised with retry_after value
- Test: Poller backs off after RateLimitError (mock asyncio.sleep, verify interval doubled)
- Test: Poller resets interval after successful poll
- Test: Backoff caps at 3600s
- Test: Default poll_interval is 900, not 120

## Files to Modify
- `body/x_social.py`

## Files to Create or Modify for Tests
- `tests/test_x_executors.py` (add poller backoff tests) OR `tests/test_x_poller.py` (new file)

## Files NOT to Touch
- Everything else

## Done Signal
- Default poll interval is 900s
- 429 response triggers exponential backoff
- Backoff caps at 1 hour
- Successful poll resets interval
- Tests pass
