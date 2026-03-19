"""Score calculation and weighting logic"""
from typing import Dict, Any

# Score weights for different components
SCORE_WEIGHTS = {
    "authority_risk": 0.15,      # 15% - less weight (limited variance from pump.fun data)
    "creator_risk": 0.30,         # 30% - strongest predictor
    "concentration_risk": 0.25,   # 25% - critical for quality
    "flow_score": 0.20,          # 20% - maintained (now improved)
    "holder_quality": 0.10,      # 10% - less weight (limited early data)
}

# Risk level thresholds
RISK_THRESHOLDS = {
    "high_potential": 65,         # Score >= 65: HIGH_POTENTIAL
    "medium_potential": 50,       # Score 50-64: MEDIUM_POTENTIAL
    "low_potential": 20,          # Score 20-49: LOW_POTENTIAL
    "trash": 0,                   # Score < 20: TRASH
}

# Risk level thresholds (alternative name used by decision_mapper)
RISK_LEVEL_THRESHOLDS = {
    "HIGH_POTENTIAL": 65,
    "MEDIUM_POTENTIAL": 50,
    "LOW_POTENTIAL": 20,
    "TRASH": 0,
}

# Score metadata for display
SCORE_METADATA = {
    "high_potential": {
        "display_name": "HIGH_POTENTIAL",
        "color": "green",
        "emoji": "🟢",
        "description": "High quality token with good potential",
        "action": "SIGNAL_EARLY",
    },
    "medium_potential": {
        "display_name": "MEDIUM_POTENTIAL",
        "color": "yellow",
        "emoji": "🟡",
        "description": "Moderate quality token, worth monitoring",
        "action": "MONITOR",
    },
    "low_potential": {
        "display_name": "LOW_POTENTIAL",
        "color": "orange",
        "emoji": "🟠",
        "description": "Low quality token, high risk",
        "action": "WARN",
    },
    "trash": {
        "display_name": "TRASH",
        "color": "red",
        "emoji": "🔴",
        "description": "Likely scam or rug pull",
        "action": "REJECT",
    },
}

def combine_scores(
    authority_risk: float,
    creator_risk: float,
    holder_quality: float,
    concentration: float,
    flow_score: float,
) -> float:
    """
    Combine individual scores into final score

    Args:
        authority_risk: Authority risk score (0-100, lower is better)
        creator_risk: Creator risk score (0-100, lower is better)
        holder_quality: Holder quality score (0-100, higher is better)
        concentration: Concentration risk score (0-100, lower is better)
        flow_score: Flow quality score (0-100, higher is better)

    Returns:
        Final combined score (0-100, higher is better)
    """
    try:
        # Invert risk scores (higher is better)
        authority_score = 100 - authority_risk
        creator_score = 100 - creator_risk
        concentration_score = 100 - concentration

        # Combine with weights
        final_score = (
            authority_score * SCORE_WEIGHTS["authority_risk"] +
            creator_score * SCORE_WEIGHTS["creator_risk"] +
            concentration_score * SCORE_WEIGHTS["concentration_risk"] +
            flow_score * SCORE_WEIGHTS["flow_score"] +
            holder_quality * SCORE_WEIGHTS["holder_quality"]
        )

        # Clamp to 0-100
        return max(0.0, min(100.0, final_score))

    except Exception as e:
        return 50.0  # Default middle score on error


def get_risk_level(score: float) -> str:
    """
    Get risk level from score

    Args:
        score: Final score (0-100)

    Returns:
        Risk level string
    """
    if score >= RISK_THRESHOLDS["high_potential"]:
        return "HIGH_POTENTIAL"
    elif score >= RISK_THRESHOLDS["medium_potential"]:
        return "MEDIUM_POTENTIAL"
    elif score >= RISK_THRESHOLDS["low_potential"]:
        return "LOW_POTENTIAL"
    else:
        return "TRASH"


def get_confidence(score: float) -> float:
    """
    Get confidence level from score

    Args:
        score: Final score (0-100)

    Returns:
        Confidence (0-1)
    """
    # Higher score = higher confidence
    return score / 100.0


def get_score_metadata(risk_level: str) -> Dict[str, Any]:
    """
    Get metadata for risk level

    Args:
        risk_level: Risk level string

    Returns:
        Metadata dictionary
    """
    return SCORE_METADATA.get(risk_level.lower(), SCORE_METADATA["trash"])