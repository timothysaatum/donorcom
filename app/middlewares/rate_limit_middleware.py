from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request, Response
import time
from fastapi.responses import JSONResponse
from typing import Callable


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple rate limiting middleware"""

    def __init__(self, app, max_requests: int = 60):
        super().__init__(app)
        self.max_requests = max_requests
        self.requests = {}

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        client_ip = request.client.host if request.client else "unknown"
        current_time = time.time()

        # Clean old entries (simple sliding window)
        self.requests = {
            ip: [req_time for req_time in times if current_time - req_time < 60]
            for ip, times in self.requests.items()
        }

        # Check rate limit
        if client_ip in self.requests:
            if len(self.requests[client_ip]) >= self.max_requests:
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": "rate_limit_exceeded",
                        "message": "Too many requests",
                    },
                )
        else:
            self.requests[client_ip] = []

        # Add current request
        self.requests[client_ip].append(current_time)

        return await call_next(request)
