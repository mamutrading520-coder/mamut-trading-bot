"""Score engine for passed tokens"""

from __future__ import annotations

from typing import Dict, Any, List
from datetime import datetime

from monitoring.logger import setup_logger
from core.event_bus import Event, get_event_bus

logger = setup_logger("ScoreEngine")


class ScoreEngine:
    """Computes final token score after trash filtering."""

    def __init__(self):
        self.event_bus = get_event_bus()
        self.scored_count = 0
        self.failed_count = 0

    def _safe_float(self, value: Any, default: float = 0.0) -> float:
        try:
            if value is None:
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    def _semantic_flag_penalty(self, semantic_flags: List[str]) -> float:
        severe_flags = {
            "cta_phrase",
            "promo_slogan",
            "profane_phrase",
            "sentence_like_name",
            "overlong_phrase",
            "generic_placeholder_symbol",
            "narrative_clause",
            "weak_lead_phrase",
            "linking_verb_structure",
            "inflated_all_caps_phrase",
        }
        severe_hits = [flag for flag in semantic_flags if flag in severe_flags]
        if not severe_hits:
            return 0.0
        return min(16.0, 8.0 + max(0, len(severe_hits) - 1) * 2.0)

    def _compute_quality_score(self, token_data: Dict[str, Any]) -> Dict[str, Any]:
        market_cap_sol = self._safe_float(token_data.get("market_cap_sol", 0))
        metadata_score = max(0.0, min(100.0, self._safe_float(token_data.get("metadata_score", 0))))
        social_count = int(token_data.get("social_count", 0) or 0)

        aggregate_risk = self._safe_float(token_data.get("aggregate_risk_score", 35))
        authority_risk = self._safe_float(token_data.get("authority_risk", 40))
        creator_risk = self._safe_float(token_data.get("creator_risk", 45))
        concentration_risk = self._safe_float(token_data.get("concentration_risk", 35))
        metadata_risk = self._safe_float(token_data.get("metadata_risk", 40))
        honeypot_risk = self._safe_float(token_data.get("honeypot_risk", 30))
        semantic_risk = self._safe_float(token_data.get("semantic_risk", 15))
        semantic_flags = list(token_data.get("semantic_risk_flags", []) or [])

        metadata_retrieved = bool(token_data.get("metadata_retrieved", False))
        metadata_present = bool(token_data.get("metadata_json") or token_data.get("uri_metadata"))

        score = 62.0
        notes = []

        if not metadata_retrieved and not metadata_present:
            notes.append("Metadata pending")
        else:
            if metadata_score >= 80:
                score += 10
                notes.append("Strong metadata quality")
            elif metadata_score >= 60:
                score += 7
                notes.append("Good metadata quality")
            elif metadata_score >= 40:
                score += 3
                notes.append("Acceptable metadata quality")
            elif metadata_score > 0:
                score -= 4
                notes.append("Weak metadata quality")

        if social_count >= 3:
            score += 7
            notes.append("Strong social presence")
        elif social_count == 2:
            score += 4
        elif social_count == 1:
            score += 2
        else:
            score -= 1
            notes.append("No socials detected")

        if 15 <= market_cap_sol <= 250:
            score += 6
            notes.append("Healthy early market cap range")
        elif 5 <= market_cap_sol < 15:
            score += 3
        elif market_cap_sol > 500:
            score -= 3
            notes.append("Late/extended market cap profile")

        score -= aggregate_risk * 0.38

        if semantic_risk >= 80:
            score -= 18
            notes.append("Critical semantic contamination")
        elif semantic_risk >= 65:
            score -= 12
            notes.append("High semantic contamination")
        elif semantic_risk >= 50:
            score -= 7
            notes.append("Narrative or weak token-brand semantics")
        elif semantic_risk >= 35:
            score -= 4
            notes.append("Borderline semantic contamination")

        severe_narrative_flags = {"narrative_clause", "weak_lead_phrase", "sentence_like_name", "linking_verb_structure", "inflated_all_caps_phrase"}
        if any(flag in severe_narrative_flags for flag in semantic_flags):
            score -= 12
            notes.append("Narrative/statement-style or inflated naming detected")

        if "multiword_name" in semantic_flags and "all_caps_claim" in semantic_flags:
            score -= 10
            notes.append("Inflated multiword all-caps naming pattern")

        score -= self._semantic_flag_penalty(semantic_flags)
        if semantic_flags:
            notes.append(f"Semantic flags: {', '.join(semantic_flags[:4])}")

        if authority_risk >= 80:
            score -= 6
            notes.append("High authority risk")
        elif authority_risk >= 60:
            score -= 3
        if creator_risk >= 80:
            score -= 5
            notes.append("High creator risk")
        elif creator_risk >= 60:
            score -= 2
        if concentration_risk >= 85:
            score -= 5
            notes.append("High concentration risk")
        elif concentration_risk >= 65:
            score -= 2
        if metadata_risk >= 85 and metadata_retrieved:
            score -= 5
            notes.append("High metadata risk")
        elif metadata_risk >= 65 and metadata_retrieved:
            score -= 2
        if honeypot_risk >= 80:
            score -= 8
            notes.append("High honeypot risk")
        elif honeypot_risk >= 60:
            score -= 4

        final_score = round(max(0.0, min(100.0, score)), 2)

        data_completeness = 0.0
        if metadata_retrieved or metadata_present:
            data_completeness += 0.2
        if social_count > 0:
            data_completeness += 0.1
        if market_cap_sol > 0:
            data_completeness += 0.1

        cleanliness = max(0.0, 100.0 - aggregate_risk)
        semantic_cleanliness = max(0.0, 100.0 - semantic_risk)
        confidence = (
            (final_score / 100.0) * 0.45
            + (cleanliness / 100.0) * 0.25
            + (semantic_cleanliness / 100.0) * 0.15
            + data_completeness * 0.15
        )

        if semantic_risk >= 80:
            confidence -= 0.12
        elif semantic_risk >= 65:
            confidence -= 0.08
        elif semantic_risk >= 50:
            confidence -= 0.05
        elif semantic_risk >= 35:
            confidence -= 0.03

        if any(flag in severe_narrative_flags for flag in semantic_flags):
            confidence -= 0.10
        if "multiword_name" in semantic_flags and "all_caps_claim" in semantic_flags:
            confidence -= 0.08

        confidence = round(max(0.0, min(0.99, confidence)), 4)

        return {
            "final_score": final_score,
            "confidence": confidence,
            "breakdown": {
                "market_cap_sol": market_cap_sol,
                "metadata_score": metadata_score,
                "social_count": social_count,
                "aggregate_risk": aggregate_risk,
                "authority_risk": authority_risk,
                "creator_risk": creator_risk,
                "concentration_risk": concentration_risk,
                "metadata_risk": metadata_risk,
                "honeypot_risk": honeypot_risk,
                "semantic_risk": semantic_risk,
                "semantic_flags": semantic_flags,
                "metadata_retrieved": metadata_retrieved,
                "metadata_present": metadata_present,
                "notes": notes,
            },
        }

    async def score_and_emit(self, event: Event) -> bool:
        try:
            token_data = event.data or {}
            mint = token_data.get("mint")
            if not mint:
                logger.warning("score_and_emit called without mint")
                return False

            result = self._compute_quality_score(token_data)
            score_event = Event(
                event_type="ScoreCalculated",
                data={**token_data, "final_score": result["final_score"], "confidence": result["confidence"], "score_breakdown": result["breakdown"]},
                source="ScoreEngine",
                timestamp=datetime.utcnow(),
            )
            await self.event_bus.emit(score_event)
            self.scored_count += 1
            logger.info(f"ScoreCalculated: {mint[:8]}... | score={result['final_score']:.2f} | conf={result['confidence']:.2f}")
            return True
        except Exception as e:
            logger.error(f"Error scoring token: {e}")
            self.failed_count += 1
            return False

    def get_stats(self) -> Dict[str, Any]:
        total = self.scored_count + self.failed_count
        return {"scored_count": self.scored_count, "failed_count": self.failed_count, "success_rate": self.scored_count / total if total > 0 else 0}
