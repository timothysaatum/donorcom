import ipaddress
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, HashingError, VerificationError
from datetime import datetime, timedelta, timezone
from jose import JWTError, jwt
from typing import Optional, Tuple
import os
import hashlib
from app.models.rbac import Role
from fastapi import Depends, HTTPException, status, WebSocket, Request
from fastapi.security import OAuth2PasswordBearer
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession
from app.dependencies import get_db
from app.models.user import User, RefreshToken, UserSession
from sqlalchemy.future import select
from uuid import UUID
from sqlalchemy.orm import selectinload
from app.models.health_facility import Facility
from uuid import uuid4
from app.utils.logging_config import get_logger, log_security_event

load_dotenv()

# Get logger for security module
logger = get_logger(__name__)

# Argon2 password hashing configuration
ph = PasswordHasher(
    time_cost=3,        
    memory_cost=65536,  
    parallelism=1,      
    hash_len=32,        
    salt_len=16         
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

# JWT configuration
SECRET_KEY = os.getenv("SECRET_KEY")
assert SECRET_KEY, "SECRET_KEY is not set in the .env file"

# JWT and Token Configuration
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 180
REFRESH_TOKEN_EXPIRE_DAYS = 7

# Account lockout configuration
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_DURATION_MINUTES = 15


class SessionManager:
    """Enhanced session management with robust device fingerprinting"""
    
    @staticmethod
    def normalize_header(header_value: str) -> str:
        """Normalize header values by removing extra whitespace and converting to lowercase"""
        if not header_value:
            return ""
        return " ".join(header_value.strip().lower().split())
    
    @staticmethod
    def extract_client_ip(request: Request) -> str:
        """Extract client IP with comprehensive proxy support"""
        # Check for various proxy headers in order of preference
        ip_headers = [
            "cf-connecting-ip",      # Cloudflare
            "x-real-ip",            # Nginx
            "x-forwarded-for",      # Standard proxy header
            "x-client-ip",          # Alternative
            "x-cluster-client-ip",  # Kubernetes
        ]
        
        for header in ip_headers:
            ip_value = request.headers.get(header)
            if ip_value:
                # Handle comma-separated IPs (take the first one)
                first_ip = ip_value.split(",")[0].strip()
                # Validate IP format
                try:
                    ipaddress.ip_address(first_ip)
                    return first_ip
                except ValueError:
                    continue
        
        # Fallback to request client
        return str(request.client.host) if request.client else "unknown"
    
    @staticmethod
    def parse_user_agent_simple(user_agent: str) -> dict:
        """Simple user agent parsing without external dependencies"""
        if not user_agent:
            return {
                "browser": "unknown",
                "os": "unknown",
                "device_type": "unknown",
                "is_mobile": False,
                "is_bot": True
            }
        
        ua_lower = user_agent.lower()
        
        # Browser detection
        browsers = {
            "chrome": ["chrome", "crios"],
            "firefox": ["firefox", "fxios"],
            "safari": ["safari"],
            "edge": ["edge", "edg"],
            "opera": ["opera", "opr"],
            "internet_explorer": ["trident", "msie"]
        }
        
        browser = "unknown"
        for browser_name, patterns in browsers.items():
            if any(pattern in ua_lower for pattern in patterns):
                browser = browser_name
                break
        
        # OS detection
        operating_systems = {
            "windows": ["windows", "win32", "win64"],
            "macos": ["mac os", "darwin"],
            "linux": ["linux", "ubuntu", "debian"],
            "android": ["android"],
            "ios": ["iphone", "ipad", "ipod"]
        }
        
        os = "unknown"
        for os_name, patterns in operating_systems.items():
            if any(pattern in ua_lower for pattern in patterns):
                os = os_name
                break
        
        # Device type detection
        is_mobile = any(term in ua_lower for term in ["mobile", "android", "iphone"])
        is_tablet = any(term in ua_lower for term in ["tablet", "ipad"])
        
        if is_tablet:
            device_type = "tablet"
        elif is_mobile:
            device_type = "mobile"
        else:
            device_type = "desktop"
        
        # Bot detection
        bot_indicators = [
            "bot", "crawler", "spider", "scraper", "curl", "wget", 
            "python", "java", "axios", "node", "phantom", "selenium",
            "headless", "automated", "monitor", "test"
        ]
        is_bot = any(indicator in ua_lower for indicator in bot_indicators)
        
        return {
            "browser": browser,
            "os": os,
            "device_type": device_type,
            "is_mobile": is_mobile,
            "is_tablet": is_tablet,
            "is_bot": is_bot
        }
    
    @staticmethod
    def calculate_device_risk_score(device_data: dict) -> tuple[int, list]:
        """Calculate risk score based on device characteristics"""
        risk_score = 0
        risk_factors = []
        
        # Missing or suspicious user agent
        if not device_data.get("user_agent") or device_data.get("parsed_ua", {}).get("is_bot"):
            risk_score += 40
            risk_factors.append("suspicious_user_agent")
        
        # Missing standard browser headers
        if not device_data.get("accept_language"):
            risk_score += 25
            risk_factors.append("missing_accept_language")
        
        if not device_data.get("accept_encoding"):
            risk_score += 20
            risk_factors.append("missing_accept_encoding")
        
        # Check for automation tools in user agent
        user_agent = device_data.get("user_agent", "").lower()
        automation_indicators = ["selenium", "webdriver", "phantom", "headless", "automated"]
        if any(indicator in user_agent for indicator in automation_indicators):
            risk_score += 50
            risk_factors.append("automation_detected")
        
        # Suspicious IP patterns
        client_ip = device_data.get("client_ip", "")
        if client_ip in ["unknown", "127.0.0.1", "localhost"] or not client_ip:
            risk_score += 15
            risk_factors.append("suspicious_ip")
        
        # Check for common VPN/proxy patterns
        vpn_indicators = ["vpn", "proxy", "tor"]
        headers_str = " ".join([
            device_data.get("user_agent", ""),
            device_data.get("accept_language", ""),
            device_data.get("accept_encoding", "")
        ]).lower()
        
        if any(indicator in headers_str for indicator in vpn_indicators):
            risk_score += 30
            risk_factors.append("proxy_detected")
        
        return min(risk_score, 100), risk_factors
    
    @staticmethod
    async def create_session(
        db: AsyncSession, 
        user_id: UUID, 
        request: Request,
        login_method: str = "password"
    ) -> UserSession:
        """Create a new user session with enhanced tracking"""
        
        # Extract device information
        device_info = SessionManager.extract_device_info(request)
        
        # Create session record
        session = UserSession(
            user_id=user_id,
            session_token=str(uuid4()),
            device_fingerprint=device_info.get("enhanced_fingerprint"),
            user_agent=device_info.get("user_agent"),
            user_agent_hash=hashlib.sha256(device_info.get("user_agent", "").encode()).hexdigest()[:16],
            ip_address=device_info.get("client_ip"),
            login_method=login_method,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24)  
        )
        
        db.add(session)
        await db.commit()
        await db.refresh(session)
        
        logger.info(
            "User session created",
            extra={
                "event_type": "session_created",
                "user_id": str(user_id),
                "session_id": str(session.id),
                "ip_address": device_info.get("client_ip")
            }
        )
        
        return session
    
    @staticmethod
    async def validate_session(
        db: AsyncSession, 
        session_id: UUID, 
        request: Request
    ) -> Optional[UserSession]:
        """Validate session and update activity"""
        
        result = await db.execute(
            select(UserSession)
            .options(selectinload(UserSession.user))
            .where(UserSession.id == session_id)
        )
        session = result.scalar_one_or_none()
        
        if not session or not session.is_valid:
            return None
            
        # Update activity and perform security checks
        current_ip = getattr(request.client, 'host', 'unknown') if request.client else 'unknown'
        session.update_activity(current_ip)
        
        # Security monitoring
        if session.ip_address != current_ip:
            log_security_event(
                event_type="ip_change_detected",
                user_id=str(session.user_id),
                ip_address=current_ip,
                details={
                    "session_id": str(session.id),
                    "previous_ip": session.ip_address,
                    "new_ip": current_ip
                }
            )
            session.mark_suspicious("ip_change")
        
        await db.commit()
        return session
    
    @staticmethod
    async def terminate_session(
        db: AsyncSession, 
        session_id: UUID, 
        reason: str = "logout"
    ) -> bool:
        """Terminate a specific session"""
        
        result = await db.execute(
            select(UserSession).where(UserSession.id == session_id)
        )
        session = result.scalar_one_or_none()
        
        if session:
            session.terminate(reason)
            await db.commit()
            
            logger.info(
                "Session terminated",
                extra={
                    "event_type": "session_terminated",
                    "session_id": str(session_id),
                    "user_id": str(session.user_id),
                    "reason": reason
                }
            )
            return True
        
        return False
    
    @staticmethod
    async def terminate_all_user_sessions(
        db: AsyncSession, 
        user_id: UUID, 
        except_session_id: UUID = None
    ) -> int:
        """Terminate all sessions for a user except specified one"""
        
        query = select(UserSession).where(
            UserSession.user_id == user_id,
            UserSession.is_active == True
        )
        
        if except_session_id:
            query = query.where(UserSession.id != except_session_id)
            
        result = await db.execute(query)
        sessions = result.scalars().all()
        
        terminated_count = 0
        for session in sessions:
            session.terminate("user_logout_all")
            terminated_count += 1
        
        await db.commit()
        
        logger.info(
            f"Terminated {terminated_count} sessions for user",
            extra={
                "event_type": "multiple_sessions_terminated",
                "user_id": str(user_id),
                "terminated_count": terminated_count
            }
        )
        
        return terminated_count
    

    @staticmethod
    def extract_device_info(request: Request) -> dict:
        """
        Extract comprehensive device fingerprinting information for robust authentication
        
        Enhanced version of your original method that maintains compatibility
        while adding security features and better error handling.
        """
        # Extract basic headers (same as original)
        user_agent = request.headers.get("user-agent", "").strip()
        accept_language = request.headers.get("accept-language", "").strip()
        accept_encoding = request.headers.get("accept-encoding", "").strip()
        
        # Get client IP with enhanced proxy support
        client_ip = SessionManager.extract_client_ip(request)
        
        # Parse user agent for additional insights
        parsed_ua = SessionManager.parse_user_agent_simple(user_agent)
        
        # Extract additional security-relevant headers
        security_headers = {
            "connection": request.headers.get("connection", ""),
            "cache_control": request.headers.get("cache-control", ""),
            "sec_ch_ua": request.headers.get("sec-ch-ua", ""),
            "sec_ch_ua_platform": request.headers.get("sec-ch-ua-platform", ""),
            "sec_ch_ua_mobile": request.headers.get("sec-ch-ua-mobile", ""),
            "sec_fetch_site": request.headers.get("sec-fetch-site", ""),
            "sec_fetch_mode": request.headers.get("sec-fetch-mode", ""),
            "dnt": request.headers.get("dnt", "")
        }
        
        # Normalize language for consistency (take primary language only)
        normalized_language = accept_language.split(",")[0].split(";")[0].lower() if accept_language else ""
        normalized_encoding = SessionManager.normalize_header(accept_encoding)
        
        # Create multiple fingerprint levels for flexibility
        
        # 1. Basic fingerprint (compatible with your original)
        basic_fingerprint_data = f"{user_agent}|{accept_language}|{accept_encoding}"
        basic_fingerprint = hashlib.sha256(basic_fingerprint_data.encode()).hexdigest()[:32]
        
        # 2. Enhanced fingerprint (more stable components)
        stable_components = [
            parsed_ua.get("browser", ""),
            parsed_ua.get("os", ""),
            normalized_language,
            normalized_encoding,
            client_ip if not client_ip.startswith(("127.", "192.168.", "10.", "172.")) else ""
        ]
        
        enhanced_fingerprint_data = "|".join(filter(None, stable_components))
        enhanced_fingerprint = hashlib.sha256(
            enhanced_fingerprint_data.encode('utf-8')
        ).hexdigest()[:32]
        
        # 3. Security fingerprint (includes security headers)
        security_components = stable_components + [
            security_headers.get("sec_ch_ua", ""),
            security_headers.get("sec_ch_ua_platform", ""),
            security_headers.get("connection", "")
        ]
        
        security_fingerprint_data = "|".join(filter(None, security_components))
        security_fingerprint = hashlib.sha256(
            security_fingerprint_data.encode('utf-8')
        ).hexdigest()[:32]
        
        # Compile device information
        device_data = {
            # Original fields for backward compatibility
            "fingerprint": basic_fingerprint,  # Keep your original field name
            "user_agent": user_agent,
            "accept_language": accept_language,
            "accept_encoding": accept_encoding,
            
            # Enhanced fields
            "client_ip": client_ip,
            "enhanced_fingerprint": enhanced_fingerprint,
            "security_fingerprint": security_fingerprint,
            "parsed_ua": parsed_ua,
            "normalized_language": normalized_language,
            "normalized_encoding": normalized_encoding,
            "security_headers": security_headers,
            "timestamp": datetime.now(timezone.utc).timestamp(),
            
            # Fingerprint metadata
            "fingerprint_components": len([c for c in stable_components if c]),
            "has_security_headers": bool(any(security_headers.values()))
        }
        
        # Calculate risk assessment
        risk_score, risk_factors = SessionManager.calculate_device_risk_score(device_data)
        device_data.update({
            "risk_score": risk_score,
            "risk_factors": risk_factors,
            "risk_level": "high" if risk_score >= 70 else "medium" if risk_score >= 30 else "low"
        })
        
        return device_data


