"""Detect suspicious / honeypot-like token patterns for Solana tokens"""

from __future__ import annotations

from typing import Dict, Any, List

from monitoring.logger import setup_logger

logger = setup_logger("HoneypotDetector")


class HoneypotDetector:
    """
    Detecta señales de alto riesgo en tokens Solana.

    No intenta afirmar un honeypot “estricto” estilo EVM.
    Evalúa si el token parece manipulable, congelable, poco confiable
    o con demasiadas banderas como para tratarlo como oportunidad seria.
    """

    def __init__(self, settings=None):
        self.settings = settings
        self.analyzed_count = 0
        self.suspicious_count = 0

    async def analyze(self, token_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze token for suspicious / honeypot-like characteristics.

        Expected input can include:
        - mint_authority
        - freeze_authority
        - owner_renounced
        - total_supply
        - metadata_score
        - metadata_risk_flags
        - creator_tokens_created / creator_failure_rate / creator_success_rate
        - top_holder_ratio / holder_concentration / wallet_cluster_score
        """
        try:
            self.analyzed_count += 1

            reasons: List[str] = []
            warnings: List[str] = []
            penalties: List[float] = []

            mint_authority = token_data.get("mint_authority")
            freeze_authority = token_data.get("freeze_authority")
            owner_renounced = bool(token_data.get("owner_renounced", False))
            total_supply = int(token_data.get("total_supply", 0) or 0)

            metadata_score = float(token_data.get("metadata_score", 0.0) or 0.0)
            metadata_flags = list(token_data.get("metadata_risk_flags", []) or [])

            creator_failure_rate = float(token_data.get("creator_failure_rate", 0.0) or 0.0)
            creator_success_rate = float(token_data.get("creator_success_rate", 0.0) or 0.0)
            creator_tokens_created = int(token_data.get("creator_tokens_created", 0) or 0)

            top_holder_ratio = float(token_data.get("top_holder_ratio", 0.0) or 0.0)
            holder_concentration = float(token_data.get("holder_concentration", 0.0) or 0.0)
            wallet_cluster_score = float(token_data.get("wallet_cluster_score", 0.0) or 0.0)

            # 1) Authorities
            if freeze_authority:
                reasons.append("Freeze authority activa")
                penalties.append(30.0)

            if mint_authority:
                reasons.append("Mint authority activa")
                penalties.append(20.0)

            if not owner_renounced:
                warnings.append("Owner no renounced")
                penalties.append(10.0)

            # 2) Supply sanity
            if total_supply <= 0:
                reasons.append("Supply inválido o no disponible")
                penalties.append(20.0)
            elif total_supply < 1_000:
                warnings.append("Supply extremadamente bajo")
                penalties.append(5.0)

            # 3) Metadata quality
            if metadata_score < 20:
                reasons.append("Metadata muy pobre o sospechosa")
                penalties.append(20.0)
            elif metadata_score < 40:
                warnings.append("Metadata débil")
                penalties.append(10.0)

            suspicious_metadata_flags = {
                "suspicious_name",
                "suspicious_symbol",
                "missing_description",
                "missing_socials",
                "suspicious_links",
                "spam_language",
            }

            flagged = suspicious_metadata_flags.intersection(set(metadata_flags))
            if flagged:
                warnings.append(f"Flags metadata: {', '.join(sorted(flagged))}")
                penalties.append(min(len(flagged) * 4.0, 16.0))

            # 4) Creator behavior
            if creator_tokens_created >= 5 and creator_failure_rate >= 0.80:
                reasons.append("Creador con historial muy negativo")
                penalties.append(20.0)
            elif creator_tokens_created >= 3 and creator_success_rate <= 0.10:
                warnings.append("Creador con baja tasa histórica de éxito")
                penalties.append(10.0)

            # 5) Concentration / clustering
            if top_holder_ratio >= 0.50:
                reasons.append("Top holder concentration extrema")
                penalties.append(25.0)
            elif top_holder_ratio >= 0.25:
                warnings.append("Top holder concentration alta")
                penalties.append(12.0)

            if holder_concentration >= 0.80:
                reasons.append("Holder concentration extrema")
                penalties.append(20.0)
            elif holder_concentration >= 0.60:
                warnings.append("Holder concentration elevada")
                penalties.append(10.0)

            if wallet_cluster_score >= 0.80:
                reasons.append("Wallet clustering sospechoso")
                penalties.append(15.0)
            elif wallet_cluster_score >= 0.60:
                warnings.append("Posible clustering de wallets")
                penalties.append(8.0)

            risk_score = min(round(sum(penalties), 2), 100.0)

            if risk_score >= 70:
                risk_level = "critical"
            elif risk_score >= 45:
                risk_level = "high"
            elif risk_score >= 25:
                risk_level = "medium"
            else:
                risk_level = "low"

            is_suspicious = risk_score >= 45 or len(reasons) >= 2

            if is_suspicious:
                self.suspicious_count += 1

            result = {
                "is_suspicious": is_suspicious,
                "risk_level": risk_level,
                "risk_score": risk_score,
                "score_penalty": risk_score,
                "reasons": reasons,
                "warnings": warnings,
                "checks": {
                    "freeze_authority_active": bool(freeze_authority),
                    "mint_authority_active": bool(mint_authority),
                    "owner_renounced": owner_renounced,
                    "metadata_score": metadata_score,
                    "metadata_flag_count": len(metadata_flags),
                    "creator_tokens_created": creator_tokens_created,
                    "creator_failure_rate": creator_failure_rate,
                    "creator_success_rate": creator_success_rate,
                    "top_holder_ratio": top_holder_ratio,
                    "holder_concentration": holder_concentration,
                    "wallet_cluster_score": wallet_cluster_score,
                },
            }

            logger.debug(
                f"Honeypot analysis completed | suspicious={is_suspicious} "
                f"| risk_score={risk_score}"
            )
            return result

        except Exception as e:
            logger.error(f"Error analyzing honeypot risk: {e}")
            return {
                "is_suspicious": True,
                "risk_level": "critical",
                "risk_score": 100.0,
                "score_penalty": 100.0,
                "reasons": [f"Detector error: {e}"],
                "warnings": [],
                "checks": {},
            }

    def get_stats(self) -> dict:
        total = self.analyzed_count
        return {
            "analyzed_count": total,
            "suspicious_count": self.suspicious_count,
            "suspicious_rate": self.suspicious_count / total if total > 0 else 0,
        }
