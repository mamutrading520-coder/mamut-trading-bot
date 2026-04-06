"""Trash filter engine for token quality assessment."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime

from monitoring.logger import setup_logger
from config.settings import Settings
from config.thresholds import (
    TRASH_FILTER_THRESHOLDS,
    CREATOR_RISK_THRESHOLDS,
    CONCENTRATION_THRESHOLDS,
    AUTHORITY_RISK_THRESHOLDS,
    WALLET_CLUSTER_THRESHOLDS,
)
from storage.sqlite_store import SQLiteStore
from core.event_bus import Event, get_event_bus
from filters.honeypot_detector import HoneypotDetector
from filters.wallet_cluster_checker import WalletClusterChecker

logger = setup_logger("TrashFilterEngine")


class TrashFilterEngine:
    """Filters out low-quality and scam-like tokens using coordinated risk checks."""

    _CONTROL_CHARS_RE = re.compile(r"[\x00-\x1F\x7F]")
    _MULTISPACE_RE = re.compile(r"\s+")
    _WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)?")
    _NUMERICISH_RE = re.compile(r"^(?:(?:19|20)\d{2}|\d+[a-z]{0,3})$", re.IGNORECASE)

    _SEMANTIC_IMPERATIVE_RE = re.compile(r"^\s*(?:join|buy|sell|open|claim|click|follow|watch|check|visit|send|ape|pump|moon|hold|make|create|generate|show|turn|put|draw|render|write)\b", re.IGNORECASE)
    _SEMANTIC_PROMO_RE = re.compile(r"\b(?:most|best|biggest|strongest|bullish|viral|official|guaranteed|unstoppable|massive|epic|legendary|ultimate|alpha)\b.*\b(?:community|army|movement|launch|token|coin|memecoin|pump|run|holders|weeks?|days?|today|now|ever)\b", re.IGNORECASE)
    _SEMANTIC_COMMUNITY_RE = re.compile(r"\b(?:community|army|movement|holders|family|club|gang|squad)\b", re.IGNORECASE)
    _SEMANTIC_CLAIM_RE = re.compile(r"\b(?:most|best|biggest|strongest|bullish|viral|official|guaranteed|unstoppable|massive|epic|legendary|alpha|moonshot|x100|100x)\b", re.IGNORECASE)
    _SEMANTIC_TIME_RE = re.compile(r"\b(?:today|tonight|tomorrow|again|ever|forever|weeks?|days?|months?|years?|right now)\b", re.IGNORECASE)
    _SEMANTIC_PROFANITY_RE = re.compile(r"\b(?:fuck(?:in|ing)?|shit|bitch|asshole|bastard|damn)\b", re.IGNORECASE)
    _SEMANTIC_EXCESSIVE_PUNCT_RE = re.compile(r"[!?]{2,}|[._-]{3,}")
    _SEMANTIC_GENERIC_SYMBOL_RE = re.compile(r"^(?:BUY|SELL|APE|JOIN|FREE|PUMP|NOW|MOON|TEST|TOKEN|COIN|BULLISH|ALPHA)$", re.IGNORECASE)

    _SEMANTIC_FUNCTION_WORDS = {"a", "an", "and", "as", "at", "by", "for", "from", "in", "into", "of", "on", "or", "the", "to", "with", "without", "within"}
    _SEMANTIC_WEAK_STARTERS = {"a", "an", "any", "each", "every", "most", "my", "one", "our", "some", "that", "the", "their", "these", "this", "those", "your"}
    _SEMANTIC_NARRATIVE_STARTERS = {"how", "why", "when", "where", "what", "who"}
    _SEMANTIC_PRONOUN_WORDS = {"i", "you", "he", "she", "it", "we", "they", "me", "him", "her", "them", "us"}
    _SEMANTIC_LINKING_VERBS = {"am", "is", "are", "was", "were", "be", "been", "being"}

    _SEMANTIC_DEICTIC_WORDS = {"this", "that", "these", "those", "my", "your", "our", "their"}
    _SEMANTIC_ROUTING_WORDS = {"ca", "bio", "link", "website", "site", "telegram", "discord", "twitter", "tiktok", "instagram", "insta", "ig", "x"}
    _SEMANTIC_CONTEXT_WORDS = {"ca", "bio", "coin", "token", "launch", "live", "website", "site", "telegram", "discord", "twitter", "tiktok", "dex", "paid", "official", "community", "pump", "moon", "cto", "alpha", "trend", "viral"}
    _SEMANTIC_GENERIC_NAME_WORDS = {"coin", "token", "wif", "inu", "meme", "memecoin", "sol", "cap"}

    _SEMANTIC_STATUS_WORDS = {"suspended", "banned", "paused", "delayed", "live", "online", "offline", "out", "listed", "open", "closed", "updated", "broken", "restored", "available", "ready"}
    _SEMANTIC_STATUS_SUBJECT_WORDS = {"account", "bundle", "launch", "listing", "website", "site", "server", "dex", "update", "news", "market", "channel", "bio", "link"}
    _SEMANTIC_ANNOUNCEMENT_ACTION_WORDS = {"read", "watch", "listen", "check", "join", "follow", "see", "now", "alert", "update", "news", "breaking"}
    _SEMANTIC_TITLE_WORDS = {"life", "story", "tale", "diary", "chronicles", "adventures", "journey", "memoirs", "account", "legend", "days", "nights"}
    _SEMANTIC_TITLE_CONNECTORS = {"with", "of", "from", "about"}
    _SEMANTIC_ROLE_CLAIM_WORDS = {"agent", "groomer", "king", "queen", "hero", "boss", "guru", "dev", "doctor", "hunter", "warrior", "president", "ceo"}
    _SEMANTIC_ARTICLE_WORDS = {"a", "an", "the"}

    def __init__(self, store: SQLiteStore, settings: Settings):
        self.store = store
        self.settings = settings
        self.event_bus = get_event_bus()
        self.honeypot_detector = HoneypotDetector(settings)
        self.wallet_cluster_checker = WalletClusterChecker()
        self.passed = 0
        self.rejected = 0

    def _normalize_text(self, value: Any) -> str:
        text = str(value or "")
        text = self._CONTROL_CHARS_RE.sub(" ", text)
        text = self._MULTISPACE_RE.sub(" ", text).strip()
        return text

    def _extract_words(self, value: str) -> List[str]:
        return self._WORD_RE.findall(value or "")

    def _is_null_like(self, value: Optional[str]) -> bool:
        if not value:
            return True
        normalized = value.strip().lower()
        return normalized in {"", "11111111111111111111111111111111", "system", "systemprogram", "renounced", "none", "null"}

    def _safe_float(self, value: Any, default: float = 0.0) -> float:
        try:
            if value is None:
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    def _safe_int(self, value: Any, default: int = 0) -> int:
        try:
            if value is None:
                return default
            return int(value)
        except (TypeError, ValueError):
            return default

    def _is_numericish(self, word: str) -> bool:
        return bool(self._NUMERICISH_RE.fullmatch(word or ""))

    def _analyze_name_profile(self, words: List[str]) -> Dict[str, bool]:
        lowered_words = [word.lower() for word in words]
        content_words = [word for word in lowered_words if word not in self._SEMANTIC_FUNCTION_WORDS]
        weak_pool = self._SEMANTIC_DEICTIC_WORDS | self._SEMANTIC_ROUTING_WORDS | self._SEMANTIC_CONTEXT_WORDS | self._SEMANTIC_GENERIC_NAME_WORDS
        routing_hits = sum(1 for word in content_words if word in self._SEMANTIC_ROUTING_WORDS)
        context_hits = sum(1 for word in content_words if word in self._SEMANTIC_CONTEXT_WORDS)
        deictic_hits = sum(1 for word in content_words if word in self._SEMANTIC_DEICTIC_WORDS)
        generic_hits = sum(1 for word in content_words if word in self._SEMANTIC_GENERIC_NAME_WORDS)
        numeric_hits = sum(1 for word in content_words if self._is_numericish(word))
        weak_hits = sum(1 for word in content_words if word in weak_pool or self._is_numericish(word))
        content_count = len(content_words)

        starts_weak = bool(lowered_words and lowered_words[0] in self._SEMANTIC_WEAK_STARTERS)
        has_linking_verb = any(word in self._SEMANTIC_LINKING_VERBS for word in lowered_words[1:])
        status_hits = sum(1 for word in lowered_words if word in self._SEMANTIC_STATUS_WORDS)
        status_subject_hits = sum(1 for word in lowered_words if word in self._SEMANTIC_STATUS_SUBJECT_WORDS)
        announcement_hits = sum(1 for word in lowered_words if word in self._SEMANTIC_ANNOUNCEMENT_ACTION_WORDS)
        has_title_word = any(word in self._SEMANTIC_TITLE_WORDS for word in lowered_words)
        has_title_connector = any(word in self._SEMANTIC_TITLE_CONNECTORS for word in lowered_words)

        role_claim_phrase = False
        for idx, word in enumerate(lowered_words):
            if word not in self._SEMANTIC_ROLE_CLAIM_WORDS:
                continue
            article_before = idx > 0 and lowered_words[idx - 1] in self._SEMANTIC_ARTICLE_WORDS
            if article_before or starts_weak or has_linking_verb or any(w in self._SEMANTIC_DEICTIC_WORDS or w in self._SEMANTIC_PRONOUN_WORDS for w in lowered_words[:idx]):
                role_claim_phrase = True
                break

        return {
            "routing_phrase": len(words) <= 3 and routing_hits >= 1 and (context_hits >= 2 or "ca" in content_words),
            "deictic_generic_construct": len(words) <= 3 and deictic_hits >= 1 and generic_hits >= 1,
            "numeric_generic_construct": len(words) <= 3 and numeric_hits >= 1 and generic_hits >= 1,
            "generic_context_construct": len(words) <= 3 and generic_hits >= 1 and context_hits >= 1,
            "all_content_weak": content_count >= 2 and weak_hits == content_count,
            "context_heavy_phrase": len(words) <= 4 and content_count >= 2 and weak_hits >= max(2, content_count - 1),
            "status_update_phrase": len(words) <= 4 and status_hits >= 1 and (status_subject_hits >= 1 or has_linking_verb or starts_weak or announcement_hits >= 1),
            "announcement_phrase": len(words) >= 3 and announcement_hits >= 1 and (status_hits >= 1 or has_linking_verb or status_subject_hits >= 1),
            "title_like_narrative": len(words) >= 3 and has_title_word and has_title_connector,
            "role_claim_phrase": len(words) >= 3 and role_claim_phrase,
        }

    def _creator_history_thresholds(self) -> Dict[str, int]:
        return {
            "min_outcome_history": int(CREATOR_RISK_THRESHOLDS.get("min_outcome_history_for_failure_penalty", 3)),
            "hard_reject_min_tokens": int(CREATOR_RISK_THRESHOLDS.get("hard_reject_min_tokens", 8)),
            "hard_reject_min_outcomes": int(CREATOR_RISK_THRESHOLDS.get("hard_reject_min_outcomes", 4)),
        }

    def _calculate_authority_risk(self, token_data: Dict[str, Any]) -> Dict[str, Any]:
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
            return {"score": risk_score, "has_mint_authority": has_mint_authority, "has_freeze_authority": has_freeze_authority, "owner_renounced": owner_renounced, "reasons": reasons, "warnings": warnings}
        except Exception as e:
            logger.debug(f"Error calculating authority risk: {e}")
            return {"score": 50.0, "has_mint_authority": None, "has_freeze_authority": None, "owner_renounced": False, "reasons": [f"Authority risk error: {e}"], "warnings": []}

    def _calculate_creator_risk(self, token_data: Dict[str, Any]) -> Dict[str, Any]:
        creator = token_data.get("creator")
        creator_resolved = token_data.get("creator_resolved", True)
        thresholds = self._creator_history_thresholds()
        if not creator_resolved or not creator or (isinstance(creator, str) and creator.upper() == "UNKNOWN"):
            return {"score": 42.0, "creator": creator or "unknown", "is_new": False, "is_blacklisted": False, "is_trusted": False, "total_tokens": 0, "successful_tokens": 0, "failed_tokens": 0, "resolved_outcomes": 0, "wallet_age_days": None, "success_rate": 0.0, "failure_rate": 0.0, "hard_reject_eligible": False, "reasons": ["Creator no resuelto"], "warnings": ["Creator identity unavailable"]}
        try:
            creator_profile = self.store.get_creator_profile(creator)
            total_tokens = successful_tokens = failed_tokens = resolved_outcomes = 0
            wallet_age_days = None
            is_blacklisted = is_trusted = False
            success_rate = failure_rate = 0.0
            reasons: List[str] = []
            warnings: List[str] = []
            hard_reject_eligible = False
            if creator_profile:
                total_tokens = int(getattr(creator_profile, "total_tokens", 0) or 0)
                successful_tokens = int(getattr(creator_profile, "successful_tokens", 0) or 0)
                failed_tokens = int(getattr(creator_profile, "failed_tokens", 0) or 0)
                wallet_age_days = getattr(creator_profile, "wallet_age_days", None)
                is_blacklisted = bool(getattr(creator_profile, "is_blacklisted", False))
                is_trusted = bool(getattr(creator_profile, "is_trusted", False))
                resolved_outcomes = max(0, successful_tokens + failed_tokens)
                if resolved_outcomes > 0:
                    success_rate = successful_tokens / resolved_outcomes
                    failure_rate = failed_tokens / resolved_outcomes
                if is_blacklisted:
                    return {"score": 95.0, "creator": creator, "is_new": False, "is_blacklisted": True, "is_trusted": False, "total_tokens": total_tokens, "successful_tokens": successful_tokens, "failed_tokens": failed_tokens, "resolved_outcomes": resolved_outcomes, "wallet_age_days": wallet_age_days, "success_rate": success_rate, "failure_rate": failure_rate, "hard_reject_eligible": True, "reasons": ["Creator blacklisted"], "warnings": []}
                if is_trusted:
                    risk_score = 10.0
                    warnings.append("Creator trusted")
                else:
                    risk_score = 32.0
                    if total_tokens >= 5 and resolved_outcomes == 0:
                        warnings.append("Creator aún no tiene outcomes resueltos")
                        risk_score += 6.0
                    if wallet_age_days is not None:
                        if wallet_age_days < 1:
                            warnings.append("Creator wallet muy nueva")
                            risk_score += 12.0
                        elif wallet_age_days < 7:
                            warnings.append("Creator wallet reciente")
                            risk_score += 8.0
                        elif wallet_age_days < 30:
                            warnings.append("Creator wallet joven")
                            risk_score += 3.0
                    if resolved_outcomes >= thresholds["min_outcome_history"]:
                        if resolved_outcomes >= 6 and failure_rate >= 0.85:
                            reasons.append("Creator con historial confirmado muy negativo")
                            risk_score += 28.0
                        elif resolved_outcomes >= 4 and failure_rate >= 0.70:
                            reasons.append("Creator con historial confirmado débil")
                            risk_score += 18.0
                        elif failure_rate >= 0.50:
                            warnings.append("Creator con tasa elevada de fallos")
                            risk_score += 8.0
                        if success_rate >= 0.60:
                            warnings.append("Creator con buen historial confirmado")
                            risk_score -= 10.0
                        elif success_rate >= 0.40:
                            warnings.append("Creator con historial confirmado aceptable")
                            risk_score -= 5.0
                    else:
                        warnings.append("Historial confirmado insuficiente para castigo duro")
                    if total_tokens >= thresholds["hard_reject_min_tokens"] and wallet_age_days is not None and wallet_age_days < 7:
                        warnings.append("Alta velocidad de lanzamientos en poco tiempo")
                        risk_score += 6.0
                hard_reject_eligible = is_blacklisted or (total_tokens >= thresholds["hard_reject_min_tokens"] and resolved_outcomes >= thresholds["hard_reject_min_outcomes"])
            else:
                warnings.append("Creator sin historial conocido")
                risk_score = 38.0
            risk_score = max(0.0, min(100.0, risk_score))
            return {"score": risk_score, "creator": creator, "is_new": creator_profile is None, "is_blacklisted": is_blacklisted, "is_trusted": is_trusted, "total_tokens": total_tokens, "successful_tokens": successful_tokens, "failed_tokens": failed_tokens, "resolved_outcomes": resolved_outcomes, "wallet_age_days": wallet_age_days, "success_rate": success_rate, "failure_rate": failure_rate, "hard_reject_eligible": hard_reject_eligible, "reasons": reasons, "warnings": warnings}
        except Exception as e:
            logger.debug(f"Error calculating creator risk: {e}")
            return {"score": 50.0, "creator": creator, "is_new": True, "is_blacklisted": False, "is_trusted": False, "total_tokens": 0, "successful_tokens": 0, "failed_tokens": 0, "resolved_outcomes": 0, "wallet_age_days": None, "success_rate": 0.0, "failure_rate": 0.0, "hard_reject_eligible": False, "reasons": [f"Creator risk error: {e}"], "warnings": []}

    def _calculate_concentration_risk(self, token_data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            creator_balance = float(token_data.get("creator_balance", 0) or 0)
            total_supply = float(token_data.get("total_supply", 0) or 0)
            holder_count = int(token_data.get("holder_count", 0) or 0)
            creator_hold_percentage = float(token_data.get("creator_hold_percentage", 0.0) or 0.0)
            top_holder_percentage = float(token_data.get("top_holder_percentage", 0.0) or 0.0)
            top_5_holders_percentage = float(token_data.get("top_5_holders_percentage", 0.0) or 0.0)
            top_10_holders_percentage = float(token_data.get("top_10_holders_percentage", 0.0) or 0.0)
            risk_score = 35.0
            reasons: List[str] = []
            warnings: List[str] = []
            if creator_hold_percentage > 0:
                creator_percentage = creator_hold_percentage
                has_supply_info = True
            elif total_supply > 0:
                creator_percentage = (creator_balance / total_supply) * 100
                has_supply_info = True
            else:
                creator_percentage = 0.0
                has_supply_info = False
            if creator_percentage > 90:
                risk_score = 95.0
                reasons.append("Creator controla >90% del supply")
            elif creator_percentage > 70:
                risk_score = 80.0
                reasons.append("Creator controla >70% del supply")
            elif creator_percentage > 50:
                risk_score = 65.0
                warnings.append("Creator controla >50% del supply")
            elif has_supply_info and creator_percentage < 20:
                risk_score = 25.0
            if top_holder_percentage >= 35:
                risk_score += 15.0
                warnings.append(f"Top holder controla {top_holder_percentage:.1f}% del supply")
            elif top_holder_percentage >= 20:
                risk_score += 8.0
                warnings.append(f"Top holder concentrado ({top_holder_percentage:.1f}%)")
            if top_5_holders_percentage >= 70:
                risk_score += 12.0
                warnings.append(f"Top-5 holders controlan {top_5_holders_percentage:.1f}%")
            elif top_5_holders_percentage >= 50:
                risk_score += 6.0
                warnings.append(f"Top-5 holders elevado ({top_5_holders_percentage:.1f}%)")
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
            return {"score": risk_score, "creator_percentage": creator_percentage, "holder_count": holder_count, "top_holder_percentage": top_holder_percentage, "top_5_holders_percentage": top_5_holders_percentage, "top_10_holders_percentage": top_10_holders_percentage, "reasons": reasons, "warnings": warnings}
        except Exception as e:
            logger.debug(f"Error calculating concentration risk: {e}")
            return {"score": 50.0, "creator_percentage": 0.0, "holder_count": 0, "top_holder_percentage": 0.0, "top_5_holders_percentage": 0.0, "top_10_holders_percentage": 0.0, "reasons": [f"Concentration risk error: {e}"], "warnings": []}

    def _calculate_metadata_risk(self, token_data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            metadata_score_raw = token_data.get("metadata_score")
            metadata_flags = list(token_data.get("metadata_risk_flags", []) or [])
            social_count = int(token_data.get("social_count", 0) or 0)
            metadata_json = token_data.get("metadata_json") or token_data.get("uri_metadata")
            metadata_retrieved = bool(token_data.get("metadata_retrieved", False))
            reasons: List[str] = []
            warnings: List[str] = []
            if metadata_score_raw is None:
                risk_score = 35.0
                warnings.append("Metadata score no disponible aún")
            else:
                metadata_score = float(metadata_score_raw or 0.0)
                if metadata_score <= 0 and not metadata_retrieved and not metadata_json:
                    risk_score = 35.0
                    warnings.append("Metadata aún no enriquecida")
                else:
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
            return {"score": risk_score, "metadata_score": float(metadata_score_raw or 0.0) if metadata_score_raw is not None else None, "metadata_risk_flags": metadata_flags, "social_count": social_count, "reasons": reasons, "warnings": warnings, "metadata_retrieved": metadata_retrieved, "metadata_present": bool(metadata_json)}
        except Exception as e:
            logger.debug(f"Error calculating metadata risk: {e}")
            return {"score": 40.0, "metadata_score": None, "metadata_risk_flags": [], "social_count": 0, "reasons": [], "warnings": [f"Metadata risk fallback: {e}"], "metadata_retrieved": False, "metadata_present": False}

    def _calculate_semantic_risk(self, token_data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            name = self._normalize_text(token_data.get("name"))
            symbol = self._normalize_text(token_data.get("symbol"))
            description = self._normalize_text(token_data.get("description"))
            reasons: List[str] = []
            warnings: List[str] = []
            flags: List[str] = []
            if not name:
                return {"score": 90.0, "reasons": ["Nombre de token ausente"], "warnings": [], "flags": ["missing_name"], "hard_reject": True, "name": "", "symbol": symbol, "word_count": 0, "stopword_ratio": 0.0}

            name_words = self._extract_words(name)
            lowered_words = [word.lower() for word in name_words]
            word_count = len(name_words)
            function_hits = sum(1 for word in lowered_words if word in self._SEMANTIC_FUNCTION_WORDS)
            stopword_ratio = function_hits / max(word_count, 1)
            starts_weak = bool(lowered_words and lowered_words[0] in self._SEMANTIC_WEAK_STARTERS)
            narrative_start = bool(lowered_words and lowered_words[0] in self._SEMANTIC_NARRATIVE_STARTERS)
            has_pronoun = any(word in self._SEMANTIC_PRONOUN_WORDS for word in lowered_words[1:])
            has_linking_verb = any(word in self._SEMANTIC_LINKING_VERBS for word in lowered_words[1:])
            titlecase_words = sum(1 for word in name_words if word[:1].isupper())
            low_capitalization = titlecase_words <= 1
            all_caps_words = sum(1 for word in name_words if len(word) > 1 and word.upper() == word)
            profile = self._analyze_name_profile(name_words)

            risk_score = 10.0
            hard_reject = False
            narrative_clause = word_count == 3 and narrative_start and (has_pronoun or has_linking_verb)
            weak_lead_phrase = word_count >= 4 and starts_weak and function_hits >= 1
            clause_like_structure = has_linking_verb and (narrative_start or starts_weak or function_hits >= 1)
            inflated_all_caps_phrase = word_count >= 4 and all_caps_words >= 3 and function_hits <= 1

            if word_count == 3:
                risk_score += 8.0
            elif word_count >= 4:
                risk_score += 14.0
                warnings.append("Nombre demasiado largo para branding temprano")
                flags.append("multiword_name")
            if word_count > 5:
                risk_score += 12.0
                reasons.append("Nombre excesivamente largo y poco propio de ticker")
                flags.append("overlong_phrase")
            if function_hits >= 2:
                risk_score += 10.0
                warnings.append("Nombre con demasiadas palabras funcionales")
                flags.append("high_stopword_load")
            elif stopword_ratio >= 0.34 and word_count >= 3:
                risk_score += 6.0
                warnings.append("Nombre con estructura poco compacta")
                flags.append("stopword_heavy")
            if starts_weak and word_count >= 3:
                risk_score += 8.0
                warnings.append("Nombre inicia como frase o statement")
                flags.append("weak_starter")
            if narrative_start:
                risk_score += 16.0
                warnings.append("Nombre arranca con estructura narrativa")
                flags.append("narrative_start")
            if low_capitalization and word_count >= 4:
                risk_score += 10.0
                warnings.append("Capitalización de frase común o narrativa")
                flags.append("common_phrase_casing")
            if all_caps_words >= 3 and word_count >= 4:
                risk_score += 18.0
                warnings.append("Claim multi-palabra en mayúsculas")
                flags.append("all_caps_claim")

            if profile["routing_phrase"]:
                risk_score += 48.0
                reasons.append("Nombre corto dominado por routing/contexto, no por branding")
                flags.append("routing_context_phrase")
                hard_reject = True
            if profile["deictic_generic_construct"]:
                risk_score += 44.0
                reasons.append("Nombre corto deíctico + genérico, sin identidad propia")
                flags.append("deictic_generic_construct")
                hard_reject = True
            if profile["numeric_generic_construct"]:
                risk_score += 40.0
                reasons.append("Nombre corto numérico + genérico, sin branding consistente")
                flags.append("numeric_generic_construct")
                hard_reject = True
            if profile["generic_context_construct"]:
                risk_score += 36.0
                reasons.append("Nombre corto combina léxico genérico con contexto promocional")
                flags.append("generic_context_construct")
                hard_reject = True
            if profile["all_content_weak"]:
                risk_score += 34.0
                reasons.append("Nombre corto de baja identidad, compuesto solo por léxico débil")
                flags.append("low_identity_short_name")
                hard_reject = True
            elif profile["context_heavy_phrase"]:
                risk_score += 22.0
                warnings.append("Nombre corto excesivamente cargado de léxico contextual/generico")
                flags.append("context_heavy_short_name")

            if profile["status_update_phrase"]:
                risk_score += 44.0
                reasons.append("Nombre funciona como status/update, no como branding")
                flags.append("status_update_phrase")
                hard_reject = True
            if profile["announcement_phrase"]:
                risk_score += 40.0
                reasons.append("Nombre funciona como anuncio o instrucción editorial")
                flags.append("announcement_phrase")
                hard_reject = True
            if profile["title_like_narrative"]:
                risk_score += 34.0
                reasons.append("Nombre parece título narrativo/editorial, no nombre de token")
                flags.append("title_like_narrative_phrase")
                hard_reject = True
            if profile["role_claim_phrase"]:
                risk_score += 36.0
                reasons.append("Nombre contiene claim de rol/persona, no branding limpio")
                flags.append("role_claim_phrase")
                hard_reject = True

            if self._SEMANTIC_IMPERATIVE_RE.match(name) and word_count >= 2:
                risk_score += 42.0
                reasons.append("Nombre se comporta como CTA o frase imperativa")
                flags.append("cta_phrase")
                hard_reject = True
            promo_hit = self._SEMANTIC_PROMO_RE.search(name)
            claim_hit = self._SEMANTIC_CLAIM_RE.search(name)
            community_hit = self._SEMANTIC_COMMUNITY_RE.search(name)
            time_hit = self._SEMANTIC_TIME_RE.search(name)
            if promo_hit or (claim_hit and (community_hit or time_hit)):
                risk_score += 36.0
                reasons.append("Nombre con semántica promocional o slogan narrativo")
                flags.append("promo_slogan")
                hard_reject = True
            if self._SEMANTIC_PROFANITY_RE.search(name) and word_count >= 2:
                risk_score += 30.0
                reasons.append("Nombre agresivo o profano impropio de branding serio")
                flags.append("profane_phrase")
                hard_reject = True
            if narrative_clause:
                risk_score += 38.0
                reasons.append("Nombre con estructura narrativa tipo statement, no tipo token")
                flags.append("narrative_clause")
                hard_reject = True
            if weak_lead_phrase:
                risk_score += 28.0
                reasons.append("Nombre parece frase común iniciada como statement")
                flags.append("weak_lead_phrase")
                hard_reject = True
            if clause_like_structure and not narrative_clause:
                risk_score += 16.0
                warnings.append("Nombre contiene verbo o estructura de clause")
                flags.append("linking_verb_structure")
            if inflated_all_caps_phrase:
                risk_score += 42.0
                reasons.append("Nombre multi-palabra en mayúsculas luce como branding inflado o artificial")
                flags.append("inflated_all_caps_phrase")
                hard_reject = True

            sentence_like = (
                (word_count >= 4 and ((starts_weak and low_capitalization) or stopword_ratio >= 0.45))
                or (word_count >= 3 and clause_like_structure and (narrative_start or function_hits >= 1))
                or (time_hit and (starts_weak or low_capitalization or all_caps_words >= 3))
                or (low_capitalization and function_hits >= 2)
            )
            if sentence_like:
                risk_score += 26.0
                reasons.append("Nombre luce como frase común o statement, no como token")
                flags.append("sentence_like_name")
                hard_reject = True
            if self._SEMANTIC_EXCESSIVE_PUNCT_RE.search(name):
                risk_score += 8.0
                warnings.append("Puntuación exagerada en nombre")
                flags.append("excessive_punctuation")
            if symbol and self._SEMANTIC_GENERIC_SYMBOL_RE.fullmatch(symbol):
                risk_score += 14.0
                warnings.append("Símbolo genérico o promocional")
                flags.append("generic_placeholder_symbol")
            if description:
                description_words = len(self._extract_words(description))
                if description_words >= 6 and (self._SEMANTIC_IMPERATIVE_RE.match(description) or self._SEMANTIC_PROMO_RE.search(description)):
                    risk_score += 8.0
                    warnings.append("Descripción refuerza tono promocional o CTA")
                    flags.append("promo_description")

            concise_brandlike = word_count <= 2 and function_hits == 0 and not hard_reject and "multiword_name" not in flags and "generic_placeholder_symbol" not in flags
            if concise_brandlike:
                risk_score -= 6.0

            risk_score = round(max(0.0, min(100.0, risk_score)), 2)
            return {"score": risk_score, "reasons": reasons, "warnings": warnings, "flags": flags, "hard_reject": hard_reject, "name": name, "symbol": symbol, "word_count": word_count, "stopword_ratio": round(stopword_ratio, 3)}
        except Exception as e:
            logger.debug(f"Error calculating semantic risk: {e}")
            return {"score": 55.0, "reasons": [f"Semantic risk fallback: {e}"], "warnings": [], "flags": ["semantic_risk_error"], "hard_reject": False, "name": self._normalize_text(token_data.get("name")), "symbol": self._normalize_text(token_data.get("symbol")), "word_count": 0, "stopword_ratio": 0.0}

    def _build_honeypot_input(self, token_data: Dict[str, Any], wallet_cluster_risk: Dict[str, Any]) -> Dict[str, Any]:
        creator_analysis = token_data.get("analysis", {}) or {}
        creator_tokens_created = self._safe_int(token_data.get("creator_tokens_created", creator_analysis.get("total_tokens")))
        creator_failed_tokens = self._safe_int(token_data.get("creator_failed_tokens", creator_analysis.get("failed_tokens")))
        creator_successful_tokens = self._safe_int(token_data.get("creator_successful_tokens", creator_analysis.get("successful_tokens")))
        creator_failure_rate = token_data.get("creator_failure_rate")
        if creator_failure_rate is None:
            creator_failure_rate = creator_analysis.get("failure_rate")
        if creator_failure_rate is None and creator_tokens_created > 0:
            creator_failure_rate = creator_failed_tokens / creator_tokens_created
        creator_success_rate = token_data.get("creator_success_rate")
        if creator_success_rate is None:
            creator_success_rate = creator_analysis.get("success_rate")
        if creator_success_rate is None and creator_tokens_created > 0:
            creator_success_rate = creator_successful_tokens / creator_tokens_created
        top_holder_percentage = self._safe_float(token_data.get("top_holder_percentage", 0.0))
        holder_concentration = token_data.get("holder_concentration")
        if holder_concentration is None:
            holder_concentration = token_data.get("holder_concentration_score")
        holder_concentration = self._safe_float(holder_concentration, 0.0)
        if holder_concentration > 1.0:
            holder_concentration = holder_concentration / 100.0
        return {**token_data, "mint_authority": None if self._is_null_like(token_data.get("mint_authority")) else token_data.get("mint_authority"), "freeze_authority": None if self._is_null_like(token_data.get("freeze_authority")) else token_data.get("freeze_authority"), "creator_tokens_created": creator_tokens_created, "creator_failure_rate": self._safe_float(creator_failure_rate, 0.0), "creator_success_rate": self._safe_float(creator_success_rate, 0.0), "top_holder_ratio": max(0.0, min(1.0, top_holder_percentage / 100.0)), "holder_concentration": max(0.0, min(1.0, holder_concentration)), "wallet_cluster_score": self._safe_float(wallet_cluster_risk.get("wallet_cluster_risk_score", wallet_cluster_risk.get("score", 0.0)), 0.0) / 100.0}

    def _combine_risks(self, authority_risk: Dict[str, Any], creator_risk: Dict[str, Any], concentration_risk: Dict[str, Any], metadata_risk: Dict[str, Any], honeypot_risk: Dict[str, Any], wallet_cluster_risk: Dict[str, Any], semantic_risk: Dict[str, Any]) -> Dict[str, Any]:
        weighted_score = round(max(0.0, min(100.0, authority_risk["score"] * 0.18 + creator_risk["score"] * 0.14 + concentration_risk["score"] * 0.10 + metadata_risk["score"] * 0.06 + honeypot_risk["risk_score"] * 0.18 + wallet_cluster_risk.get("score", 0.0) * 0.08 + semantic_risk["score"] * 0.26)), 2)
        reasons = authority_risk.get("reasons", []) + creator_risk.get("reasons", []) + concentration_risk.get("reasons", []) + metadata_risk.get("reasons", []) + honeypot_risk.get("reasons", []) + wallet_cluster_risk.get("wallet_cluster_flags", []) + semantic_risk.get("reasons", [])
        warnings = authority_risk.get("warnings", []) + creator_risk.get("warnings", []) + concentration_risk.get("warnings", []) + metadata_risk.get("warnings", []) + honeypot_risk.get("warnings", []) + semantic_risk.get("warnings", [])
        risk_level = "critical" if weighted_score >= 75 else "high" if weighted_score >= 55 else "medium" if weighted_score >= 35 else "low"
        return {"risk_score": weighted_score, "risk_level": risk_level, "reasons": reasons, "warnings": warnings}

    def _should_reject(self, authority_risk: Dict[str, Any], creator_risk: Dict[str, Any], concentration_risk: Dict[str, Any], metadata_risk: Dict[str, Any], honeypot_risk: Dict[str, Any], wallet_cluster_risk: Dict[str, Any], semantic_risk: Dict[str, Any], aggregate: Dict[str, Any]) -> Tuple[bool, List[str]]:
        rejection_reasons: List[str] = []
        if authority_risk["score"] > AUTHORITY_RISK_THRESHOLDS.get("max_authority_risk", 80):
            rejection_reasons.append("Exceeds authority risk threshold")
        if creator_risk["score"] > CREATOR_RISK_THRESHOLDS.get("max_creator_risk", 85) and creator_risk.get("hard_reject_eligible", False):
            rejection_reasons.append("Exceeds creator risk threshold")
        if concentration_risk["score"] > CONCENTRATION_THRESHOLDS.get("max_concentration_risk", 80):
            rejection_reasons.append("Exceeds concentration risk threshold")
        if honeypot_risk.get("is_suspicious", False) and honeypot_risk.get("risk_score", 0) >= 70:
            rejection_reasons.append("High honeypot/suspicious-token risk")
        metadata_present = metadata_risk.get("metadata_present", False)
        metadata_retrieved = metadata_risk.get("metadata_retrieved", False)
        if metadata_present and metadata_retrieved and metadata_risk["score"] > TRASH_FILTER_THRESHOLDS.get("max_metadata_risk", 90):
            rejection_reasons.append("Exceeds metadata risk threshold")
        if wallet_cluster_risk.get("score", 0.0) > WALLET_CLUSTER_THRESHOLDS.get("max_wallet_cluster_risk", 80):
            rejection_reasons.append("Extreme wallet cluster concentration detected")
        if semantic_risk.get("hard_reject", False):
            rejection_reasons.append("Semantic profile incompatible with token branding")
        elif semantic_risk.get("score", 0.0) >= 68.0:
            rejection_reasons.append("Exceeds semantic risk threshold")
        if aggregate["risk_score"] > TRASH_FILTER_THRESHOLDS.get("max_total_risk", 75):
            rejection_reasons.append("Exceeds aggregate trash-filter risk threshold")
        return len(rejection_reasons) > 0, rejection_reasons

    async def filter_and_emit(self, event: Event) -> Optional[str]:
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
            semantic_risk = self._calculate_semantic_risk(token_data)
            wallet_cluster_risk = await self.wallet_cluster_checker.analyze(token_data)
            honeypot_input = self._build_honeypot_input(token_data=token_data, wallet_cluster_risk=wallet_cluster_risk)
            honeypot_risk = await self.honeypot_detector.analyze(honeypot_input)
            aggregate = self._combine_risks(authority_risk, creator_risk, concentration_risk, metadata_risk, honeypot_risk, wallet_cluster_risk, semantic_risk)
            reject, rejection_reasons = self._should_reject(authority_risk, creator_risk, concentration_risk, metadata_risk, honeypot_risk, wallet_cluster_risk, semantic_risk, aggregate)
            component_results = {"authority_risk": authority_risk, "creator_risk": creator_risk, "concentration_risk": concentration_risk, "metadata_risk": metadata_risk, "honeypot_risk": honeypot_risk, "wallet_cluster_risk": wallet_cluster_risk, "semantic_risk": semantic_risk}

            if reject:
                self.rejected += 1
                rejection_event = Event(event_type="TokenRejected", data={**token_data, "mint": mint, "reason": " | ".join(rejection_reasons), "rejection_reason": " | ".join(rejection_reasons), "aggregate_risk_score": aggregate["risk_score"], "aggregate_risk_level": aggregate["risk_level"], "component_results": component_results, "warnings": aggregate["warnings"], "semantic_risk": semantic_risk["score"], "semantic_risk_flags": semantic_risk.get("flags", [])}, source="TrashFilterEngine", timestamp=datetime.utcnow())
                await self.event_bus.emit(rejection_event)
                logger.warning(f"[REJECTED] {mint[:8]}... | risk={aggregate['risk_score']:.1f} | semantic={semantic_risk['score']:.1f} | {rejection_reasons[0]}")
                return "REJECTED"

            self.passed += 1
            passed_event = Event(event_type="TokenPassed", data={**token_data, "aggregate_risk_score": aggregate["risk_score"], "aggregate_risk_level": aggregate["risk_level"], "component_results": component_results, "warnings": aggregate["warnings"], "authority_risk": authority_risk["score"], "creator_risk": creator_risk["score"], "concentration_risk": concentration_risk["score"], "metadata_risk": metadata_risk["score"], "honeypot_risk": honeypot_risk["risk_score"], "wallet_cluster_risk": wallet_cluster_risk.get("score", 0.0), "semantic_risk": semantic_risk["score"], "semantic_risk_flags": semantic_risk.get("flags", [])}, source="TrashFilterEngine", timestamp=datetime.utcnow())
            await self.event_bus.emit(passed_event)
            logger.info(f"[PASSED FILTERS] {mint[:8]}... | total_risk={aggregate['risk_score']:.1f} | auth={authority_risk['score']:.0f} creator={creator_risk['score']:.0f} | semantic={semantic_risk['score']:.0f} cluster={wallet_cluster_risk.get('score', 0.0):.0f}")
            return "PASSED"
        except Exception as e:
            logger.error(f"Error filtering token: {e}")
            return None

    def get_stats(self) -> Dict[str, Any]:
        total = self.passed + self.rejected
        return {"passed": self.passed, "rejected": self.rejected, "pass_rate": (self.passed / total * 100) if total > 0 else 0, "honeypot_detector": self.honeypot_detector.get_stats(), "wallet_cluster_checker": self.wallet_cluster_checker.get_stats()}
