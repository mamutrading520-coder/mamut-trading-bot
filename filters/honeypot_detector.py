from typing import Any, Dict, List
from loguru import logger


class HoneypotDetector:
    """
    Early-stage honeypot and trap-risk heuristic detector.

    This detector does not simulate swaps. It scores risk based on
    metadata, authority state, liquidity conditions and suspicious
    token characteristics available during early discovery.
    """

    def __init__(self) -> None:
        logger.debug("HoneypotDetector initialized")

    async def analyze(self, token_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze token data and return a heuristic honeypot risk profile.
        """
        try:
            risk_score = 0
            risk_flags: List[str] = []

            mint_authority = self._as_bool(token_data.get("mint_authority"))
            freeze_authority = self._as_bool(token_data.get("freeze_authority"))
            liquidity_locked = self._as_bool(token_data.get("liquidity_locked"))
            has_website = self._as_bool(token_data.get("has_website"))
            has_twitter = self._as_bool(token_data.get("has_twitter"))
            has_telegram = self._as_bool(token_data.get("has_telegram"))

            holder_count = self._as_int(token_data.get("holder_count"))
            top_holder_percentage = self._as_float(token_data.get("top_holder_percentage"))
            creator_hold_percentage = self._as_float(token_data.get("creator_hold_percentage"))
            buy_tax = self._as_float(token_data.get("buy_tax"))
            sell_tax = self._as_float(token_data.get("sell_tax"))
            liquidity_usd = self._as_float(token_data.get("liquidity_usd"))
            volume_5m = self._as_float(token_data.get("volume_5m"))
            metadata_score = self._as_float(token_data.get("metadata_score"))

            if mint_authority:
                risk_score += 20
                risk_flags.append("mint_authority_enabled")

            if freeze_authority:
                risk_score += 20
                risk_flags.append("freeze_authority_enabled")

            if not liquidity_locked:
                risk_score += 15
                risk_flags.append("liquidity_not_locked")

            if holder_count <= 10:
                risk_score += 12
                risk_flags.append("very_low_holder_count")
            elif holder_count <= 25:
                risk_score += 6
                risk_flags.append("low_holder_count")

            if top_holder_percentage >= 35:
                risk_score += 18
                risk_flags.append("top_holder_concentrated")
            elif top_holder_percentage >= 20:
                risk_score += 10
                risk_flags.append("top_holder_elevated")

            if creator_hold_percentage >= 20:
                risk_score += 18
                risk_flags.append("creator_allocation_high")
            elif creator_hold_percentage >= 10:
                risk_score += 10
                risk_flags.append("creator_allocation_elevated")

            if buy_tax >= 15:
                risk_score += 10
                risk_flags.append("buy_tax_high")

            if sell_tax >= 15:
                risk_score += 25
                risk_flags.append("sell_tax_high")
            elif sell_tax >= 8:
                risk_score += 12
                risk_flags.append("sell_tax_elevated")

            if liquidity_usd < 2000:
                risk_score += 10
                risk_flags.append("liquidity_thin")

            if volume_5m <= 0:
                risk_score += 8
                risk_flags.append("no_recent_volume")

            social_count = sum([has_website, has_twitter, has_telegram])
            if social_count == 0:
                risk_score += 8
                risk_flags.append("no_social_presence")

            if metadata_score > 0 and metadata_score < 35:
                risk_score += 8
                risk_flags.append("weak_metadata_quality")

            honeypot_risk = min(100.0, float(risk_score))

            is_high_risk = honeypot_risk >= 60
            is_medium_risk = 35 <= honeypot_risk < 60

            result = {
                "honeypot_risk_score": honeypot_risk,
                "honeypot_risk_level": self._classify_risk(honeypot_risk),
                "honeypot_flags": risk_flags,
                "is_honeypot_high_risk": is_high_risk,
                "is_honeypot_medium_risk": is_medium_risk,
                "honeypot_summary": self._build_summary(honeypot_risk, risk_flags),
            }

            logger.debug(
                f"Honeypot analysis complete | risk={honeypot_risk} | flags={risk_flags}"
            )
            return result

        except Exception as e:
            logger.error(f"Honeypot analysis failed: {e}")
            return {
                "honeypot_risk_score": 100.0,
                "honeypot_risk_level": "UNKNOWN",
                "honeypot_flags": ["honeypot_analysis_error"],
                "is_honeypot_high_risk": True,
                "is_honeypot_medium_risk": False,
                "honeypot_summary": "honeypot analysis failed",
            }

    def _classify_risk(self, risk_score: float) -> str:
        if risk_score >= 60:
            return "HIGH"
        if risk_score >= 35:
            return "MEDIUM"
        return "LOW"

    def _build_summary(self, risk_score: float, flags: List[str]) -> str:
        if not flags:
            return f"honeypot_risk={int(risk_score)} | no major flags"
        return f"honeypot_risk={int(risk_score)} | flags={','.join(flags[:4])}"

    def _as_bool(self, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "y", "enabled"}
        return bool(value)

    def _as_int(self, value: Any) -> int:
        try:
            return int(value or 0)
        except Exception:
            return 0

    def _as_float(self, value: Any) -> float:
        try:
            return float(value or 0.0)
        except Exception:
            return 0.0
