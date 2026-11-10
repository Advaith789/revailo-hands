"""Exception hierarchy. The scheduler retries TransientError and gives up on
PermanentError; anything else propagates."""


class TakeoffError(Exception):
    """Base class for errors raised by the pipeline."""


class PermanentError(TakeoffError):
    """The input is bad; retrying will not help."""


class RenderError(PermanentError):
    """The page could not be rendered."""


class TransientError(TakeoffError):
    """A dependency hiccup; the operation may succeed if retried."""


class VisionUnavailable(TransientError):
    """The vision service throttled or timed out."""


class ProgressPublishError(TransientError):
    """The progress event could not be published."""


class StorageBusy(TransientError):
    """The store refused a write because it was busy."""


class ValidationError(TakeoffError):
    """A request failed schema validation."""


class NotFound(TakeoffError):
    """The job does not exist."""


def is_retryable(exc):
    return isinstance(exc, TransientError) and not isinstance(exc, PermanentError)
