from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import settings
from app.core.exceptions import ZohoRateLimitError

zoho_retry = retry(
    stop=stop_after_attempt(settings.MAX_RETRIES),
    wait=wait_exponential(
        multiplier=settings.RETRY_BACKOFF_BASE, min=2, max=60
    ),
    retry=retry_if_exception_type((ZohoRateLimitError, ConnectionError)),
    reraise=True,
)