class TokenManager:
    """Enhanced token management with session integration"""
    
    @staticmethod
    def create_access_token(
        data: dict, 
        expires_delta: Optional[timedelta] = None,
        session_id: Optional[UUID] = None
    ) -> str:
        """Create a JWT access token with optional session reference"""
        secret_key = os.getenv("SECRET_KEY")
        algorithm = os.getenv("ALGORITHM", "HS256")

        to_encode = data.copy()
        expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
        to_encode.update({"exp": expire, "type": "access"})
        
        # Include session ID if provided
        if session_id:
            to_encode["sid"] = str(session_id)

        return jwt.encode(to_encode, secret_key, algorithm=algorithm)

    @staticmethod
    def create_refresh_token(user_id: UUID, device_info: str = None, ip_address: str = None) -> str:
        """Create a refresh token with enhanced tracking"""
        secret_key = os.getenv("SECRET_KEY")
        algorithm = os.getenv("ALGORITHM", "HS256")

        jti = str(uuid4())
        expires = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
        
        to_encode = {
            "sub": str(user_id),
            "exp": expires,
            "type": "refresh",
            "jti": jti
        }

        token = jwt.encode(to_encode, secret_key, algorithm=algorithm)
        return token

    @staticmethod
    def decode_token(token: str) -> dict:
        """Decode and verify a JWT token"""
        secret_key = os.getenv("SECRET_KEY")
        algorithm = os.getenv("ALGORITHM", "HS256")

        try:
            payload = jwt.decode(token, secret_key, algorithms=[algorithm])
            return payload
        except JWTError as e:
            raise ValueError("Invalid or expired token") from e

    @staticmethod
    async def create_refresh_token_record(
        db: AsyncSession, 
        user_id: UUID, 
        token: str, 
        device_info: str = None, 
        ip_address: str = None
    ) -> RefreshToken:
        """Create a refresh token database record with hashed token"""
        try:
            if not isinstance(user_id, UUID):
                try:
                    user_id = UUID(str(user_id))
                except Exception:
                    raise ValueError("user_id must be a UUID or UUID string")

            token_hash = hashlib.sha256(token.encode()).hexdigest()
            payload = TokenManager.decode_token(token)
            expires_at = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)

            refresh_token_record = RefreshToken(
                user_id=user_id,
                token_hash=token_hash,
                expires_at=expires_at,
                device_info=device_info,
                ip_address=ip_address
            )

            db.add(refresh_token_record)
            await db.commit()
            await db.refresh(refresh_token_record)

            logger.info(
                "Refresh token record created",
                extra={
                    "event_type": "refresh_token_created",
                    "user_id": str(user_id),
                    "token_id": str(refresh_token_record.id),
                    "expires_at": expires_at.isoformat()
                }
            )

            return refresh_token_record

        except Exception as e:
            logger.error(
                "Failed to create refresh token record",
                extra={
                    "event_type": "refresh_token_creation_failed",
                    "user_id": str(user_id),
                    "error": str(e)
                }, exc_info=True
            )
            await db.rollback()
            raise

    @staticmethod
    async def validate_refresh_token(db: AsyncSession, token: str) -> Optional[RefreshToken]:
        """Validate refresh token against database records"""
        try:
            token_hash = hashlib.sha256(token.encode()).hexdigest()
        
            result = await db.execute(
               select(RefreshToken)
               .options(selectinload(RefreshToken.user))
               .where(RefreshToken.token_hash == token_hash)
            )
            refresh_token_record = result.scalar_one_or_none()
        
            if not refresh_token_record:
                logger.warning(
                    "Refresh token validation failed - token not found",
                    extra={
                        "event_type": "refresh_token_not_found",
                        "token_hash": token_hash[:16] + "..."
                    }
                )
                return None
        
            if not refresh_token_record.is_valid:
                logger.warning(
                    "Refresh token validation failed - token invalid",
                    extra={
                        "event_type": "refresh_token_invalid",
                        "token_id": str(refresh_token_record.id),
                        "expired": refresh_token_record.is_expired,
                        "revoked": refresh_token_record.revoked
                    }
                )
                return None

            logger.info(
                "Refresh token validation successful",
                extra={
                    "event_type": "refresh_token_validated",
                    "token_id": str(refresh_token_record.id),
                    "user_id": str(refresh_token_record.user_id)
                }
            )
        
            return refresh_token_record
        
        except Exception as e:
            logger.error(
                "Refresh token validation error",
                extra={
                    "event_type": "refresh_token_validation_error",
                    "error": str(e)
                }, exc_info=True
            )
            return None

    @staticmethod
    async def revoke_refresh_token(db: AsyncSession, token_id: UUID) -> bool:
        """Revoke a specific refresh token"""
        try:
            result = await db.execute(
                select(RefreshToken).where(RefreshToken.id == token_id)
            )
            refresh_token = result.scalar_one_or_none()
            
            if refresh_token:
                refresh_token.revoke()
                await db.commit()
                
                logger.info(
                    "Refresh token revoked",
                    extra={
                        "event_type": "refresh_token_revoked",
                        "token_id": str(token_id),
                        "user_id": str(refresh_token.user_id)
                    }
                )
                return True
            
            return False
            
        except Exception as e:
            logger.error(
                "Failed to revoke refresh token",
                extra={
                    "event_type": "refresh_token_revoke_failed",
                    "token_id": str(token_id),
                    "error": str(e)
                },
                exc_info=True
            )
            await db.rollback()
            return False



