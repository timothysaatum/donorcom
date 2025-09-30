import logging
import sys
import os
import traceback
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from pythonjsonlogger import jsonlogger
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from contextvars import ContextVar
from functools import wraps
import time

# Context variables for request tracking
request_id: ContextVar[Optional[str]] = ContextVar('request_id', default=None)
user_id: ContextVar[Optional[str]] = ContextVar('user_id', default=None)
session_id: ContextVar[Optional[str]] = ContextVar('session_id', default=None)

LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

# Environment configuration
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
ENABLE_FILE_LOGGING = os.getenv("ENABLE_FILE_LOGGING", "true").lower() == "true"


class ContextualJsonFormatter(jsonlogger.JsonFormatter):
    """Enhanced JSON formatter that includes contextual information"""
    
    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)
        
        # Add timestamp in ISO format
        log_record['timestamp'] = datetime.now(timezone.utc).isoformat() + 'Z'
        
        # Add environment
        log_record['environment'] = ENVIRONMENT
        
        # Add contextual information
        if request_id.get():
            log_record['request_id'] = request_id.get()
        if user_id.get():
            log_record['user_id'] = user_id.get()
        if session_id.get():
            log_record['session_id'] = session_id.get()
        
        # Add service information
        log_record['service'] = 'blood-bank-api'
        
        # Enhanced error information
        if record.exc_info:
            log_record['exception'] = {
                'type': record.exc_info[0].__name__,
                'message': str(record.exc_info[1]),
                'traceback': traceback.format_exception(*record.exc_info)
            }
        
        # Add extra fields if they exist
        if hasattr(record, 'extra_fields'):
            log_record.update(record.extra_fields)


class ApplicationLogger:
    """Centralized logger class for the application"""
    
    _instance = None
    _loggers = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._setup_logging()
        return cls._instance
    
    def _setup_logging(self):
        """Set up all logging handlers"""
        # Root logger configuration
        root_logger = logging.getLogger()
        root_logger.setLevel(getattr(logging, LOG_LEVEL))
        
        # Clear existing handlers
        root_logger.handlers.clear()
        
        # Custom formatter
        formatter = ContextualJsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(funcName)s:%(lineno)d %(message)s"
        )
        
        # Console handler (always enabled)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        console_handler.setLevel(getattr(logging, LOG_LEVEL))
        root_logger.addHandler(console_handler)
        
        # File handlers (if enabled)
        if ENABLE_FILE_LOGGING:
            self._setup_file_handlers(formatter)
        
        # Configure third-party loggers
        self._configure_third_party_loggers()
    
    def _setup_file_handlers(self, formatter):
        """Set up file-based logging handlers"""
        root_logger = logging.getLogger()
        
        # Application logs (rotating by size)
        app_handler = RotatingFileHandler(
            f"{LOG_DIR}/app.log", 
            maxBytes=10_000_000,  # 10MB
            backupCount=10
        )
        app_handler.setFormatter(formatter)
        app_handler.setLevel(logging.INFO)
        root_logger.addHandler(app_handler)
        
        # Error logs (rotating by time)
        error_handler = TimedRotatingFileHandler(
            f"{LOG_DIR}/error.log",
            when="midnight",
            interval=1,
            backupCount=30
        )
        error_handler.setFormatter(formatter)
        error_handler.setLevel(logging.ERROR)
        root_logger.addHandler(error_handler)
        
        # Security/Auth logs
        security_handler = TimedRotatingFileHandler(
            f"{LOG_DIR}/security.log",
            when="midnight",
            interval=1,
            backupCount=90  # Keep security logs longer
        )
        security_handler.setFormatter(formatter)
        security_logger = logging.getLogger("security")
        security_logger.addHandler(security_handler)
        security_logger.setLevel(logging.INFO)
        
        # Performance logs
        perf_handler = RotatingFileHandler(
            f"{LOG_DIR}/performance.log",
            maxBytes=5_000_000,
            backupCount=5
        )
        perf_handler.setFormatter(formatter)
        perf_logger = logging.getLogger("performance")
        perf_logger.addHandler(perf_handler)
        perf_logger.setLevel(logging.INFO)
        
        # Access logs (separate from uvicorn)
        access_handler = TimedRotatingFileHandler(
            f"{LOG_DIR}/access.log",
            when="midnight",
            interval=1,
            backupCount=30
        )
        access_handler.setFormatter(formatter)
        access_logger = logging.getLogger("access")
        access_logger.addHandler(access_handler)
        access_logger.setLevel(logging.INFO)
    
    def _configure_third_party_loggers(self):
        """Configure third-party library loggers"""
        # Reduce sqlalchemy noise in development
        if ENVIRONMENT.lower() in ["development", "dev"]:
            logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
            logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)
        
        # Uvicorn access logs
        uvicorn_access = logging.getLogger("uvicorn.access")
        uvicorn_access.handlers.clear()  # Remove default handlers
    
    def get_logger(self, name: str) -> logging.Logger:
        """Get a logger instance for a specific module/component"""
        if name not in self._loggers:
            self._loggers[name] = logging.getLogger(name)
        return self._loggers[name]


