"""Trash filter engine for token quality assessment"""

from __future__ import annotations

from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime

from monitoring.logger import setup_logger
from config.settings import Settings
from config.thresholds import (
    TRASH_FILTER_THRESHOLDS,
    CREATOR_RISK_THRESHOLDS,
    CONCENTRATION_THRESHOLDS,
    AUTHORITY_RISK_THRESHOLDS,
)
from storage.sqlite_store import SQLiteStore
from core.event_bus import Event, get_event_bus
from filters.honeypot_detector import HoneypotDetector

logger = setup_logger("TrashFilterEngine")


class TrashFilterEngine:
    """Filters out low-quality and scam-like tokens using coordinated risk checks."""

    def __init__(self, store: SQLiteStore, settings: Settings):
        self.store = store
        self.settings = settings
        self.event_bus = get_event_bus()

        self.honeypot_detector = HoneypotDetector(settings)

        self.passed = 0
        self.rejected = 0

    def _is_null_like(self, value: Optional[str]) -> bool:
        """Normalize Solana null/renounced authority values."""
        if not value:
            return True

        normalized = value.strip().lower()
        return normalized in {
            "",
            "11111111111111111111111111111111",
            "system",
            "systemprogram",
            "renounced",
            "none",
            "null",
        }

    def _calculate_authority_risk(self, token_data: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate authority/permission risk score."""
        try:
            mint_authority = token_data.get("mint_authority")
            freeze_authority = token_data.get("freeze_authority")
            owner_renounced = bool(token_data.get("owner_renounced", False))

            has_mint_authority = not self._is_null_like(mint_authority)
            has_freeze_authority = not self._is_null_like(freeze_authority)

            risk_score = 0.0
            reasons: List[str] = []
            warnings: List[str] = []

            if has_freeze_authority:
                risk_score += 45.0
                reasons.append("Freeze authority activa")

            if has_mint_authority:
                risk_score += 35.0
                reasons.append("Mint authority activa")

            if not owner_renounced:
                risk_score += 15.0
                warnings.append("Owner no renounced")

            risk_score = max(0.0, min(100.0, risk_score))

            return {
                "score": risk_score,
                "has_mint_authority": has_mint_authority,
                "has_freeze_authority": has_freeze_authority,
                "owner_renounced": owner_renounced,
                "reasons": reasons,
                "warnings": warnings,
            }

        except Exception as e:
            logger.debug(f"Error calculating authority risk: {e}")
            return {
                "score": 50.0,
                "has_mint_authority": None,
                "has_freeze_authority": None,
                "owner_renounced": False,
                "reasons": [f"Authority risk error: {e}"],
                "warnings": [],
            }

    def _calculate_creator_risk(self, token_data: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate creator reputation risk score."""
        try:
            creator = token_data.get("creator", "unknown")
            creator_profile = self.store.get_creator_profile(creator)

            risk_score = 55.0
            reasons: List[str] = []
            warnings: List[str] = []

            total_tokens = 0
            successful_tokens = 0
            wallet_age_days = None
            is_blacklisted = False
            is_trusted = False

            if creator_profile:
                total_tokens = int(getattr(creator_profile, "total_tokens", 0) or 0)
                successful_tokens = int(getattr(creator_profile, "successful_tokens", 0) or 0)
                wallet_age_days = getattr(creator_profile, "wallet_age_days", None)
                is_blacklisted = bool(getattr(creator_profile, "is_blacklisted", False))
                is_trusted = bool(getattr(creator_profile, "is_trusted", False))

                if is_blacklisted:
                    risk_score = 95.0
                    reasons.append("Creator blacklisted")
                elif is_trusted:
                    risk_score = 15.0
                    warnings.append("Creator trusted")
                else:
                    if total_tokens > 0:
                        success_rate = successful_tokens / total_tokens
                        risk_score = 55.0 - (success_rate * 35.0)

                        if total_tokens >= 5 and success_rate < 0.10:
                            reasons.append("Creator con historial muy débil")
                            risk_score += 20.0
                        elif total_tokens >= 3 and success_rate < 0.25:
                            warnings.append("Creator con baja tasa de éxito")
                            risk_score += 10.0

                    if wallet_age_days is not None:
                        if wallet_age_days < 7:
                            warnings.append("Creator wallet muy nueva")
                            risk_score += 15.0
                        elif wallet_age_days < 30:
                            warnings.append("Creator wallet reciente")
                            risk_score += 8.0
            else:
                warnings.append("Creator sin historial conocido")
                risk_score = 65.0

            risk_score = max(0.0, min(100.0, risk_score))

            return {
                "score": risk_score,
                "creator": creator,
                "is_new": creator_profile is None,
                "is_blacklisted": is_blacklisted,
                "is_trusted": is_trusted,
                "total_tokens": total_tokens,
                "successful_tokens": successful_tokens,
                "wallet_age_days": wallet_age_days,
                "reasons": reasons,
                "warnings": warnings,
            }

        except Exception as e:
            logger.debug(f"Error calculating creator risk: {e}")
            return {
                "score": 50.0,
                "creator": token_data.get("creator", "unknown"),
                "is_new": True,
                "is_blacklisted": False,
                "is_trusted": False,
                "total_tokens": 0,
                "successful_tokens": 0,
                "wallet_age_days": None,
                "reasons": [f"Creator risk error: {e}"],
                "warnings": [],
            }

    def _calculate_concentration_risk(self, token_data: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate token holder concentration risk."""
        try:
            creator_balance = float(token_data.get("creator_balance", 0) or 0)
            total_supply = float(token_data.get("total_supply", 0) or 0)
            holder_count = int(token_data.get("holder_count", 0) or 0)

            risk_score = 50.0
            creator_percentage = 0.0
            reasons: List[str] = []
            warnings: List[str] = []

            if total_supply > 0:
                creator_percentage = (creator_balance / total_supply) * 100

                if creator_percentage > 90:
                    risk_score = 95.0
                    reasons.append("Creator controla >90% del supply")
                elif creator_percentage > 70:
                    risk_score = 80.0
                    reasons.append("Creator controla >70% del supply")
                elif creator_percentage > 50:
                    risk_score = 65.0
                    warnings.append("Creator controla >50% del supply")
                elif creator_percentage < 20:
                    risk_score = 25.0

            if holder_count > 100:
                risk_score -= 15.0
            elif holder_count > 50:
                risk_score -= 10.0
            elif holder_count > 20:
                risk_score -= 5.0
            elif holder_count <= 5 and total_supply > 0:
                warnings.append("Muy pocos holders iniciales")
                risk_score += 10.0

            risk_score = max(0.0, min(100.0, risk_score))

            return {
                "score": risk_score,
                "creator_percentage": creator_percentage,
                "holder_count": holder_count,
                "reasons": reasons,
                "warnings": warnings,
            }

        except Exception as e:
            logger.debug(f"Error calculating concentration risk: {e}")
            return {
                "score": 50.0,
                "creator_percentage": 0.0,
                "holder_count": 0,
                "reasons": [f"Concentration risk error: {e}"],
                "warnings": [],
            }

    def _calculate_metadata_risk(self, token_data: Dict[str, Any]) -> Dict[str, Any]:
    """Calculate metadata quality risk from TokenEnricher output."""
    try:
        metadata_score_raw = token_data.get("metadata_score")
        metadata_flags = list(token_data.get("metadata_risk_flags", []) or [])
        social_count = int(token_data.get("social_count", 0) or 0)
        metadata_json = token_data.get("metadata_json")
        metadata_retrieved = bool(token_data.get("metadata_retrieved", False))

        reasons: List[str] = []
        warnings: List[str] = []

        # Caso 1: metadata aún no disponible o claramente incompleta.
        # En etapa temprana esto NO debe equivaler a scam.
        if metadata_score_raw is None:
            risk_score = 35.0
            warnings.append("Metadata score no disponible aún")
        else:
            metadata_score = float(metadata_score_raw or 0.0)

            # Si score=0 pero ni siquiera se ha recuperado metadata real,
            # tratamos esto como información insuficiente, no como basura confirmada.
            if metadata_score <= 0 and not metadata_retrieved and not metadata_json:
                risk_score = 35.0
                warnings.append("Metadata aún no enriquecida")
            else:
                # Escala menos agresiva que 100 - score
                risk_score = max(5.0, min(85.0, 70.0 - (metadata_score * 0.6)))

                if metadata_score < 20:
                    warnings.append("Metadata muy débil")
                elif metadata_score < 40:
                    warnings.append("Metadata débil")
                elif metadata_score >= 70:
                    risk_score -= 10.0

        if social_count == 0:
            warnings.append("Sin sociales detectadas")
            risk_score += 5.0
        elif social_count >= 2:
            risk_score -= 8.0

        if metadata_flags:
            warnings.append(f"Metadata flags: {', '.join(metadata_flags)}")
            risk_score += min(len(metadata_flags) * 3.0, 12.0)

        risk_score = max(0.0, min(100.0, risk_score))

        return {
            "score": risk_score,
            "metadata_score": float(metadata_score_raw or 0.0) if metadata_score_raw is not None else None,
            "metadata_risk_flags": metadata_flags,
            "social_count": social_count,
            "reasons": reasons,
            "warnings": warnings,
            "metadata_retrieved": metadata_retrieved,
            "metadata_present": bool(metadata_json),
        }

    except Exception as e:
        logger.debug(f"Error calculating metadata risk: {e}")
        return {
            "score": 40.0,
            "metadata_score": None,
            "metadata_risk_flags": [],
            "social_count": 0,
            "reasons": [],
            "warnings": [f"Metadata risk fallback: {e}"],
            "metadata_retrieved": False,
            "metadata_present": False,
        }
    

    def _combine_risks(
        self,
        authority_risk: Dict[str, Any],
        creator_risk: Dict[str, Any],
        concentration_risk: Dict[str, Any],
        metadata_risk: Dict[str, Any],
        honeypot_risk: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Combine component risks into one aggregate risk model."""
        weighted_score = (
            authority_risk["score"] * 0.28
            + creator_risk["score"] * 0.20
            + concentration_risk["score"] * 0.18
            + metadata_risk["score"] * 0.12
            + honeypot_risk["risk_score"] * 0.22
        )

        weighted_score = round(max(0.0, min(100.0, weighted_score)), 2)

        reasons = (
            authority_risk.get("reasons", [])
            + creator_risk.get("reasons", [])
            + concentration_risk.get("reasons", [])
            + metadata_risk.get("reasons", [])
            + honeypot_risk.get("reasons", [])
        )

        warnings = (
            authority_risk.get("warnings", [])
            + creator_risk.get("warnings", [])
            + concentration_risk.get("warnings", [])
            + metadata_risk.get("warnings", [])
            + honeypot_risk.get("warnings", [])
        )

        if weighted_score >= 75:
            risk_level = "critical"
        elif weighted_score >= 55:
            risk_level = "high"
        elif weighted_score >= 35:
            risk_level = "medium"
        else:
            risk_level = "low"

        return {
            "risk_score": weighted_score,
            "risk_level": risk_level,
            "reasons": reasons,
            "warnings": warnings,
        }

    def _should_reject(
        self,
        authority_risk: Dict[str, Any],
        creator_risk: Dict[str, Any],
        concentration_risk: Dict[str, Any],
        metadata_risk: Dict[str, Any],
        honeypot_risk: Dict[str, Any],
        aggregate: Dict[str, Any],
    ) -> Tuple[bool, List[str]]:
        """Determine whether the token should be rejected by hard/aggregate rules."""
        rejection_reasons: List[str] = []

        if authority_risk["score"] > AUTHORITY_RISK_THRESHOLDS.get("max_authority_risk", 80):
            rejection_reasons.append("Exceeds authority risk threshold")

        if creator_risk["score"] > CREATOR_RISK_THRESHOLDS.get("max_creator_risk", 85):
            rejection_reasons.append("Exceeds creator risk threshold")

        if concentration_risk["score"] > CONCENTRATION_THRESHOLDS.get("max_concentration_risk", 80):
            rejection_reasons.append("Exceeds concentration risk threshold")

        if honeypot_risk.get("is_suspicious", False) and honeypot_risk.get("risk_score", 0) >= 70:
            rejection_reasons.append("High honeypot/suspicious-token risk")

        metadata_present = metadata_risk.get("metadata_present", False)
        metadata_retrieved = metadata_risk.get("metadata_retrieved", False)

        if (
            metadata_present
            and metadata_retrieved
            and metadata_risk["score"] > TRASH_FILTER_THRESHOLDS.get("max_metadata_risk", 90)
        ):
            rejection_reasons.append("Exceeds metadata risk threshold")

        if aggregate["risk_score"] > TRASH_FILTER_THRESHOLDS.get("max_total_risk", 75):
            rejection_reasons.append("Exceeds aggregate trash-filter risk threshold")

        return len(rejection_reasons) > 0, rejection_reasons

    async def filter_and_emit(self, event: Event) -> Optional[str]:
        """
        Filter token and emit TokenPassed or TokenRejected.
        """
        try:
            token_data = event.data or {}
            mint = token_data.get("mint")
            if not mint:
                logger.warning("filter_and_emit called without mint")
                return None

            authority_risk = self._calculate_authority_risk(token_data)
            creator_risk = self._calculate_creator_risk(token_data)
            concentration_risk = self._calculate_concentration_risk(token_data)
            metadata_risk = self._calculate_metadata_risk(token_data)
            honeypot_risk = await self.honeypot_detector.analyze(token_data)

            aggregate = self._combine_risks(
                authority_risk=authority_risk,
                creator_risk=creator_risk,
                concentration_risk=concentration_risk,
                metadata_risk=metadata_risk,
                honeypot_risk=honeypot_risk,
            )

            reject, rejection_reasons = self._should_reject(
                authority_risk=authority_risk,
                creator_risk=creator_risk,
                concentration_risk=concentration_risk,
                metadata_risk=metadata_risk,
                honeypot_risk=honeypot_risk,
                aggregate=aggregate,
            )

            component_results = {
                "authority_risk": authority_risk,
                "creator_risk": creator_risk,
                "concentration_risk": concentration_risk,
                "metadata_risk": metadata_risk,
                "honeypot_risk": honeypot_risk,
            }

            if reject:
                self.rejected += 1

                rejection_event = Event(
                    event_type="TokenRejected",
                    data={
                        **token_data,
                        "mint": mint,
                        "reason": " | ".join(rejection_reasons),
                        "rejection_reason": " | ".join(rejection_reasons),
                        "aggregate_risk_score": aggregate["risk_score"],
                        "aggregate_risk_level": aggregate["risk_level"],
                        "component_results": component_results,
                        "warnings": aggregate["warnings"],
                    },
                    source="TrashFilterEngine",
                    timestamp=datetime.utcnow(),
                )

                await self.event_bus.emit(rejection_event)
                logger.warning(
                    f"[REJECTED] {mint[:8]}... | risk={aggregate['risk_score']:.1f} | "
                    f"{rejection_reasons[0]}"
                )
                return "REJECTED"

            self.passed += 1

            passed_event = Event(
                event_type="TokenPassed",
                data={
                    **token_data,
                    "aggregate_risk_score": aggregate["risk_score"],
                    "aggregate_risk_level": aggregate["risk_level"],
                    "component_results": component_results,
                    "warnings": aggregate["warnings"],
                    "authority_risk": authority_risk["score"],
                    "creator_risk": creator_risk["score"],
                    "concentration_risk": concentration_risk["score"],
                    "metadata_risk": metadata_risk["score"],
                    "honeypot_risk": honeypot_risk["risk_score"],
                },
                source="TrashFilterEngine",
                timestamp=datetime.utcnow(),
            )

            await self.event_bus.emit(passed_event)
            logger.info(
                f"[PASSED FILTERS] {mint[:8]}... | total_risk={aggregate['risk_score']:.1f} "
                f"| auth={authority_risk['score']:.0f} creator={creator_risk['score']:.0f}"
            )
            return "PASSED"

        except Exception as e:
            logger.error(f"Error filtering token: {e}")
            return None

    def get_stats(self) -> Dict[str, Any]:
        """Get filter statistics."""
        total = self.passed + self.rejected
        return {
            "passed": self.passed,
            "rejected": self.rejected,
            "pass_rate": (self.passed / total * 100) if total > 0 else 0,
            "honeypot_detector": self.honeypot_detector.get_stats(),
        }
