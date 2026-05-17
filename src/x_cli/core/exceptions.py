"""Custom exceptions for x-query."""

from __future__ import annotations


class XQueryError(RuntimeError):
    error_code: str = "api_error"


class AuthenticationError(XQueryError):
    error_code = "not_authenticated"


class RateLimitError(XQueryError):
    error_code = "rate_limited"


class NotFoundError(XQueryError):
    error_code = "not_found"


class NetworkError(XQueryError):
    error_code = "network_error"


class QueryIdError(XQueryError):
    error_code = "query_id_error"


class InvalidInputError(XQueryError):
    error_code = "invalid_input"


class TwitterAPIError(XQueryError):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        if status_code in (401, 403):
            self.error_code = "not_authenticated"
        elif status_code == 429:
            self.error_code = "rate_limited"
        elif status_code == 404:
            self.error_code = "not_found"
        else:
            self.error_code = "api_error"
        super().__init__("Twitter API error (HTTP %d): %s" % (status_code, message))
