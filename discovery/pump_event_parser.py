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
    _COMMAND_PREFIX_RE = re.compile(r"^\s*[/!#.]+\s*[a-zA-Z]", re.IGNORECASE)
    _COMMAND_WITH_AMOUNT_RE = re.compile(
        r"^\s*[/!]?\s*(buy|sell|swap|ape|long|short|tp|sl)\b.*\b\d+(?:\.\d+)?\b",
        re.IGNORECASE,
    )
    _PAIR_OR_ACTION_RE = re.compile(
        r"\b(?:buy|sell|swap|ape|long|short|tp|sl)\b.*\b(?:sol|usd|usdc|usdt)\b",
        re.IGNORECASE,
    )
    _MENTION_RE = re.compile(r"(?:@everyone|@here|<@&?)", re.IGNORECASE)

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

            if not self._is_valid_metadata_text(name, kind="name"):
                logger.info(f"Rejected parser garbage token name: {raw_name!r}")
                return None

            if not self._is_valid_metadata_text(symbol, kind="symbol"):
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

    def _is_valid_metadata_text(self, value: str, kind: str) -> bool:
        if not value or not value.strip():
            logger.debug(f"Invalid {kind}: empty")
            return False

        min_len = TOKEN_METADATA_THRESHOLDS.get(f"min_{kind}_length", 1)
        max_len = TOKEN_METADATA_THRESHOLDS.get(f"max_{kind}_length", 100)
        if len(value) < min_len or len(value) > max_len:
            logger.debug(f"Invalid {kind}: length out of range ({len(value)})")
            return False

        if self._looks_like_parser_garbage(value):
            logger.debug(f"Invalid {kind}: command/prompt-like garbage detected: {value!r}")
            return False

        return True

    def _looks_like_parser_garbage(self, value: str) -> bool:
        normalized = value.strip()
        lowered = normalized.lower()

        if self._URL_LIKE_RE.search(normalized):
            return True

        if self._MENTION_RE.search(normalized):
            return True

        if self._COMMAND_PREFIX_RE.match(normalized):
            return True

        if self._COMMAND_WITH_AMOUNT_RE.match(normalized):
            return True

        if self._PAIR_OR_ACTION_RE.search(normalized) and ("/" in normalized or any(ch.isdigit() for ch in normalized)):
            return True

        if lowered.startswith(("buy ", "sell ", "swap ", "ape ")) and any(ch.isdigit() for ch in lowered):
            return True

        if normalized.count("/") >= 2 or normalized.count("\\") >= 2:
            return True

        non_alnum_ratio = sum(1 for ch in normalized if not ch.isalnum() and ch != " ") / max(len(normalized), 1)
        if len(normalized) >= 8 and non_alnum_ratio > 0.35:
            return True

        return False
