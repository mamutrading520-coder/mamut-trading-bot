"""Parser for Pump.fun token events"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Dict, Any

from config.thresholds import TOKEN_METADATA_THRESHOLDS
from monitoring.logger import setup_logger

logger = setup_logger("PumpEventParser")


@dataclass
class ParsedTokenEvent:
    """Parsed token event data"""
    mint: str
    name: str
    symbol: str
    creator: str
    signature: str
    initial_sol: float
    market_cap_sol: float
    uri: str
    timestamp: int = 0
    initial_buy: int = 0
    bonding_curve: str = ""
    v_tokens_in_bonding_curve: int = 0
    v_sol_in_bonding_curve: float = 0.0
    creator_resolved: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "mint": self.mint,
            "name": self.name,
            "symbol": self.symbol,
            "creator": self.creator,
            "creator_resolved": self.creator_resolved,
            "signature": self.signature,
            "tx_signature": self.signature,
            "initial_sol": self.initial_sol,
            "initial_buy": self.initial_buy,
            "market_cap_sol": self.market_cap_sol,
            "uri": self.uri,
            "timestamp": self.timestamp,
            "bonding_curve": self.bonding_curve,
            "v_tokens_in_bonding_curve": self.v_tokens_in_bonding_curve,
            "v_sol_in_bonding_curve": self.v_sol_in_bonding_curve,
        }


class PumpEventParser:
    """Parses Pump.fun WebSocket events"""

    _CONTROL_CHARS_RE = re.compile(r"[\x00-\x1F\x7F]")
    _MULTISPACE_RE = re.compile(r"\s+")
    _URL_LIKE_RE = re.compile(r"(?:https?://|www\.|t\.me/|discord(?:\.gg|app\.com/))", re.IGNORECASE)
    _MENTION_RE = re.compile(r"(?:@everyone|@here|<@&?|^@[A-Za-z0-9_]+$)", re.IGNORECASE)
    _COMMAND_PREFIX_RE = re.compile(r"^\s*[/!#.]+\s*[a-zA-Z]", re.IGNORECASE)
    _COMMAND_WITH_AMOUNT_RE = re.compile(
        r"^\s*[/!]?\s*(buy|sell|swap|ape|long|short|tp|sl)\b.*\b\d+(?:\.\d+)?\b",
        re.IGNORECASE,
    )
    _PAIR_OR_ACTION_RE = re.compile(
        r"\b(?:buy|sell|swap|ape|long|short|tp|sl)\b.*\b(?:sol|usd|usdc|usdt)\b",
        re.IGNORECASE,
    )
    _IMPERATIVE_PROMPT_RE = re.compile(
        r"^\s*(?:put|make|create|generate|draw|render|show|turn|dress|write|imagine)\b",
        re.IGNORECASE,
    )
    _AI_PROMPT_RE = re.compile(
        r"\b(?:grok|chatgpt|midjourney|stable\s*diffusion|dall-?e)\b.*\b(?:imagine|prompt|style|render|draw|make)\b",
        re.IGNORECASE,
    )
    _STYLE_PROMPT_RE = re.compile(
        r"\b(?:in the style of|prompt:|cinematic|8k|ultra detailed|hyperrealistic)\b",
        re.IGNORECASE,
    )
    _VALID_SYMBOL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_$.-]{0,19}$")

    def parse(self, data: Dict[str, Any]) -> Optional[ParsedTokenEvent]:
        """Parse token creation event"""
        try:
            mint = data.get("mint")
            signature = data.get("signature")
            raw_name = data.get("name") or "UNKNOWN"
            raw_symbol = data.get("symbol") or "UNKNOWN"
            creator_raw = data.get("traderPublicKey") or data.get("creator") or ""
            creator = creator_raw or "UNKNOWN"
            creator_resolved = creator not in {"", "UNKNOWN", "unknown"}
            uri = data.get("uri", "")
            timestamp = int(data.get("createdTimestamp") or data.get("timestamp") or 0)
            bonding_curve = data.get("bondingCurveKey") or data.get("bonding_curve") or ""

            if not mint or not signature:
                logger.warning("Missing mint or signature")
                return None

            name = self._normalize_text(raw_name)
            symbol = self._normalize_text(raw_symbol)

            if not self._is_valid_name(name):
                logger.info(f"Rejected parser garbage token name: {raw_name!r}")
                return None

            if not self._is_valid_symbol(symbol):
                logger.info(f"Rejected parser garbage token symbol: {raw_symbol!r}")
                return None

            initial_buy = int(data.get("initialBuy") or 0)
            if initial_buy > 0:
                initial_sol = initial_buy / 1e9
            elif "initial_sol" in data:
                initial_sol = float(data.get("initial_sol") or 0)
            else:
                initial_sol = 0.0

            v_tokens_in_bonding_curve = int(
                data.get("vTokensInBondingCurve") or data.get("v_tokens_in_bonding_curve") or 0
            )
            v_sol_raw = data.get("vSolInBondingCurve") or data.get("v_sol_in_bonding_curve") or 0
            v_sol_in_bonding_curve = float(v_sol_raw) / 1e9 if v_sol_raw else 0.0

            market_cap_sol = float(data.get("market_cap_sol") or 0)
            if market_cap_sol == 0.0 and v_tokens_in_bonding_curve > 0 and v_sol_raw:
                market_cap_sol = float(v_sol_raw) * 1_000_000 / v_tokens_in_bonding_curve

            parsed = ParsedTokenEvent(
                mint=mint,
                name=name,
                symbol=symbol,
                creator=creator,
                signature=signature,
                initial_sol=initial_sol,
                initial_buy=initial_buy,
                market_cap_sol=market_cap_sol,
                uri=uri,
                timestamp=timestamp,
                bonding_curve=bonding_curve,
                v_tokens_in_bonding_curve=v_tokens_in_bonding_curve,
                v_sol_in_bonding_curve=v_sol_in_bonding_curve,
                creator_resolved=creator_resolved,
            )

            creator_display = creator[:8] if len(creator) >= 8 else creator
            logger.info(f"✓ Parsed: {symbol} | SOL: {initial_sol:.4f} | Creator: {creator_display}...")
            return parsed

        except Exception as e:
            logger.warning(f"Parse error: {e}")
            return None

    def _normalize_text(self, value: Any) -> str:
        text = str(value or "")
        text = self._CONTROL_CHARS_RE.sub(" ", text)
        text = self._MULTISPACE_RE.sub(" ", text).strip()
        return text

    def _is_valid_name(self, value: str) -> bool:
        if not self._passes_length(value, kind="name"):
            return False

        if self._URL_LIKE_RE.search(value):
            return False

        if self._MENTION_RE.search(value):
            return False

        if self._COMMAND_PREFIX_RE.match(value):
            return False

        if self._COMMAND_WITH_AMOUNT_RE.match(value):
            return False

        if self._PAIR_OR_ACTION_RE.search(value) and ("/" in value or any(ch.isdigit() for ch in value)):
            return False

        if self._looks_like_prompt_text(value):
            return False

        non_alnum_ratio = sum(1 for ch in value if not ch.isalnum() and ch != " ") / max(len(value), 1)
        if len(value) >= 8 and non_alnum_ratio > 0.35:
            return False

        return True

    def _is_valid_symbol(self, value: str) -> bool:
        if not self._passes_length(value, kind="symbol"):
            return False

        if " " in value:
            return False

        if value.startswith("@"):
            return False

        if self._URL_LIKE_RE.search(value):
            return False

        if self._MENTION_RE.search(value):
            return False

        if self._COMMAND_PREFIX_RE.match(value):
            return False

        if not self._VALID_SYMBOL_RE.fullmatch(value):
            return False

        return True

    def _passes_length(self, value: str, kind: str) -> bool:
        if not value or not value.strip():
            logger.debug(f"Invalid {kind}: empty")
            return False

        min_len = TOKEN_METADATA_THRESHOLDS.get(f"min_{kind}_length", 1)
        max_len = TOKEN_METADATA_THRESHOLDS.get(f"max_{kind}_length", 100)
        if len(value) < min_len or len(value) > max_len:
            logger.debug(f"Invalid {kind}: length out of range ({len(value)})")
            return False

        return True

    def _looks_like_prompt_text(self, value: str) -> bool:
        normalized = value.strip()
        lowered = normalized.lower()
        words = [word for word in normalized.split(" ") if word]

        if self._AI_PROMPT_RE.search(normalized):
            return True

        if self._STYLE_PROMPT_RE.search(normalized) and len(words) >= 3:
            return True

        if self._IMPERATIVE_PROMPT_RE.match(normalized) and len(words) >= 3:
            return True

        if lowered.startswith(("put ", "make ", "create ", "generate ", "draw ", "render ", "turn ")) and len(words) >= 3:
            return True

        if "grok imagine" in lowered or "chatgpt prompt" in lowered or "midjourney prompt" in lowered:
            return True

        if any(pronoun in lowered for pronoun in [" her ", " him ", " them ", " it "]) and self._IMPERATIVE_PROMPT_RE.match(normalized):
            return True

        return False