def get_password_hash(password: str) -> str:
    """Hash a plaintext password using Argon2"""
    try:
        return ph.hash(password)
    except HashingError as e:
        logger.error(
            "Password hashing failed",
            extra={
                "event_type": "password_hashing_failed",
                "error": str(e)
            }
        )
        raise HTTPException(
            status_code=500, 
            detail="Password hashing failed"
        ) from e


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against an Argon2 hashed password"""
    try:
        ph.verify(hashed_password, plain_password)
        return True
    except VerifyMismatchError:
        return False
    except VerificationError as e:
        logger.error(
            "Password verification error",
            extra={
                "event_type": "password_verification_error",
                "error": str(e)
            }
        )
        return False


def needs_rehash(hashed_password: str) -> bool:
    """Check if password hash needs to be updated with current parameters"""
    try:
        return ph.check_needs_rehash(hashed_password)
    except Exception:
        return True


async def handle_failed_login(
    db: AsyncSession, 
    user: User, 
    ip_address: str = None,
    user_agent: str = None
) -> None:
    """Handle failed login attempt with account locking"""
    try:
        user.increment_failed_attempts(
            max_attempts=MAX_LOGIN_ATTEMPTS,
            lockout_duration_minutes=LOCKOUT_DURATION_MINUTES
        )
        
        await db.commit()
        
        log_security_event(
            event_type="failed_login_attempt",
            user_id=str(user.id),
            ip_address=ip_address,
            user_agent=user_agent,
            details={
                "failed_attempts": user.failed_login_attempts,
                "account_locked": user.is_locked,
                "locked_until": user.locked_until.isoformat() if user.locked_until else None
            }
        )
        
        logger.warning(
            "Failed login attempt recorded",
            extra={
                "event_type": "failed_login_recorded",
                "user_id": str(user.id),
                "failed_attempts": user.failed_login_attempts,
                "account_locked": user.is_locked
            }
        )
        
    except Exception as e:
        logger.error(
            "Failed to handle failed login",
            extra={
                "event_type": "failed_login_handling_error",
                "user_id": str(user.id),
                "error": str(e)
            },
            exc_info=True
        )
        await db.rollback()


async def handle_successful_login(
    db: AsyncSession, 
    user: User,
    ip_address: str = None,
    user_agent: str = None
) -> None:
    """Handle successful login with security logging"""
    try:
        user.reset_failed_attempts()
        await db.commit()
        
        log_security_event(
            event_type="successful_login",
            user_id=str(user.id),
            ip_address=ip_address,
            user_agent=user_agent,
            details={
                "last_login": user.last_login.isoformat(),
                "failed_attempts_reset": True
            }
        )
        
        logger.info(
            "Successful login recorded",
            extra={
                "event_type": "successful_login_recorded",
                "user_id": str(user.id),
                "last_login": user.last_login.isoformat()
            }
        )
        
    except Exception as e:
        logger.error(
            "Failed to handle successful login",
            extra={
                "event_type": "successful_login_handling_error",
                "user_id": str(user.id),
                "error": str(e)
            },
            exc_info=True
        )
        await db.rollback()


async def authenticate_user(
    db: AsyncSession, 
    email: str, 
    password: str,
    ip_address: str = None,
    user_agent: str = None
) -> Tuple[bool, Optional[User], Optional[str]]:
    """
    Authenticate user with enhanced security features
    Returns: (success, user, error_message)
    """

    try:
        result = await db.execute(
            select(User)
            .options(
                selectinload(User.roles).selectinload(Role.permissions),
                selectinload(User.facility).selectinload(Facility.blood_bank),
                selectinload(User.work_facility).selectinload(Facility.blood_bank)
            )
            .where(User.email == email)
        )

        user = result.scalar_one_or_none()
        if not user:
            log_security_event(
                event_type="authentication_failed",
                ip_address=ip_address,
                user_agent=user_agent,
                details={
                    "reason": "user_not_found",
                    "email": email
                }
            )
            return False, None, "Invalid email or password"

        can_login, login_error = user.can_login()
        if not can_login:
            await handle_failed_login(db, user, ip_address, user_agent)
            return False, user, login_error

        if not user.is_verified:
            return False, user, "Email not verified"

        if not verify_password(password, user.password):
            await handle_failed_login(db, user, ip_address, user_agent)
            return False, user, "Invalid email or password"

        if needs_rehash(user.password):
            try:
                user.password = get_password_hash(password)
                logger.info(
                    "Password rehashed with updated parameters",
                    extra={
                        "event_type": "password_rehashed",
                        "user_id": str(user.id)
                    }
                )
            except Exception as e:
                logger.warning(
                    "Failed to rehash password",
                    extra={
                        "event_type": "password_rehash_failed",
                        "user_id": str(user.id),
                        "error": str(e)
                    }
                )

        await handle_successful_login(db, user, ip_address, user_agent)
        return True, user, None

    except Exception as e:
        logger.error(
            "Authentication error",
            extra={
                "event_type": "authentication_error",
                "email": email,
                "error": str(e)
            },
            exc_info=True
        )
        return False, None, "Authentication failed"


def create_verification_token(email: str, role: str, facility_id: str = None) -> str:
    """Create verification token with role and facility information"""
    expire = datetime.now(timezone.utc) + timedelta(hours=24)
    
    payload = {
        "sub": email,
        "role": role,
        "exp": expire,
        "type": "email_verification"
    }
    
    if facility_id:
        payload["facility_id"] = facility_id
    
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def verify_token_and_extract_data(token: str) -> dict:
    """Verify token and extract user data safely"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        
        if payload.get("type") != "email_verification":
            raise ValueError("Invalid token type")
            
        return {
            "email": payload.get("sub"),
            "role": payload.get("role"),
            "facility_id": payload.get("facility_id")
        }
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=400, detail="Token has expired")
    except jwt.JWTError:
        raise HTTPException(status_code=400, detail="Invalid token")


