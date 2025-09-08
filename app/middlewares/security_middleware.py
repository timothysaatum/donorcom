import time
import hashlib
import ipaddress
from typing import Callable, Set, Dict, List
from datetime import datetime, timedelta, timezone

from fastapi import Request, Response, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.config import settings
from app.utils.logging_config import get_logger, log_security_event

logger = get_logger(__name__)

class SecurityMiddleware(BaseHTTPMiddleware):
    """Comprehensive security middleware for production deployment"""
    
    def __init__(self, app, **kwargs):
        super().__init__(app, **kwargs)
        
        # Rate limiting storage (in production, use Redis)
        self.request_counts: Dict[str, List[float]] = {}
        self.blocked_ips: Dict[str, float] = {}
        
        # Suspicious activity tracking
        self.suspicious_patterns: Set[str] = {
            # SQL Injection patterns
            'union select', 'drop table', 'delete from', 'insert into',
            'update set', 'exec sp_', 'xp_cmdshell', 'sp_executesql',
            
            # XSS patterns  
            '<script', 'javascript:', 'onload=', 'onerror=', 'onclick=',
            'eval(', 'document.cookie', 'document.write',
            
            # Path traversal
            '../', '..\\', '/etc/passwd', '/etc/shadow', 'boot.ini',
            
            # Command injection
            ';cat ', '|cat ', '&cat ', ';ls ', '|ls ', '&ls ',
            ';id;', '|id|', '&id&', 'wget ', 'curl ',
            
            # Common attack tools
            'sqlmap', 'nikto', 'nessus', 'metasploit', 'burpsuite',
            'acunetix', 'netsparker', 'w3af'
        }
        
        # Sensitive paths that require extra protection
        self.sensitive_paths = {
            '/admin', '/api/admin', '/debug', '/test',
            '/config', '/setup', '/.env', '/backup'
        }
        
        # File extension blacklist
        self.dangerous_extensions = {
            '.php', '.asp', '.aspx', '.jsp', '.cgi', '.pl',
            '.py', '.rb', '.sh', '.bat', '.cmd', '.exe'
        }
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.time()
        client_ip = self._extract_client_ip(request)
        
        try:
            # Security checks
            await self._check_ip_blocking(client_ip)
            await self._check_rate_limiting(client_ip, request)
            await self._check_suspicious_requests(request)
            await self._check_path_security(request)
            await self._validate_request_size(request)
            
            # Process request
            response = await call_next(request)
            
            # Add security headers
            self._add_security_headers(response)
            
            # Log successful request
            process_time = time.time() - start_time
            self._log_request(request, response, client_ip, process_time)
            
            return response
            
        except HTTPException as e:
            # Log security violation
            self._log_security_violation(request, client_ip, str(e.detail))
            
            # Track repeated violations
            await self._track_violations(client_ip)
            
            return JSONResponse(
                status_code=e.status_code,
                content={"error": "security_violation", "message": e.detail}
            )
            
        except Exception as e:
            logger.error(f"Security middleware error: {e}")
            return JSONResponse(
                status_code=500,
                content={"error": "internal_error", "message": "Security check failed"}
            )
    
    def _extract_client_ip(self, request: Request) -> str:
        """Extract client IP with proxy support"""
        # Check various headers in order of preference
        ip_headers = [
            "cf-connecting-ip",      # Cloudflare
            "x-real-ip",            # Nginx
            "x-forwarded-for",      # Standard
            "x-client-ip",          # Alternative
            "x-cluster-client-ip",  # Kubernetes
        ]
        
        for header in ip_headers:
            ip_value = request.headers.get(header)
            if ip_value:
                # Take first IP from comma-separated list
                first_ip = ip_value.split(",")[0].strip()
                try:
                    ipaddress.ip_address(first_ip)
                    return first_ip
                except ValueError:
                    continue
        
        # Fallback to request client
        return str(request.client.host) if request.client else "unknown"
    
    async def _check_ip_blocking(self, client_ip: str):
        """Check if IP is currently blocked"""
        if client_ip in self.blocked_ips:
            block_time = self.blocked_ips[client_ip]
            if time.time() - block_time < 3600:  # 1 hour block
                raise HTTPException(
                    status_code=429,
                    detail="IP temporarily blocked due to suspicious activity"
                )
            else:
                # Remove expired block
                del self.blocked_ips[client_ip]
    
    async def _check_rate_limiting(self, client_ip: str, request: Request):
        """Implement rate limiting per IP"""
        current_time = time.time()
        window_start = current_time - 60  # 1 minute window
        
        # Clean old entries
        if client_ip in self.request_counts:
            self.request_counts[client_ip] = [
                req_time for req_time in self.request_counts[client_ip]
                if req_time > window_start
            ]
        else:
            self.request_counts[client_ip] = []
        
        # Add current request
        self.request_counts[client_ip].append(current_time)
        
        # Check limits
        request_count = len(self.request_counts[client_ip])
        
        # Different limits for different endpoints
        if request.url.path.startswith("/api/auth/login"):
            limit = settings.LOGIN_RATE_LIMIT_PER_MINUTE
        else:
            limit = settings.RATE_LIMIT_REQUESTS_PER_MINUTE
        
        if request_count > limit:
            log_security_event(
                event_type="rate_limit_exceeded",
                ip_address=client_ip,
                user_agent=request.headers.get("user-agent", ""),
                details={
                    "path": request.url.path,
                    "requests_in_window": request_count,
                    "limit": limit
                }
            )
            
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded. Max {limit} requests per minute."
            )
    
    async def _check_suspicious_requests(self, request: Request):
        """Check for suspicious request patterns"""
        suspicious_indicators = []
        
        # Check URL for suspicious patterns
        url_str = str(request.url).lower()
        query_params = str(request.query_params).lower() if request.query_params else ""
        
        for pattern in self.suspicious_patterns:
            if pattern in url_str or pattern in query_params:
                suspicious_indicators.append(f"suspicious_pattern_{pattern.replace(' ', '_')}")
        
        # Check for suspicious headers
        user_agent = request.headers.get("user-agent", "").lower()
        
        # Check for bot/scanner user agents
        bot_indicators = [
            'sqlmap', 'nikto', 'nessus', 'burp', 'metasploit',
            'acunetix', 'w3af', 'skipfish', 'owasp'
        ]
        
        for indicator in bot_indicators:
            if indicator in user_agent:
                suspicious_indicators.append(f"attack_tool_{indicator}")
        
        # Check for missing standard headers (might indicate automation)
        if not request.headers.get("accept"):
            suspicious_indicators.append("missing_accept_header")
        
        if not request.headers.get("user-agent"):
            suspicious_indicators.append("missing_user_agent")
        
        # Check for suspicious header values
        referer = request.headers.get("referer", "").lower()
        if any(pattern in referer for pattern in self.suspicious_patterns):
            suspicious_indicators.append("suspicious_referer")
        
        # Log and potentially block if too many indicators
        if suspicious_indicators:
            if len(suspicious_indicators) >= 3:  # High suspicion threshold
                raise HTTPException(
                    status_code=403,
                    detail="Request blocked due to suspicious activity"
                )
            
            # Log for monitoring
            log_security_event(
                event_type="suspicious_request_detected",
                ip_address=self._extract_client_ip(request),
                user_agent=user_agent,
                details={
                    "path": request.url.path,
                    "indicators": suspicious_indicators,
                    "severity": "high" if len(suspicious_indicators) >= 3 else "medium"
                }
            )
    
    async def _check_path_security(self, request: Request):
        """Check for attempts to access sensitive paths"""
        path = request.url.path.lower()
        
        # Block access to sensitive paths in production
        if settings.is_production:
            for sensitive_path in self.sensitive_paths:
                if path.startswith(sensitive_path):
                    # Allow admin path only from whitelisted IPs
                    if sensitive_path == '/admin' and settings.ADMIN_IP_WHITELIST:
                        client_ip = self._extract_client_ip(request)
                        if client_ip not in settings.ADMIN_IP_WHITELIST:
                            raise HTTPException(
                                status_code=403,
                                detail="Access to admin interface restricted"
                            )
                    elif sensitive_path != '/admin':
                        raise HTTPException(
                            status_code=404,
                            detail="Path not found"
                        )
        
        # Check for dangerous file extensions
        for ext in self.dangerous_extensions:
            if path.endswith(ext):
                raise HTTPException(
                    status_code=403,
                    detail="File type not allowed"
                )
        
        # Block common scanner paths
        scanner_paths = [
            '/wp-admin', '/wp-login', '/phpinfo.php', '/phpmyadmin',
            '/admin.php', '/config.php', '/test.php', '/.git',
            '/.svn', '/backup', '/backups'
        ]
        
        for scanner_path in scanner_paths:
            if path.startswith(scanner_path):
                raise HTTPException(
                    status_code=404,
                    detail="Path not found"
                )
    
    async def _validate_request_size(self, request: Request):
        """Validate request size to prevent DoS attacks"""
        content_length = request.headers.get("content-length")
        
        if content_length:
            try:
                size_mb = int(content_length) / (1024 * 1024)
                if size_mb > settings.MAX_REQUEST_SIZE_MB:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Request too large. Max {settings.MAX_REQUEST_SIZE_MB}MB allowed"
                    )
            except ValueError:
                pass  # Invalid content-length header
        
        # Check for suspiciously large URLs (might indicate attack)
        if len(str(request.url)) > 2048:  # Standard URL length limit
            raise HTTPException(
                status_code=414,
                detail="URL too long"
            )
    
    def _add_security_headers(self, response: Response):
        """Add security headers to response"""
        if not settings.SECURITY_HEADERS_ENABLED:
            return
        
        # Prevent MIME type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"
        
        # Prevent framing (clickjacking protection)
        response.headers["X-Frame-Options"] = "DENY"
        
        # XSS protection
        response.headers["X-XSS-Protection"] = "1; mode=block"
        
        # Referrer policy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        # Permissions policy (disable potentially dangerous features)
        response.headers["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=(), "
            "payment=(), usb=(), magnetometer=(), gyroscope=()"
        )
        
        # Content Security Policy (if enabled)
        if settings.CSP_ENABLED:
            csp_policy = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data: https:; "
                "font-src 'self'; "
                "connect-src 'self'; "
                "frame-ancestors 'none'; "
                "base-uri 'self'; "
                "form-action 'self';"
            )
            response.headers["Content-Security-Policy"] = csp_policy
        
        # Add custom security header
        response.headers["X-Security-Policy"] = "strict"
    
    async def _track_violations(self, client_ip: str):
        """Track security violations and implement progressive blocking"""
        # In production, this should use Redis or database
        violation_key = f"violations_{client_ip}"
        current_time = time.time()
        
        # Simple in-memory tracking (replace with Redis in production)
        if not hasattr(self, '_violations'):
            self._violations = {}
        
        if violation_key not in self._violations:
            self._violations[violation_key] = []
        
        # Clean old violations (1 hour window)
        self._violations[violation_key] = [
            v_time for v_time in self._violations[violation_key]
            if current_time - v_time < 3600
        ]
        
        # Add current violation
        self._violations[violation_key].append(current_time)
        
        # Block IP if too many violations
        violation_count = len(self._violations[violation_key])
        if violation_count >= 5:  # 5 violations in 1 hour
            self.blocked_ips[client_ip] = current_time
            
            log_security_event(
                event_type="ip_blocked",
                ip_address=client_ip,
                details={
                    "violation_count": violation_count,
                    "block_duration_hours": 1
                }
            )
    
    def _log_request(self, request: Request, response: Response, client_ip: str, process_time: float):
        """Log request details for monitoring"""
        # Only log in debug mode or for errors
        if settings.DEBUG or response.status_code >= 400:
            logger.info(
                f"{request.method} {request.url.path} - {response.status_code} - {process_time:.3f}s",
                extra={
                    "event_type": "http_request",
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "process_time": process_time,
                    "ip_address": client_ip,
                    "user_agent": request.headers.get("user-agent", "")
                }
            )
    
    def _log_security_violation(self, request: Request, client_ip: str, violation_detail: str):
        """Log security violations"""
        log_security_event(
            event_type="security_violation",
            ip_address=client_ip,
            user_agent=request.headers.get("user-agent", ""),
            details={
                "path": request.url.path,
                "method": request.method,
                "violation": violation_detail,
                "query_params": str(request.query_params) if request.query_params else None
            }
        )


