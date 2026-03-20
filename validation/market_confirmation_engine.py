"""Confirm market conditions after Raydium pool validation"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Dict, Any

from monitoring.logger import setup_logger
from config.settings import Settings
from config.thresholds import SIGNAL_THRESHOLDS

logger = setup_logger("MarketConfirmationEngine")


class MarketConfirmationEngine:
    """Confirms market conditions for a token after Raydium pool validation."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.confirmations_made = 0
        self.confirmations_failed = 0

    def _analyze_pool_quality(self, pool_validation: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze validated pool quality and build a normalized quality summary.
        """
        checks = pool_validation.get("checks", {}) or {}
        liquidity_sol = float(pool_validation.get("liquidity_sol", 0.0) or 0.0)
        validation_score = float(pool_validation.get("validation_score", 0.0) or 0.0)

        analysis = {
            "pool_valid": bool(pool_validation.get("is_valid", False)),
            "liquidity_sol": liquidity_sol,
            "validation_score": validation_score,
            "quality_score": 0.0,
            "market_stage": "UNCONFIRMED",
            "quality_factors": [],
            "warnings": list(pool_validation.get("warnings", []) or []),
        }

        if not analysis["pool_valid"]:
            analysis["quality_score"] = max(10.0, validation_score * 0.4)
            analysis["quality_factors"].append("Pool validation failed")
            return analysis

        score = 55.0

        # Reuse validator score as base confidence anchor
        score += min(validation_score * 0.25, 20.0)

        # Liquidity quality
        if liquidity_sol >= 100:
            score += 15.0
            analysis["quality_factors"].append(f"Strong liquidity: {liquidity_sol:.2f} SOL")
        elif liquidity_sol >= 50:
            score += 10.0
            analysis["quality_factors"].append(f"Good liquidity: {liquidity_sol:.2f} SOL")
        elif liquidity_sol >= 10:
            score += 5.0
            analysis["quality_factors"].append(f"Tradable liquidity: {liquidity_sol:.2f} SOL")
        else:
            analysis["warnings"].append(f"Low liquidity: {liquidity_sol:.2f} SOL")

        # Program check
        if checks.get("program_id", {}).get("valid"):
            score += 5.0
            analysis["quality_factors"].append("Official/accepted Raydium program")

        # Pool age check
        pool_age = checks.get("pool_age", {}) or {}
        if pool_age.get("valid"):
            score += 5.0
            analysis["quality_factors"].append("Pool age validated")

            age_minutes = float(pool_age.get("pool_age_minutes", 0.0) or 0.0)
            if age_minutes <= 15:
                analysis["market_stage"] = "EARLY_ACTIVE"
            elif age_minutes <= 60:
                analysis["market_stage"] = "ACTIVE"
            else:
                analysis["market_stage"] = "MATURE"
        else:
            analysis["warnings"].append("Pool age not validated")

        # Quote asset check
        if checks.get("quote_asset", {}).get("valid"):
            score += 5.0
            analysis["quality_factors"].append("Allowed quote asset")

        analysis["quality_score"] = min(100.0, round(score, 2))
        return analysis

    def _calculate_confidence_boost(
        self,
        initial_confidence: float,
        pool_quality: Dict[str, Any],
    ) -> float:
        """
        Calculate confidence boost after pool validation and market confirmation.
        """
        base_confidence = float(initial_confidence or 0.0)

        if not pool_quality.get("pool_valid", False):
            return max(0.05, round(base_confidence * 0.5, 4))

        quality_score = float(pool_quality.get("quality_score", 0.0) or 0.0)

        # Max boost ~0.20, proportional to quality
        boost = (quality_score / 100.0) * 0.20
        new_confidence = min(0.99, base_confidence + boost)
        return round(new_confidence, 4)

    async def confirm_market(
        self,
        token_data: Dict[str, Any],
        initial_signal: Dict[str, Any],
        pool_validation: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Confirm market conditions using real validator output.

        Returns a structured result for the orchestrator, which remains the only
        component responsible for emitting the MarketConfirmed event.
        """
        try:
            mint = token_data.get("mint")
            symbol = token_data.get("symbol", "UNKNOWN")

            logger.debug(f"Confirming market conditions for {mint[:8]}...")

            pool_quality = self._analyze_pool_quality(pool_validation)

            initial_confidence = float(
                initial_signal.get(
                    "confidence",
                    token_data.get("confidence", 0.5),
                ) or 0.5
            )
            new_confidence = self._calculate_confidence_boost(
                initial_confidence,
                pool_quality,
            )

            min_confirmation_score = float(
                SIGNAL_THRESHOLDS.get("min_confirmation_score", 65)
            )

            is_confirmed = (
                pool_quality.get("pool_valid", False)
                and float(pool_quality.get("quality_score", 0.0)) >= min_confirmation_score
            )

            reasons = []
            if is_confirmed:
                reasons.append("Raydium pool validated")
                reasons.extend(pool_quality.get("quality_factors", []))
            else:
                reasons.append("Market confirmation threshold not met")
                reasons.extend(pool_quality.get("warnings", []))

            confirmation = {
                "mint": mint,
                "symbol": symbol,
                "confirmation_id": f"CONFIRM-{uuid.uuid4().hex[:12]}",
                "is_confirmed": is_confirmed,
                "reason": reasons[0] if reasons else "Market confirmation evaluated",
                "reasons": reasons,
                "initial_confidence": initial_confidence,
                "new_confidence": new_confidence,
                "confidence_boost": round(new_confidence - initial_confidence, 4),
                "score": float(
                    token_data.get(
                        "final_score",
                        initial_signal.get("score", 0.0),
                    ) or 0.0
                ),
                "risk_level": token_data.get(
                    "decision",
                    initial_signal.get("decision", "CONFIRMED"),
                ),
                "market_stage": pool_quality.get("market_stage", "UNCONFIRMED"),
                "pool_quality": pool_quality,
                "pool_validation": pool_validation,
                "pool": {
                    "id": pool_validation.get("pool_id"),
                    "pool_id": pool_validation.get("pool_id"),
                    "pool_address": pool_validation.get("pool_address"),
                    "liquidity_sol": pool_validation.get("liquidity_sol", 0.0),
                },
                "checks": pool_validation.get("checks", {}),
                "timestamp": datetime.utcnow().isoformat(),
            }

            self.confirmations_made += 1

            if is_confirmed:
                logger.info(
                    f"Market confirmed for {mint[:8]}... | confidence={new_confidence:.1%}"
                )
            else:
                logger.warning(f"Market confirmation failed for {mint[:8]}...")

            return confirmation

        except Exception as e:
            logger.error(f"Error confirming market: {e}")
            self.confirmations_failed += 1
            return {
                "mint": token_data.get("mint"),
                "symbol": token_data.get("symbol", "UNKNOWN"),
                "error": str(e),
                "is_confirmed": False,
            }

    def get_stats(self) -> dict:
        """Get confirmation engine statistics."""
        total = self.confirmations_made + self.confirmations_failed
        return {
            "confirmations_made": self.confirmations_made,
            "confirmations_failed": self.confirmations_failed,
            "confirmation_rate": self.confirmations_made / total if total > 0 else 0,
        }
