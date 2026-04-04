"""Discovery deduplication guard for early Pump.fun token floods."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

from monitoring.logger import setup_logger
from utils.time_utils import get_timestamp

logger = setup_logger("DiscoveryDeduper")


class DiscoveryDeduper:
    """Deduplicates semantically identical discovery events within a short window."""

    def __init__(self, settings=None):
        self.window = int(getattr(settings, "discovery_dedup_window", 180) or 180)
        self.max_tracked = int(getattr(settings, "discovery_dedup_max_tracked", 5000) or 5000)
        self.initial_sol_tolerance = float(
            getattr(settings, "discovery_dedup_initial_sol_tolerance", 0.002) or 0.002
        )

        self.recent_mints: Dict[str, float] = {}
        self.recent_signatures: Dict[str, float] = {}
        self.semantic_keys: Dict[Tuple[str, ...], Dict[str, Any]] = {}

        self.duplicate_count = 0
        self.unique_count = 0

    @staticmethod
    def _normalize_text(value: Any) -> str:
        if value is None:
            return ""
        text = str(value).strip().lower()
        text = re.sub(r"[^a-z0-9]+", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    @staticmethod
    def _normalize_creator(value: Any) -> str:
        if value is None:
            return ""
        creator = str(value).strip()
        if creator.lower() in {"", "unknown"}:
            return ""
        return creator

    def _normalize_initial_sol_bucket(self, value: Any) -> Optional[str]:
        try:
            initial_sol = float(value or 0.0)
        except (TypeError, ValueError):
            return None

        if initial_sol <= 0:
            return None

        bucket = round(initial_sol / max(self.initial_sol_tolerance, 0.0001))
        return str(bucket)

    def _semantic_fingerprints(self, token_data: Dict[str, Any]) -> Tuple[Tuple[str, ...], ...]:
        creator = self._normalize_creator(token_data.get("creator"))
        if not creator:
            return tuple()

        name = self._normalize_text(token_data.get("name"))
        symbol = self._normalize_text(token_data.get("symbol"))
        uri = str(token_data.get("uri") or "").strip().lower()
        initial_sol_bucket = self._normalize_initial_sol_bucket(token_data.get("initial_sol"))

        keys = []

        if name and symbol:
            keys.append(("creator_name_symbol", creator, name, symbol))

        if uri and name:
            keys.append(("creator_uri_name", creator, uri, name))

        if name and symbol and initial_sol_bucket:
            keys.append(("creator_name_symbol_sol", creator, name, symbol, initial_sol_bucket))

        return tuple(keys)

    def _evict_if_needed(self) -> None:
        while len(self.semantic_keys) > self.max_tracked:
            oldest_key = min(
                self.semantic_keys,
                key=lambda item: self.semantic_keys[item].get("timestamp", float("inf")),
            )
            self.semantic_keys.pop(oldest_key, None)

        while len(self.recent_mints) > self.max_tracked:
            oldest_key = min(self.recent_mints, key=self.recent_mints.get)
            self.recent_mints.pop(oldest_key, None)

        while len(self.recent_signatures) > self.max_tracked:
            oldest_key = min(self.recent_signatures, key=self.recent_signatures.get)
            self.recent_signatures.pop(oldest_key, None)

    def check_and_register(self, token_data: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """Return (is_duplicate, reason)."""
        try:
            current_time = float(get_timestamp())
            mint = str(token_data.get("mint") or "").strip()
            signature = str(token_data.get("signature") or token_data.get("tx_signature") or "").strip()

            if mint and mint in self.recent_mints and current_time - self.recent_mints[mint] <= self.window:
                self.duplicate_count += 1
                return True, "duplicate_mint"

            if signature and signature in self.recent_signatures and current_time - self.recent_signatures[signature] <= self.window:
                self.duplicate_count += 1
                return True, "duplicate_signature"

            semantic_keys = self._semantic_fingerprints(token_data)
            for key in semantic_keys:
                previous = self.semantic_keys.get(key)
                if not previous:
                    continue
                elapsed = current_time - float(previous.get("timestamp", 0.0) or 0.0)
                if elapsed <= self.window:
                    self.duplicate_count += 1
                    return True, f"semantic_duplicate:{key[0]}"

            if mint:
                self.recent_mints[mint] = current_time
            if signature:
                self.recent_signatures[signature] = current_time

            representative = {
                "timestamp": current_time,
                "mint": mint,
                "signature": signature,
                "symbol": token_data.get("symbol"),
                "name": token_data.get("name"),
                "creator": token_data.get("creator"),
            }
            for key in semantic_keys:
                self.semantic_keys[key] = representative

            self.unique_count += 1
            self._evict_if_needed()
            return False, None

        except Exception as e:
            logger.error(f"Error checking discovery duplicate: {e}")
            return False, None

    def cleanup_old_entries(self) -> int:
        try:
            current_time = float(get_timestamp())
            removed = 0

            old_mints = [mint for mint, ts in self.recent_mints.items() if current_time - ts > self.window]
            for mint in old_mints:
                self.recent_mints.pop(mint, None)
                removed += 1

            old_sigs = [sig for sig, ts in self.recent_signatures.items() if current_time - ts > self.window]
            for sig in old_sigs:
                self.recent_signatures.pop(sig, None)
                removed += 1

            old_semantic = [
                key
                for key, payload in self.semantic_keys.items()
                if current_time - float(payload.get("timestamp", 0.0) or 0.0) > self.window
            ]
            for key in old_semantic:
                self.semantic_keys.pop(key, None)
                removed += 1

            return removed

        except Exception as e:
            logger.error(f"Error cleaning discovery deduper: {e}")
            return 0

    def get_stats(self) -> Dict[str, Any]:
        total = self.unique_count + self.duplicate_count
        return {
            "unique_discoveries": self.unique_count,
            "deduped_discoveries": self.duplicate_count,
            "dedup_rate": self.duplicate_count / total if total > 0 else 0,
            "tracked_mints": len(self.recent_mints),
            "tracked_signatures": len(self.recent_signatures),
            "tracked_semantic_keys": len(self.semantic_keys),
            "window_seconds": self.window,
        }
