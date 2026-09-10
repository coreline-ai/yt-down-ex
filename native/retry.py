"""App-owned bounded retry policy. Unknown rate limits never retry early."""
import math
from email.utils import parsedate_to_datetime

DELAYS=(5,15,45)
MAX_RETRY_AFTER=3600
TRANSIENT={'NETWORK_ERROR','NETWORK_TIMEOUT','HTTP_SERVER_ERROR'}

def retry_after(value,now):
    try:
        seconds=float(value) if str(value).strip().isdigit() else parsedate_to_datetime(value).timestamp()-now
        return max(0,seconds) if math.isfinite(seconds) else None
    except (TypeError,ValueError,OverflowError):return None

def next_retry(error,attempt,now,jitter=0,delays=DELAYS):
    if attempt not in (1,2,3):return None
    if error.code not in TRANSIENT|{'HTTP_RATE_LIMIT'}:return None
    delay=delays[attempt-1]+max(0,min(1,jitter))
    if error.code=='HTTP_RATE_LIMIT':
        required=getattr(error,'retry_after',None)
        if required is None or not math.isfinite(required) or required<0 or required>MAX_RETRY_AFTER:return None
        delay=max(delay,required)
    return now+delay