async def get_current_user(
    db: AsyncSession = Depends(get_db), 
    token: str = Depends(oauth2_scheme),
    request: Request = None
) -> User:
    """Get current user with enhanced session validation"""
    try:
        payload = TokenManager.decode_token(token)
        user_id = payload.get("sub")
        session_id = payload.get("sid")  # Session ID from token
        
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token does not contain user ID",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if payload.get("type") != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type",
                headers={"WWW-Authenticate": "Bearer"},
            )

        result = await db.execute(
            select(User)
            .options(
                selectinload(User.roles).selectinload(Role.permissions),
                selectinload(User.facility).selectinload(Facility.blood_bank),
                selectinload(User.work_facility).selectinload(Facility.blood_bank)
            )
            .where(User.id == UUID(user_id))
        )
        user = result.scalar_one_or_none()

        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if not user.is_active or not user.status:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Account is inactive",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if user.is_locked:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Account is temporarily locked",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Validate session if session ID is in token and request is available
        if session_id and request:
            session = await SessionManager.validate_session(db, UUID(session_id), request)
            if not session:
                logger.warning(
                    "Invalid session detected",
                    extra={
                        "event_type": "invalid_session",
                        "user_id": str(user.id),
                        "session_id": session_id
                    }
                )
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid session",
                    headers={"WWW-Authenticate": "Bearer"},
                )

        return user

    except (JWTError, ValueError) as e:
        logger.warning(
            "Invalid authentication credentials",
            extra={
                "event_type": "invalid_auth_credentials",
                "error": str(e)
            }
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

# Keep other existing functions unchanged...
async def get_current_user_ws(websocket: WebSocket, db: AsyncSession) -> User:
    """WebSocket authentication with enhanced security"""
    token = websocket.cookies.get("access_token")
    if token is None:
        await websocket.close(code=1008)
        raise HTTPException(status_code=401, detail="Missing token")

    try:
        payload = TokenManager.decode_token(token)
        user_id = payload.get("sub")
        
        if not user_id:
            await websocket.close(code=1008)
            raise HTTPException(status_code=401, detail="Invalid token")

        if payload.get("type") != "access":
            await websocket.close(code=1008)
            raise HTTPException(status_code=401, detail="Invalid token type")

        result = await db.execute(
            select(User)
            .options(
                selectinload(User.roles).selectinload(Role.permissions),
                selectinload(User.facility).selectinload(Facility.blood_bank),
                selectinload(User.work_facility).selectinload(Facility.blood_bank)
            )
            .where(User.id == UUID(user_id))
        )
        user = result.scalar_one_or_none()
        
        if not user:
            await websocket.close(code=1008)
            raise HTTPException(status_code=401, detail="User not found")

        if not user.is_active or not user.status or user.is_locked:
            await websocket.close(code=1008)
            raise HTTPException(status_code=401, detail="Account is inactive or locked")
            
        return user

    except Exception as e:
        logger.warning(
            "WebSocket authentication failed",
            extra={
                "event_type": "websocket_auth_failed",
                "error": str(e)
            }
        )
        await websocket.close(code=1008)
        raise HTTPException(status_code=401, detail="Invalid authentication credentials")


async def cleanup_expired_refresh_tokens(db: AsyncSession) -> int:
    """Clean up expired refresh tokens from database"""
    try:
        result = await db.execute(
            select(RefreshToken).where(RefreshToken.expires_at < datetime.now(timezone.utc))
        )
        expired_tokens = result.scalars().all()
        
        count = len(expired_tokens)
        
        for token in expired_tokens:
            await db.delete(token)
        
        await db.commit()
        
        if count > 0:
            logger.info(
                "Expired refresh tokens cleaned up",
                extra={
                    "event_type": "refresh_tokens_cleaned",
                    "tokens_removed": count
                }
            )
        
        return count
        
    except Exception as e:
        logger.error(
            "Failed to cleanup expired refresh tokens",
            extra={
                "event_type": "refresh_token_cleanup_failed",
                "error": str(e)
            },
            exc_info=True
        )
        await db.rollback()
        return 0