# Global logger instance
app_logger = ApplicationLogger()


def get_logger(name: str = None) -> logging.Logger:
    """
    Get a logger instance. Use __name__ as the name parameter.
    
    Args:
        name: Logger name, typically __name__ from calling module
    
    Returns:
        Logger instance
    """
    if name is None:
        # Get the calling module's name
        import inspect
        frame = inspect.currentframe().f_back
        name = frame.f_globals.get('__name__', 'unknown')
    
    return app_logger.get_logger(name)


def log_function_call(
    include_args: bool = False,
    include_result: bool = False,
    level: str = "DEBUG"
):
    """
    Decorator to log function calls
    
    Args:
        include_args: Whether to log function arguments
        include_result: Whether to log function return value
        level: Log level for the messages
    """
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            logger = get_logger(func.__module__)
            log_level = getattr(logging, level.upper())
            
            start_time = time.time()
            
            log_data = {
                'function': func.__name__,
                'module': func.__module__,
                'action': 'function_start'
            }
            
            if include_args:
                # Be careful with sensitive data
                safe_args = []
                safe_kwargs = {}
                
                for arg in args:
                    if hasattr(arg, '__class__') and 'password' not in str(arg).lower():
                        safe_args.append(str(arg)[:100])  # Truncate long args
                
                for k, v in kwargs.items():
                    if 'password' not in k.lower() and 'token' not in k.lower():
                        safe_kwargs[k] = str(v)[:100]  # Truncate long values
                
                log_data.update({
                    'args': safe_args,
                    'kwargs': safe_kwargs
                })
            
            logger.log(log_level, f"Starting {func.__name__}", extra={'extra_fields': log_data})
            
            try:
                result = await func(*args, **kwargs)
                
                execution_time = time.time() - start_time
                log_data.update({
                    'action': 'function_end',
                    'execution_time_seconds': round(execution_time, 4),
                    'status': 'success'
                })
                
                if include_result and result is not None:
                    # Be careful not to log sensitive data
                    result_str = str(result)[:200]  # Truncate long results
                    if 'password' not in result_str.lower() and 'token' not in result_str.lower():
                        log_data['result_preview'] = result_str
                
                logger.log(log_level, f"Completed {func.__name__}", extra={'extra_fields': log_data})
                return result
                
            except Exception as e:
                execution_time = time.time() - start_time
                log_data.update({
                    'action': 'function_error',
                    'execution_time_seconds': round(execution_time, 4),
                    'status': 'error',
                    'error_type': type(e).__name__,
                    'error_message': str(e)
                })
                
                logger.error(f"Error in {func.__name__}: {str(e)}", extra={'extra_fields': log_data}, exc_info=True)
                raise
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            logger = get_logger(func.__module__)
            log_level = getattr(logging, level.upper())
            
            start_time = time.time()
            
            log_data = {
                'function': func.__name__,
                'module': func.__module__,
                'action': 'function_start'
            }
            
            logger.log(log_level, f"Starting {func.__name__}", extra={'extra_fields': log_data})
            
            try:
                result = func(*args, **kwargs)
                execution_time = time.time() - start_time
                log_data.update({
                    'action': 'function_end',
                    'execution_time_seconds': round(execution_time, 4),
                    'status': 'success'
                })
                
                logger.log(log_level, f"Completed {func.__name__}", extra={'extra_fields': log_data})
                return result
                
            except Exception as e:
                execution_time = time.time() - start_time
                log_data.update({
                    'action': 'function_error',
                    'execution_time_seconds': round(execution_time, 4),
                    'status': 'error',
                    'error_type': type(e).__name__,
                    'error_message': str(e)
                })
                
                logger.error(f"Error in {func.__name__}: {str(e)}", extra={'extra_fields': log_data}, exc_info=True)
                raise
        
        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    
    return decorator


