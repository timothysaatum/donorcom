"""
Device Trust Calculator

Utility classes and functions for calculating device trust scores
and managing device trust data.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


@dataclass
class DeviceTrustData:
    """Data structure for device trust metrics"""

    device_id: str
    trust_score: int
    registration_time: datetime
    last_seen: datetime
    total_sessions: int
    successful_logins: int
    failed_attempts: int
    suspicious_activities: int
    verification_challenges_passed: int
    verification_challenges_failed: int
    is_trusted: bool
    trust_level: str
    location_consistency_score: int


class DeviceIdentifier:
    """Device trust score calculator and identifier"""

    # Trust level thresholds
    TRUST_LEVELS = {
        "untrusted": (0, 19),
        "low": (20, 39),
        "medium": (40, 69),
        "high": (70, 89),
        "verified": (90, 100),
    }

    # Score weights for different factors
    WEIGHTS = {
        "age": 0.15,  # Device age factor
        "usage": 0.25,  # Usage frequency
        "success_rate": 0.30,  # Login success rate
        "verification": 0.20,  # Verification challenges
        "location": 0.10,  # Location consistency
    }

    @classmethod
    def calculate_trust_score(cls, trust_data: DeviceTrustData) -> int:
        """
        Calculate trust score based on multiple factors

        Returns:
            int: Trust score from 0 to 100
        """
        score = 0

        # 1. Device age factor (0-15 points)
        age_score = cls._calculate_age_score(trust_data.registration_time)
        score += age_score * cls.WEIGHTS["age"] * 100

        # 2. Usage frequency factor (0-25 points)
        usage_score = cls._calculate_usage_score(
            trust_data.total_sessions, trust_data.registration_time
        )
        score += usage_score * cls.WEIGHTS["usage"] * 100

        # 3. Success rate factor (0-30 points)
        success_score = cls._calculate_success_rate(
            trust_data.successful_logins,
            trust_data.failed_attempts,
            trust_data.suspicious_activities,
        )
        score += success_score * cls.WEIGHTS["success_rate"] * 100

        # 4. Verification factor (0-20 points)
        verification_score = cls._calculate_verification_score(
            trust_data.verification_challenges_passed,
            trust_data.verification_challenges_failed,
        )
        score += verification_score * cls.WEIGHTS["verification"] * 100

        # 5. Location consistency factor (0-10 points)
        location_score = trust_data.location_consistency_score / 100
        score += location_score * cls.WEIGHTS["location"] * 100

        # Ensure score is within bounds
        return max(0, min(100, int(score)))

    @classmethod
    def determine_trust_level(cls, trust_score: int) -> str:
        """
        Determine trust level based on score

        Args:
            trust_score: Trust score from 0 to 100

        Returns:
            str: Trust level (untrusted, low, medium, high, verified)
        """
        for level, (min_score, max_score) in cls.TRUST_LEVELS.items():
            if min_score <= trust_score <= max_score:
                return level
        return "untrusted"

    @staticmethod
    def _calculate_age_score(registration_time: datetime) -> float:
        """
        Calculate score based on device age
        Older devices (up to 90 days) get higher scores

        Returns:
            float: Score from 0.0 to 1.0
        """
        if not registration_time:
            return 0.0

        days_old = (datetime.now(timezone.utc) - registration_time).days

        # Linear increase up to 90 days, then cap at 1.0
        if days_old <= 0:
            return 0.0
        elif days_old >= 90:
            return 1.0
        else:
            return days_old / 90

    @staticmethod
    def _calculate_usage_score(
        total_sessions: int, registration_time: datetime
    ) -> float:
        """
        Calculate score based on usage frequency
        More sessions relative to device age = higher score

        Returns:
            float: Score from 0.0 to 1.0
        """
        if not registration_time or total_sessions <= 0:
            return 0.0

        days_old = max(1, (datetime.now(timezone.utc) - registration_time).days)
        sessions_per_day = total_sessions / days_old

        # Expected: ~1 session per day for normal usage
        # Scale: 0-2 sessions/day maps to 0.0-1.0
        score = min(1.0, sessions_per_day / 2.0)
        return score

    @staticmethod
    def _calculate_success_rate(
        successful_logins: int, failed_attempts: int, suspicious_activities: int
    ) -> float:
        """
        Calculate score based on login success rate
        High success rate with low suspicious activity = higher score

        Returns:
            float: Score from 0.0 to 1.0
        """
        total_attempts = successful_logins + failed_attempts

        if total_attempts == 0:
            return 0.5  # Neutral for new devices

        # Base success rate
        success_rate = successful_logins / total_attempts

        # Penalty for suspicious activities
        if total_attempts > 0:
            suspicious_ratio = suspicious_activities / total_attempts
            penalty = min(0.5, suspicious_ratio * 2)  # Up to 50% penalty
            success_rate = max(0.0, success_rate - penalty)

        return success_rate

    @staticmethod
    def _calculate_verification_score(
        challenges_passed: int, challenges_failed: int
    ) -> float:
        """
        Calculate score based on verification challenge results

        Returns:
            float: Score from 0.0 to 1.0
        """
        total_challenges = challenges_passed + challenges_failed

        if total_challenges == 0:
            return 0.3  # Default score for unverified devices

        # Success rate with bonus for completing challenges
        success_rate = challenges_passed / total_challenges

        # Bonus for passing multiple challenges
        if challenges_passed >= 3:
            success_rate = min(1.0, success_rate * 1.2)

        return success_rate

    @classmethod
    def calculate_risk_score(cls, trust_data: DeviceTrustData) -> int:
        """
        Calculate risk score (inverse of trust score)

        Args:
            trust_data: Device trust data

        Returns:
            int: Risk score from 0 to 100 (higher = more risky)
        """
        trust_score = cls.calculate_trust_score(trust_data)
        risk_score = 100 - trust_score

        # Additional risk factors
        if trust_data.suspicious_activities > 3:
            risk_score += 10

        if trust_data.failed_attempts > trust_data.successful_logins:
            risk_score += 15

        # Ensure risk score is within bounds
        return max(0, min(100, risk_score))

    @classmethod
    def should_require_verification(cls, trust_data: DeviceTrustData) -> bool:
        """
        Determine if additional verification should be required

        Args:
            trust_data: Device trust data

        Returns:
            bool: True if verification is needed
        """
        trust_score = cls.calculate_trust_score(trust_data)

        # Require verification for low trust devices
        if trust_score < 40:
            return True

        # Require verification if suspicious activity detected
        if trust_data.suspicious_activities > 2:
            return True

        # Require verification if too many failed attempts
        if trust_data.failed_attempts > trust_data.successful_logins:
            return True

        return False


class DeviceFingerprintGenerator:
    """Generate and validate device fingerprints"""

    @staticmethod
    def generate_fingerprint(
        user_agent: str, accept_language: str, accept_encoding: str, client_ip: str
    ) -> str:
        """
        Generate a device fingerprint from browser characteristics

        Args:
            user_agent: Browser user agent string
            accept_language: Accept-Language header
            accept_encoding: Accept-Encoding header
            client_ip: Client IP address (optional, for enhanced fingerprint)

        Returns:
            str: 64-character hex fingerprint
        """
        import hashlib

        # Normalize inputs
        components = [
            user_agent.strip().lower(),
            accept_language.split(",")[0].strip().lower() if accept_language else "",
            accept_encoding.strip().lower(),
            # Only include IP network portion (not full IP for privacy)
            ".".join(client_ip.split(".")[:3]) if client_ip else "",
        ]

        # Create fingerprint
        fingerprint_data = "|".join(filter(None, components))
        fingerprint = hashlib.sha256(fingerprint_data.encode("utf-8")).hexdigest()

        return fingerprint[:64]

    @staticmethod
    def is_valid_fingerprint(fingerprint: str) -> bool:
        """
        Validate fingerprint format

        Args:
            fingerprint: Fingerprint to validate

        Returns:
            bool: True if valid format
        """
        if not fingerprint or not isinstance(fingerprint, str):
            return False

        # Check length
        if len(fingerprint) != 64:
            return False

        # Check if hexadecimal
        try:
            int(fingerprint, 16)
            return True
        except ValueError:
            return False


__all__ = [
    "DeviceTrustData",
    "DeviceIdentifier",
    "DeviceFingerprintGenerator",
]
