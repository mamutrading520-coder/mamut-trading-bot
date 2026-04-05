"""Score engine for passed tokens"""

from __future__ import annotations

import re
from typing import Dict, Any, Tuple, List
from datetime import datetime

from monitoring.logger import setup_logger
from core.event_bus import Event, get_event_bus

logger = setup_logger("ScoreEngine")


class ScoreEngine:
    """Computes final token score after trash filtering."""

    _BARE_DOMAIN_RE = re.compile(
        r"\b(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+(?:com|io|fun|xyz|ai|app|net|org|gg|co)\b",
        re.IGNORECASE,
    )
    _PURE_MATH_STATEMENT_RE = re.compile(r"^\s*\d+(?:\s*[+\-*/xX]\s*\d+)+(?:\s*=\s*\d+)?\s*$")
    _OFFICIAL_PREFIX_RE = re.compile(r"^\s*official\b", re.IGNORECASE)
    _HELP_BAIT_RE = re.compile(
        r"\b(?:lets?\s+help|help\s+this|single\s+mother|his\s+bday|her\s+bday|w\s+frontrun|with\s+frontrun|front\s*run)\b",
        re.IGNORECASE,
    )
    _TEMPORAL_CONTEXT_RE = re.compile(
        r"^(?:life\s+when|back\s+when|remember\s+when)\b|\bwhen\b.+\bwas\b",
        re.IGNORECASE,
    )
    _PROMOTIONAL_PHRASE_RE = re.compile(
        r"\b(?:same\s+dev(?:eloper)?\s+as|same\s+team\s+as|btw\s+check|check\s+(?:this|it|ca)|official\s+ca|contract\s+below|he\s+shilled|she\s+shilled|they\s+shilled|went\s+\d+(?:k|m|x)?)\b",
        re.IGNORECASE,
    )
    _STATEMENT_SUBJECT_RE = re.compile(
        r"^(?:men|women|boys|girls|guys|people|they|we|you|i|he|she|it|bro|bros|devs?)\b",
        re.IGNORECASE,
    )
    _STATEMENT_LINKER_RE = re.compile(
        r"\b(?:cant|can't|cannot|can|dont|don't|do|does|did|is|are|was|were|be|need|needs|like|love|hate|deserve|deserves|should|shouldn't|must|will|wont|won't)\b",
        re.IGNORECASE,
    )
    _WORD_TOKEN_RE = re.compile(r"[A-Za-zÀ-ÿ0-9']+")

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

    def _normalize_text(self, value: Any) -> str:
        return str(value or "").replace("\n", " ").replace("\r", " ").strip()

    def _semantic_metadata_penalty(self, token_data: Dict[str, Any]) -> Tuple[float, List[str]]:
        name = self._normalize_text(token_data.get("name"))
        if not name:
            return 0.0, []

        lowered = name.lower()
        tokens = self._WORD_TOKEN_RE.findall(name)
        lowercase_ratio = sum(1 for ch in name if ch.islower()) / max(sum(1 for ch in name if ch.isalpha()), 1)

        severity = 0.0
        notes: List[str] = []

        if self._OFFICIAL_PREFIX_RE.match(name) and len(tokens) >= 2:
            severity = max(severity, 0.80)
            notes.append("OFFICIAL-prefixed name")

        if self._BARE_DOMAIN_RE.search(name):
            severity = max(severity, 0.85)
            notes.append("Bare domain in name")

        if self._HELP_BAIT_RE.search(name):
            severity = max(severity, 0.90)
            notes.append("Help-bait / CTA name")

        if self._PURE_MATH_STATEMENT_RE.fullmatch(name):
            severity = max(severity, 0.85)
            notes.append("Math-statement name")

        if self._TEMPORAL_CONTEXT_RE.search(name) and len(tokens) >= 3:
            severity = max(severity, 0.65)
            notes.append("Temporal/comparative phrase")

        if self._PROMOTIONAL_PHRASE_RE.search(name):
            severity = max(severity, 0.75)
            notes.append("Promotional/narrative phrase")

        if (
            self._STATEMENT_SUBJECT_RE.match(name)
            and self._STATEMENT_LINKER_RE.search(name)
            and len(tokens) >= 3
            and lowercase_ratio >= 0.80
        ):
            severity = max(severity, 0.70)
            notes.append("Statement-like human phrase")

        if severity >= 0.85:
            return 18.0, notes
        if severity >= 0.70:
            return 12.0, notes
        if severity >= 0.50:
            return 7.0, notes
        return 0.0, []

    def _compute_quality_score(self, token_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build final score from early-stage quality signals and residual risk.
        Returns:
        - final_score: 0..100
        - confidence: 0..1
        - breakdown
        """
        market_cap_sol = self._safe_float(token_data.get("market_cap_sol", 0))
        metadata_score = max(0.0, min(100.0, self._safe_float(token_data.get("metadata_score", 0))))
        social_count = int(token_data.get("social_count", 0) or 0)

        aggregate_risk = self._safe_float(token_data.get("aggregate_risk_score", 35))
        authority_risk = self._safe_float(token_data.get("authority_risk", 40))
        creator_risk = self._safe_float(token_data.get("creator_risk", 45))
        concentration_risk = self._safe_float(token_data.get("concentration_risk", 35))
        metadata_risk = self._safe_float(token_data.get("metadata_risk", 40))
        honeypot_risk = self._safe_float(token_data.get("honeypot_risk", 30))

        metadata_retrieved = bool(token_data.get("metadata_retrieved", False))
        metadata_present = bool(token_data.get("metadata_json") or token_data.get("uri_metadata"))

        score = 62.0
        notes = []

        # Metadata quality: no castigar fuerte si aún no llegó metadata real
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

        # Social presence: señal positiva, pero ausencia no debe matar early tokens
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

        # Early market-cap sanity
        if 15 <= market_cap_sol <= 250:
            score += 6
            notes.append("Healthy early market cap range")
        elif 5 <= market_cap_sol < 15:
            score += 3
        elif market_cap_sol > 500:
            score -= 3
            notes.append("Late/extended market cap profile")

        # Main residual-risk penalty: usar aggregate como castigo principal
        score -= aggregate_risk * 0.38

        # Secondary fine-tuning only for extreme risks
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

        semantic_penalty, semantic_notes = self._semantic_metadata_penalty(token_data)
        if semantic_penalty > 0:
            score -= semantic_penalty
            notes.append(f"Semantic metadata penalty -{semantic_penalty:.0f}")
            notes.extend(semantic_notes)

        final_score = round(max(0.0, min(100.0, score)), 2)

        # Confidence: mezcla de score, limpieza y completitud de datos
        data_completeness = 0.0
        if metadata_retrieved or metadata_present:
            data_completeness += 0.2
        if social_count > 0:
            data_completeness += 0.1
        if market_cap_sol > 0:
            data_completeness += 0.1

        cleanliness = max(0.0, 100.0 - aggregate_risk)
        confidence = (
            (final_score / 100.0) * 0.5
            + (cleanliness / 100.0) * 0.3
            + data_completeness * 0.2
        )
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
                "metadata_retrieved": metadata_retrieved,
                "metadata_present": metadata_present,
                "semantic_penalty": semantic_penalty,
                "notes": notes,
            },
        }

    async def score_and_emit(self, event: Event) -> bool:
        """Score token and emit ScoreCalculated."""
        try:
            token_data = event.data or {}
            mint = token_data.get("mint")
            if not mint:
                logger.warning("score_and_emit called without mint")
                return False

            result = self._compute_quality_score(token_data)

            score_event = Event(
                event_type="ScoreCalculated",
                data={
                    **token_data,
                    "final_score": result["final_score"],
                    "confidence": result["confidence"],
                    "score_breakdown": result["breakdown"],
                },
                source="ScoreEngine",
                timestamp=datetime.utcnow(),
            )

            await self.event_bus.emit(score_event)

            self.scored_count += 1
            logger.info(
                f"ScoreCalculated: {mint[:8]}... | "
                f"score={result['final_score']:.2f} | conf={result['confidence']:.2f}"
            )
            return True

        except Exception as e:
            logger.error(f"Error scoring token: {e}")
            self.failed_count += 1
            return False

    def get_stats(self) -> Dict[str, Any]:
        total = self.scored_count + self.failed_count
        return {
            "scored_count": self.scored_count,
            "failed_count": self.failed_count,
            "success_rate": self.scored_count / total if total > 0 else 0,
        }
