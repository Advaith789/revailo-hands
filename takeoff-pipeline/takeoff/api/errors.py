from ..core.errors import NotFound, ValidationError

STATUS_BY_ERROR = {
    ValidationError: 400,
    NotFound: 404,
}


def http_status(exc):
    for klass, code in STATUS_BY_ERROR.items():
        if isinstance(exc, klass):
            return code
    return 500


def error_body(exc):
    return {"error": type(exc).__name__, "message": str(exc)}
