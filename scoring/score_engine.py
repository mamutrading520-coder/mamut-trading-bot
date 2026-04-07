"""Score engine for passed tokens."""

from __future__ import annotations

import re
from typing import Any, Dict, List
from datetime import datetime

from monitoring.logger import setup_logger
from core.event_bus import Event, get_event_bus

logger = setup_logger("ScoreEngine")


class ScoreEngine:
    """Computes final token score after trash filtering."""

    _WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)?")
    _ASSET_MIMIC_WORDS = {
        "btc", "bitcoin", "eth", "ethereum", "sol", "solana", "bnb", "xrp",
        "doge", "dogecoin", "pepe", "usd", "usdc", "usdt",
    }
    _GENERIC_FINANCIAL_WORDS = {
        "credit", "wealth", "money", "cash", "capital", "profit", "profits",
        "gains", "fortune", "finance", "bank", "pay", "payment", "paycheck",
        "income", "rich", "riches", "prosperity",
    }
    _COMMUNITY_IDENTITY_WORDS = {
        "holders", "hodlers", "holder", "army", "community", "club", "gang",
        "cult", "fam", "family",
    }
    _GENERIC_ARCHETYPE_WORDS = {
        "assassin", "killer", "warrior", "hero", "boss", "legend", "queen", "king",
    }

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

    def _normalize_brand_text(self, value: Any) -> str:
        text = str(value or "").strip().lower()
        text = re.sub(r"[^a-z0-9]+", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    def _extract_words(self, value: Any) -> List[str]:
        return [word.lower() for word in self._WORD_RE.findall(str(value or ""))]

    def _calculate_brand_distinctiveness(self, token_data: Dict[str, Any]) -> Dict[str, Any]:
        name_words = self._extract_words(token_data.get("name"))
        symbol_words = self._extract_words(token_data.get("symbol"))
        all_words = name_words + symbol_words

        score = 100.0
        flags: List[str] = []
        notes: List[str] = []

        asset_hits = sorted({word for word in all_words if word in self._ASSET_MIMIC_WORDS})
        finance_hits = sorted({word for word in name_words if word in self._GENERIC_FINANCIAL_WORDS})
        community_hits = sorted({word for word in name_words if word in self._COMMUNITY_IDENTITY_WORDS})
        archetype_hits = sorted({word for word in name_words if word in self._GENERIC_ARCHETYPE_WORDS})
        weak_brand_hits = len(asset_hits) + len(finance_hits) + len(community_hits) + len(archetype_hits)

        if asset_hits:
            score -= 42.0
            flags.append("asset_mimic_branding")
            notes.append("Brand mimics canonical asset/ticker lexicon")

        if finance_hits:
            score -= 28.0 if len(name_words) <= 2 else 18.0
            flags.append("generic_financial_branding")
            notes.append("Brand relies on generic financial lexicon")

        if community_hits:
            score -= 18.0
            flags.append("community_followership_branding")
            notes.append("Brand framed around followers/community identity")

        if len(name_words) == 1 and archetype_hits:
            score -= 16.0
            flags.append("generic_archetype_branding")
            notes.append("Brand uses generic archetype word")

        if name_words and len(name_words) <= 2 and weak_brand_hits >= max(1, len(name_words)):
            score -= 14.0
            flags.append("low_brand_specificity")
            notes.append("Brand distinctiveness too dependent on generic lexicon")

        score = round(max(0.0, min(100.0, score)), 2)
        deduped_flags = list(dict.fromkeys(flags))
        deduped_notes = list(dict.fromkeys(notes))
        return {
            "score": score,
            "flags": deduped_flags,
            "notes": deduped_notes,
        }

    def _semantic_flag_penalty(self, semantic_flags: List[str]) -> float:
        severe_flags = {
            "cta_phrase",
            "promo_slogan",
            "profane_phrase",
            "profane_symbol",
            "sentence_like_name",
            "overlong_phrase",
            "generic_placeholder_symbol",
            "narrative_clause",
            "weak_lead_phrase",
            "linking_verb_structure",
            "inflated_all_caps_phrase",
            "routing_context_phrase",
            "deictic_generic_construct",
            "numeric_generic_construct",
            "generic_context_construct",
            "low_identity_short_name",
            "status_update_phrase",
            "announcement_phrase",
            "title_like_narrative_phrase",
            "role_claim_phrase",
            "generic_prefix_branding",
            "aspirational_generic_branding",
        }
        severe_hits = [flag for flag in semantic_flags if flag in severe_flags]
        if not severe_hits:
            return 0.0
        return min(22.0, 10.0 + max(0, len(severe_hits) - 1) * 2.0)

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

        brand_profile = self._calculate_brand_distinctiveness(token_data)
        brand_distinctiveness = self._safe_float(brand_profile.get("score", 100), 100.0)
        brand_flags = list(brand_profile.get("flags", []) or [])
        brand_notes = list(brand_profile.get("notes", []) or [])

        score = 62.0
        notes: List[str] = []

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

        score -= aggregate_risk * 0.40

        if semantic_risk >= 80:
            score -= 20
            notes.append("Critical semantic contamination")
        elif semantic_risk >= 65:
            score -= 14
            notes.append("High semantic contamination")
        elif semantic_risk >= 50:
            score -= 9
            notes.append("Weak token-brand semantics")
        elif semantic_risk >= 35:
            score -= 5
            notes.append("Borderline semantic contamination")
        elif semantic_risk >= 25:
            score -= 3

        if brand_distinctiveness < 70:
            score -= 4
            notes.append("Weak brand distinctiveness")
        if brand_distinctiveness < 55:
            score -= 8
        if brand_distinctiveness < 40:
            score -= 12
        if brand_flags:
            score -= min(16.0, len(brand_flags) * 4.0)
            notes.extend(brand_notes[:2])
            notes.append(f"Brand flags: {', '.join(brand_flags[:4])}")

        hard_weak_name_flags = {
            "routing_context_phrase",
            "deictic_generic_construct",
            "numeric_generic_construct",
            "generic_context_construct",
            "low_identity_short_name",
            "status_update_phrase",
            "announcement_phrase",
            "title_like_narrative_phrase",
            "role_claim_phrase",
            "generic_prefix_branding",
            "aspirational_generic_branding",
            "profane_symbol",
        }
        medium_weak_name_flags = {
            "context_heavy_short_name",
            "inflated_all_caps_phrase",
            "sentence_like_name",
            "weak_lead_phrase",
            "linking_verb_structure",
        }
        hard_brand_flags = {
            "asset_mimic_branding",
            "generic_financial_branding",
            "community_followership_branding",
        }
        review_brand_flags = {
            "generic_archetype_branding",
            "low_brand_specificity",
        }

        if any(flag in hard_weak_name_flags for flag in semantic_flags):
            score -= 20
            notes.append("Hard semantic weak-name class detected")
        elif any(flag in medium_weak_name_flags for flag in semantic_flags):
            score -= 10
            notes.append("Weak semantic naming pattern detected")

        if any(flag in hard_brand_flags for flag in brand_flags):
            score -= 14
            notes.append("Hard brand distinctiveness issue detected")
        elif any(flag in review_brand_flags for flag in brand_flags):
            score -= 8
            notes.append("Brand distinctiveness issue detected")

        if "multiword_name" in semantic_flags and "all_caps_claim" in semantic_flags:
            score -= 10
            notes.append("Inflated multiword all-caps naming pattern")

        score -= self._semantic_flag_penalty(semantic_flags)
        if semantic_flags:
            notes.append(f"Semantic flags: {', '.join(semantic_flags[:6])}")

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
        brand_cleanliness = max(0.0, brand_distinctiveness) / 100.0
        confidence = (
            (final_score / 100.0) * 0.40
            + (cleanliness / 100.0) * 0.22
            + (semantic_cleanliness / 100.0) * 0.13
            + brand_cleanliness * 0.10
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
        elif semantic_risk >= 25:
            confidence -= 0.02

        if brand_distinctiveness < 70:
            confidence -= 0.03
        if brand_distinctiveness < 55:
            confidence -= 0.05
        if brand_distinctiveness < 40:
            confidence -= 0.08

        if any(flag in hard_weak_name_flags for flag in semantic_flags):
            confidence -= 0.14
        elif any(flag in medium_weak_name_flags for flag in semantic_flags):
            confidence -= 0.08
        if any(flag in hard_brand_flags for flag in brand_flags):
            confidence -= 0.10
        elif any(flag in review_brand_flags for flag in brand_flags):
            confidence -= 0.06
        if "multiword_name" in semantic_flags and "all_caps_claim" in semantic_flags:
            confidence -= 0.08

        semantic_early_gate_applied = False
        if any(flag in hard_weak_name_flags for flag in semantic_flags):
            final_score = min(final_score, 59.0)
            confidence = min(confidence, 0.64)
            semantic_early_gate_applied = True
            notes.append("Semantic early-signal gate applied")
        elif semantic_risk >= 30 and any(flag in medium_weak_name_flags for flag in semantic_flags):
            final_score = min(final_score, 59.0)
            confidence = min(confidence, 0.64)
            semantic_early_gate_applied = True
            notes.append("Borderline semantic early-signal gate applied")

        brand_early_gate_applied = False
        if any(flag in hard_brand_flags for flag in brand_flags) or brand_distinctiveness < 52:
            final_score = min(final_score, 61.0)
            confidence = min(confidence, 0.66)
            brand_early_gate_applied = True
            notes.append("Brand distinctiveness early-signal gate applied")
        elif any(flag in review_brand_flags for flag in brand_flags) and brand_distinctiveness < 62:
            final_score = min(final_score, 63.0)
            confidence = min(confidence, 0.67)
            brand_early_gate_applied = True
            notes.append("Borderline brand early-signal gate applied")

        confidence = round(max(0.0, min(0.99, confidence)), 4)
        final_score = round(max(0.0, min(100.0, final_score)), 2)

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
                "brand_distinctiveness_score": brand_distinctiveness,
                "brand_flags": brand_flags,
                "brand_notes": brand_notes,
                "metadata_retrieved": metadata_retrieved,
                "metadata_present": metadata_present,
                "semantic_early_gate_applied": semantic_early_gate_applied,
                "brand_early_gate_applied": brand_early_gate_applied,
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
