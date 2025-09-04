from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
import time
import uuid
from typing import Callable
from app.utils.logging_config import (
    get_logger, 
    LogContext, 
    log_api_access, 
    log_security_event,
    log_performance_metric
)

logger = get_logger(__name__)


class LoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware to handle request/response logging and context management
    """
    
    def __init__(self, app: FastAPI, log_requests: bool = True, log_responses: bool = True):
        super().__init__(app)
        self.log_requests = log_requests
        self.log_responses = log_responses
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Generate request ID
        request_id = str(uuid.uuid4())
        
        # Extract client information
        client_ip = self.get_client_ip(request)
        user_agent = request.headers.get("user-agent", "unknown")
        
        # Extract user information if available (from JWT token)
        user_id = None
        try:
            # Try to extract user ID from token if authorization header exists
            auth_header = request.headers.get("authorization")
            if auth_header and auth_header.startswith("Bearer "):
                from app.utils.security import TokenManager
                token = auth_header.split(" ")[1]
                payload = TokenManager.decode_token(token)
                user_id = payload.get("sub")
        except Exception:
            # Token decode failed, continue without user_id
            pass
        
        # Set up logging context
        with LogContext(req_id=request_id, usr_id=user_id):
            start_time = time.time()
            
            # Log incoming request
            if self.log_requests:
                logger.info(
                    f"Incoming request: {request.method} {request.url.path}",
                    extra={
                        'extra_fields': {
                            'http_method': request.method,
                            'path': str(request.url.path),
                            'query_params': dict(request.query_params),
                            'client_ip': client_ip,
                            'user_agent': user_agent,
                            'request_size_bytes': request.headers.get("content-length", 0),
                            'action': 'request_received'
                        }
                    }
                )
            
            response = None
            status_code = 500
            
            try:
                # Process the request
                response = await call_next(request)
                status_code = response.status_code
                
                # Calculate response time
                response_time = time.time() - start_time
                
                # Log response
                if self.log_responses:
                    logger.info(
                        f"Request completed: {request.method} {request.url.path} - {status_code}",
                        extra={
                            'extra_fields': {
                                'http_method': request.method,
                                'path': str(request.url.path),
                                'status_code': status_code,
                                'response_time_seconds': round(response_time, 4),
                                'client_ip': client_ip,
                                'action': 'request_completed'
                            }
                        }
                    )
                
                # Log to access logger
                log_api_access(
                    method=request.method,
                    path=str(request.url.path),
                    status_code=status_code,
                    response_time=response_time,
                    user_id=user_id,
                    ip_address=client_ip
                )
                
                # Log performance if slow
                if response_time > 1.0:
                    log_performance_metric(
                        operation=f"{request.method} {request.url.path}",
                        duration_seconds=response_time,
                        additional_metrics={
                            'status_code': status_code,
                            'client_ip': client_ip
                        }
                    )
                
                # Log security events for authentication endpoints
                if request.url.path.startswith("/users/auth/"):
                    if status_code == 400 and "login" in request.url.path:
                        log_security_event(
                            event_type="failed_login_attempt",
                            user_id=user_id,
                            ip_address=client_ip,
                            user_agent=user_agent
                        )
                    elif status_code == 200 and "login" in request.url.path:
                        log_security_event(
                            event_type="successful_login",
                            user_id=user_id,
                            ip_address=client_ip,
                            user_agent=user_agent
                        )
                
                return response
                
            except Exception as e:
                response_time = time.time() - start_time
                
                # Log the error
                logger.error(
                    f"Request failed: {request.method} {request.url.path}",
                    extra={
                        'extra_fields': {
                            'http_method': request.method,
                            'path': str(request.url.path),
                            'error_type': type(e).__name__,
                            'error_message': str(e),
                            'response_time_seconds': round(response_time, 4),
                            'client_ip': client_ip,
                            'action': 'request_failed'
                        }
                    },
                    exc_info=True
                )
                
                # Log security event for suspicious activity
                if status_code in [401, 403]:
                    log_security_event(
                        event_type="unauthorized_access_attempt",
                        user_id=user_id,
                        ip_address=client_ip,
                        user_agent=user_agent,
                        details={
                            'path': str(request.url.path),
                            'method': request.method
                        }
                    )
                
                # Re-raise the exception
                raise
    
    def get_client_ip(self, request: Request) -> str:
        """Extract client IP address from request"""
        # Check for forwarded headers (common in load balancers)
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip
        
        # Fallback to direct client IP
        if request.client:
            return request.client.host
        
        return "unknown"


def setup_logging_middleware(app: FastAPI):
    """
    Set up logging middleware for the FastAPI application
    """
    app.add_middleware(
        LoggingMiddleware,
        log_requests=True,
        log_responses=True
    )