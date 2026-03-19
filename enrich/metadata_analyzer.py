import re
from typing import Any, Dict, List
from loguru import logger


class MetadataAnalyzer:
    """
    Basic metadata analyzer for early-stage token signal enrichment.

    This module does not attempt to prove legitimacy. It only extracts
    useful heuristics from name, symbol, description and URLs so the
    scoring/filter layers can make better decisions.
    """

    SUSPICIOUS_KEYWORDS = {
        "guaranteed",
        "100x",
        "1000x",
        "moonshot",
        "send sol",
        "double your money",
        "profit",
        "airdrop now",
        "instant gains",
        "presale now",
        "locked profits",
        "free money",
    }

    POSITIVE_KEYWORDS = {
        "website",
        "docs",
        "telegram",
        "twitter",
        "community",
        "roadmap",
        "launch",
        "fair launch",
        "lp locked",
        "renounced",
        "utility",
        "bot",
        "trading",
        "analytics",
    }

    URL_REGEX = re.compile(r"https?://[^\s]+", re.IGNORECASE)
    HANDLE_REGEX = re.compile(r"@[A-Za-z0-9_]{2,32}")
    EMOJI_HEAVY_REGEX = re.compile(r"[\U00010000-\U0010ffff]", re.UNICODE)

    def __init__(self) -> None:
        logger.debug("MetadataAnalyzer initialized")

    async def analyze(self, token_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze token metadata and return normalized heuristic signals.

        Expected token_data keys may include:
        - name
        - symbol
        - description
        - website
        - twitter
        - telegram
        """
        try:
            name = self._safe_text(token_data.get("name"))
            symbol = self._safe_text(token_data.get("symbol"))
            description = self._safe_text(token_data.get("description"))
            website = self._safe_text(token_data.get("website"))
            twitter = self._safe_text(token_data.get("twitter"))
            telegram = self._safe_text(token_data.get("telegram"))

            combined_text = " ".join(
                part for part in [name, symbol, description, website, twitter, telegram] if part
            ).strip()

            urls_found = self.URL_REGEX.findall(combined_text)
            handles_found = self.HANDLE_REGEX.findall(combined_text)

            suspicious_matches = self._find_keywords(
                combined_text, self.SUSPICIOUS_KEYWORDS
            )
            positive_matches = self._find_keywords(
                combined_text, self.POSITIVE_KEYWORDS
            )

            has_website = bool(website) or any("http" in u.lower() for u in urls_found)
            has_twitter = bool(twitter) or "twitter.com" in combined_text.lower() or "x.com" in combined_text.lower()
            has_telegram = bool(telegram) or "t.me/" in combined_text.lower()

            symbol_quality = self._score_symbol_quality(symbol)
            name_quality = self._score_name_quality(name)
            description_quality = self._score_description_quality(description)

            social_count = sum([has_website, has_twitter, has_telegram])

            metadata_score = (
                symbol_quality
                + name_quality
                + description_quality
                + (social_count * 10)
                + min(len(positive_matches) * 4, 12)
                - min(len(suspicious_matches) * 8, 24)
            )

            metadata_score = max(0, min(100, metadata_score))

            risk_flags: List[str] = []
            if not name:
                risk_flags.append("missing_name")
            if not symbol:
                risk_flags.append("missing_symbol")
            if not description:
                risk_flags.append("missing_description")
            if social_count == 0:
                risk_flags.append("no_social_links")
            if suspicious_matches:
                risk_flags.append("suspicious_marketing_language")
            if self._is_emoji_heavy(name + " " + description):
                risk_flags.append("emoji_heavy_metadata")

            result = {
                "metadata_score": float(metadata_score),
                "has_website": has_website,
                "has_twitter": has_twitter,
                "has_telegram": has_telegram,
                "social_count": social_count,
                "urls_found": urls_found,
                "handles_found": handles_found,
                "suspicious_matches": suspicious_matches,
                "positive_matches": positive_matches,
                "symbol_quality": symbol_quality,
                "name_quality": name_quality,
                "description_quality": description_quality,
                "risk_flags": risk_flags,
                "metadata_summary": self._build_summary(
                    metadata_score=metadata_score,
                    social_count=social_count,
                    suspicious_matches=suspicious_matches,
                    positive_matches=positive_matches,
                ),
            }

            logger.debug(
                f"Metadata analyzed for {symbol or 'UNKNOWN'} | "
                f"score={metadata_score} | flags={risk_flags}"
            )
            return result

        except Exception as e:
            logger.error(f"Metadata analysis failed: {e}")
            return {
                "metadata_score": 0.0,
                "has_website": False,
                "has_twitter": False,
                "has_telegram": False,
                "social_count": 0,
                "urls_found": [],
                "handles_found": [],
                "suspicious_matches": [],
                "positive_matches": [],
                "symbol_quality": 0,
                "name_quality": 0,
                "description_quality": 0,
                "risk_flags": ["metadata_analysis_error"],
                "metadata_summary": "metadata analysis failed",
            }

    def _safe_text(self, value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()

    def _find_keywords(self, text: str, keywords: set) -> List[str]:
        lowered = text.lower()
        return sorted([kw for kw in keywords if kw in lowered])

    def _score_symbol_quality(self, symbol: str) -> int:
        if not symbol:
            return 0
        score = 10
        if 2 <= len(symbol) <= 10:
            score += 15
        if symbol.isupper():
            score += 10
        if re.fullmatch(r"[A-Z0-9]+", symbol):
            score += 10
        if len(set(symbol)) == 1:
            score -= 10
        return max(0, min(30, score))

    def _score_name_quality(self, name: str) -> int:
        if not name:
            return 0
        score = 10
        if 3 <= len(name) <= 32:
            score += 10
        if re.search(r"[A-Za-z]", name):
            score += 5
        if len(name.split()) <= 5:
            score += 5
        return max(0, min(20, score))

    def _score_description_quality(self, description: str) -> int:
        if not description:
            return 0
        score = 5
        if len(description) >= 20:
            score += 5
        if len(description) >= 60:
            score += 5
        if len(description.split()) >= 6:
            score += 5
        return max(0, min(20, score))

    def _is_emoji_heavy(self, text: str) -> bool:
        if not text:
            return False
        emojis = self.EMOJI_HEAVY_REGEX.findall(text)
        return len(emojis) >= 6

    def _build_summary(
        self,
        metadata_score: float,
        social_count: int,
        suspicious_matches: List[str],
        positive_matches: List[str],
    ) -> str:
        parts = [f"metadata_score={int(metadata_score)}", f"socials={social_count}"]
        if positive_matches:
            parts.append(f"positive={','.join(positive_matches[:3])}")
        if suspicious_matches:
            parts.append(f"suspicious={','.join(suspicious_matches[:3])}")
        return " | ".join(parts)
