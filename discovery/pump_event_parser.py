"""Parser for Pump.fun token events"""
from typing import Optional, Dict, Any
from dataclasses import dataclass
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
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "mint": self.mint,
            "name": self.name,
            "symbol": self.symbol,
            "creator": self.creator,
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
    
    def parse(self, data: Dict[str, Any]) -> Optional[ParsedTokenEvent]:
        """Parse token creation event"""
        try:
            # Extract basic fields
            mint = data.get("mint")
            signature = data.get("signature")
            name = data.get("name") or "UNKNOWN"
            symbol = data.get("symbol") or "UNKNOWN"
            creator = data.get("traderPublicKey") or data.get("creator") or "UNKNOWN"
            uri = data.get("uri", "")
            timestamp = int(data.get("createdTimestamp") or data.get("timestamp") or 0)
            bonding_curve = data.get("bondingCurveKey") or data.get("bonding_curve") or ""
            
            # Validate required fields
            if not mint or not signature:
                logger.warning("Missing mint or signature")
                return None
            
            # Extract initial buy in lamports and initial SOL
            initial_buy = int(data.get("initialBuy") or 0)
            if initial_buy > 0:
                initial_sol = initial_buy / 1e9
            elif "initial_sol" in data:
                initial_sol = float(data.get("initial_sol") or 0)
            else:
                initial_sol = 0.0
            
            # Extract bonding curve virtual reserves
            v_tokens_in_bonding_curve = int(data.get("vTokensInBondingCurve") or
                                            data.get("v_tokens_in_bonding_curve") or 0)
            v_sol_raw = data.get("vSolInBondingCurve") or data.get("v_sol_in_bonding_curve") or 0
            v_sol_in_bonding_curve = float(v_sol_raw) / 1e9 if v_sol_raw else 0.0

            # Calculate market cap from bonding curve virtual reserves when available
            market_cap_sol = float(data.get("market_cap_sol") or 0)
            if market_cap_sol == 0.0 and v_tokens_in_bonding_curve > 0 and v_sol_raw:
                # pump.fun tokens have 6 decimals and 1B total supply.
                # price_per_token (SOL) = v_sol_lamports / (v_tokens_raw / 1e6) / 1e9
                #                      = v_sol_lamports / (v_tokens_raw * 1e3)
                # market_cap_sol = price_per_token * 1_000_000_000
                #                = v_sol_lamports * 1_000_000 / v_tokens_raw
                market_cap_sol = float(v_sol_raw) * 1_000_000 / v_tokens_in_bonding_curve
            
            # Validate symbol and name — tokens with "UNKNOWN" values are allowed through
            if not symbol or not symbol.strip():
                logger.debug(f"Invalid symbol: {symbol!r}")
                return None
            
            if not name or not name.strip():
                logger.debug(f"Invalid name: {name!r}")
                return None
            
            # Create parsed event
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
            )
            
            creator_display = creator[:8] if len(creator) >= 8 else creator
            logger.info(f"✓ Parsed: {symbol} | SOL: {initial_sol:.4f} | Creator: {creator_display}...")
            return parsed
            
        except Exception as e:
            logger.warning(f"Parse error: {e}")
            return None