class CSRFProtectionMiddleware(BaseHTTPMiddleware):
    """CSRF protection middleware for state-changing operations"""
    
    def __init__(self, app):
        super().__init__(app)
        self.csrf_exempt_paths = {
            '/api/auth/login',
            '/api/auth/register', 
            '/api/auth/verify-email',
            '/api/auth/forgot-password',
            '/api/auth/reset-password',
            '/health',
            '/metrics'
        }
        
        self.state_changing_methods = {'POST', 'PUT', 'PATCH', 'DELETE'}
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Skip CSRF protection for safe methods and exempt paths
        if (request.method not in self.state_changing_methods or
            request.url.path in self.csrf_exempt_paths):
            return await call_next(request)
        
        # Check for CSRF token in header
        csrf_token = request.headers.get('X-CSRF-Token')
        
        if not csrf_token:
            return JSONResponse(
                status_code=403,
                content={
                    "error": "csrf_token_missing",
                    "message": "CSRF token required for this operation"
                }
            )
        
        # In production, validate CSRF token against session
        # For now, just ensure it exists and is reasonable
        if len(csrf_token) < 16:
            return JSONResponse(
                status_code=403,
                content={
                    "error": "csrf_token_invalid", 
                    "message": "Invalid CSRF token"
                }
            )
        
        return await call_next(request)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Add unique request ID for tracing"""
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Generate or extract request ID
        request_id = request.headers.get('X-Request-ID', self._generate_request_id())
        
        # Add to request state for use in logging
        request.state.request_id = request_id
        
        response = await call_next(request)
        
        # Add request ID to response headers
        response.headers['X-Request-ID'] = request_id
        
        return response
    
    def _generate_request_id(self) -> str:
        """Generate unique request ID"""
        import uuid
        return str(uuid.uuid4())


__all__ = [
    "SecurityMiddleware",
    "CSRFProtectionMiddleware", 
    "RequestIDMiddleware"
]