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
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "mint": self.mint,
            "name": self.name,
            "symbol": self.symbol,
            "creator": self.creator,
            "signature": self.signature,
            "initial_sol": self.initial_sol,
            "market_cap_sol": self.market_cap_sol,
            "uri": self.uri,
        }


class PumpEventParser:
    """Parses Pump.fun WebSocket events"""
    
    def parse(self, data: Dict[str, Any]) -> Optional[ParsedTokenEvent]:
        """Parse token creation event"""
        try:
            # Extract basic fields
            mint = data.get("mint")
            signature = data.get("signature")
            name = data.get("name", "UNKNOWN")
            symbol = data.get("symbol", "UNKNOWN")
            creator = data.get("creator", "UNKNOWN")
            uri = data.get("uri", "")
            
            # Validate required fields
            if not mint or not signature:
                logger.warning(f"Missing mint or signature")
                return None
            
            # Extract initial SOL (can be in different formats)
            initial_sol = 0.0
            if "initialBuy" in data:
                initial_sol = float(data.get("initialBuy", 0)) / 1e9  # Convert from lamports
            elif "initial_sol" in data:
                initial_sol = float(data.get("initial_sol", 0))
            
            # Extract market cap
            market_cap_sol = 0.0
            if "bondingCurveKey" in data:
                # Try to calculate from bonding curve data
                market_cap_sol = float(data.get("market_cap_sol", 0))
            
            # Validate symbol and name
            if not symbol or symbol == "UNKNOWN" or len(symbol) == 0:
                logger.debug(f"Invalid symbol: {symbol}")
                return None
            
            if not name or name == "UNKNOWN" or len(name) == 0:
                logger.debug(f"Invalid name: {name}")
                return None
            
            # Create parsed event
            parsed = ParsedTokenEvent(
                mint=mint,
                name=name,
                symbol=symbol,
                creator=creator if creator and creator != "UNKNOWN" else "unknown",
                signature=signature,
                initial_sol=initial_sol,
                market_cap_sol=market_cap_sol,
                uri=uri,
            )
            
            logger.info(f"✓ Parsed: {symbol} | SOL: {initial_sol:.4f} | Creator: {creator[:8]}...")
            return parsed
            
        except Exception as e:
            logger.warning(f"Parse error: {e}")
            return None