# Security-specific logging functions
def log_security_event(
    event_type: str,
    user_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None
):
    """Log security-related events"""
    security_logger = logging.getLogger("security")
    
    log_data = {
        'event_type': event_type,
        'ip_address': ip_address,
        'user_agent': user_agent,
        'severity': 'high' if event_type in ['failed_login_attempt', 'unauthorized_access', 'token_abuse'] else 'medium'
    }
    
    if user_id:
        log_data['target_user_id'] = user_id
    
    if details:
        log_data.update(details)
    
    security_logger.info(f"Security event: {event_type}", extra={'extra_fields': log_data})


def log_audit_event(
        action: Optional[str]=None,
        resource_type: Optional[str]=None,
        resource_id: Optional[str]=None,
        old_values: Optional[dict[str, Any]]=None,
        new_values: Optional[dict[str, Any]]=None,
        user_id: Optional[str]=None
    ) -> None:
    """Log audit events"""
    audit_logger = logging.getLogger("audit")
    log_data = {
        'action': action,
        'resource_type': resource_type,
        'resource_id': resource_id,
        'old_values': old_values,
        'new_values': new_values,
        'user_id': user_id,
    }
    audit_logger.info("Audit event occurred", extra={'extra_fields': log_data})


def log_performance_metric(
    operation: str,
    duration_seconds: float,
    additional_metrics: Optional[Dict[str, Any]] = None
):
    """Log performance metrics"""
    perf_logger = logging.getLogger("performance")
    
    log_data = {
        'operation': operation,
        'duration_seconds': round(duration_seconds, 4),
        'performance_category': 'slow' if duration_seconds > 1.0 else 'normal'
    }
    
    if additional_metrics:
        log_data.update(additional_metrics)
    
    perf_logger.info(f"Performance metric: {operation}", extra={'extra_fields': log_data})


def log_api_access(
    method: str,
    path: str,
    status_code: int,
    response_time: float,
    user_id: Optional[str] = None,
    ip_address: Optional[str] = None
):
    """Log API access"""
    access_logger = logging.getLogger("access")
    
    log_data = {
        'http_method': method,
        'path': path,
        'status_code': status_code,
        'response_time_seconds': round(response_time, 4),
        'ip_address': ip_address
    }
    
    if user_id:
        log_data['user_id'] = user_id
    
    access_logger.info(f"{method} {path} - {status_code}", extra={'extra_fields': log_data})


# Structured logging helpers
class LogContext:
    """Context manager for setting request context"""
    
    def __init__(self, req_id: str = None, usr_id: str = None, sess_id: str = None):
        self.request_id = req_id
        self.user_id = usr_id  
        self.session_id = sess_id
        self.tokens = []
    
    def __enter__(self):
        if self.request_id:
            self.tokens.append(request_id.set(self.request_id))
        if self.user_id:
            self.tokens.append(user_id.set(self.user_id))
        if self.session_id:
            self.tokens.append(session_id.set(self.session_id))
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        for token in reversed(self.tokens):
            token.var.set(token.old_value)


# Import asyncio for coroutine check
import asyncio


# Initialize logging on module import
def setup_logging() -> logging.Logger:
    """
    Legacy function for backward compatibility.
    Returns the root logger.
    """
    return logging.getLogger()