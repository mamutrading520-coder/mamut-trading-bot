"""Format signals for output and distribution"""
from typing import Dict, Any, Optional
from datetime import datetime
from monitoring.logger import setup_logger
import json

logger = setup_logger("SignalFormatter")

class SignalFormatter:
    """Formats signals for output to various channels"""
    
    def __init__(self):
        self.formatted_count = 0
    
    def _format_json(self, signal: Dict[str, Any]) -> str:
        """Format signal as JSON"""
        try:
            return json.dumps(signal, indent=2, default=str)
        except Exception as e:
            logger.error(f"Error formatting JSON: {e}")
            return "{}"
    
    def _format_text(self, signal: Dict[str, Any]) -> str:
        """Format signal as plain text"""
        try:
            lines = [
                "=" * 70,
                f"SIGNAL: {signal.get('signal_type', 'UNKNOWN')}",
                "=" * 70,
                f"Signal ID:    {signal.get('signal_id')}",
                f"Token:        {signal.get('symbol')} ({signal.get('mint', '')[:8]}...)",
                f"Score:        {signal.get('score', 0):.1f}/100",
                f"Confidence:   {signal.get('confidence', 0):.1%}",
                f"Risk Level:   {signal.get('risk_level')}",
                f"Reason:       {signal.get('reason')}",
                "",
                "Metadata:",
                f"  Name:       {signal.get('metadata', {}).get('token_name')}",
                f"  Creator:    {signal.get('metadata', {}).get('creator', '')[:8]}...",
                f"  Initial SOL: {signal.get('metadata', {}).get('initial_sol', 0):.4f}",
                f"  Market Cap:  {signal.get('metadata', {}).get('market_cap_sol', 0):.4f} SOL",
            ]
            
            # Add component scores if available
            components = signal.get('metadata', {}).get('component_scores', {})
            if components:
                lines.append("")
                lines.append("Component Scores:")
                for component, score in components.items():
                    lines.append(f"  {component}: {score:.1f}")
            
            # Add flow data if available
            flow = signal.get('metadata', {}).get('flow', {})
            if flow:
                lines.append("")
                lines.append("Flow Analysis:")
                lines.append(f"  Flow Score:     {flow.get('flow_score', 0):.1f}")
                lines.append(f"  Momentum Score: {flow.get('momentum_score', 0):.1f}")
                lines.append(f"  Velocity Score: {flow.get('velocity_score', 0):.1f}")
                if flow.get('patterns'):
                    lines.append(f"  Patterns:       {', '.join(flow['patterns'])}")
            
            # Add buyer data if available
            buyers = signal.get('metadata', {}).get('buyers', {})
            if buyers:
                lines.append("")
                lines.append("Buyer Analysis:")
                lines.append(f"  Quality Score: {buyers.get('quality_score', 0):.1f}")
                lines.append(f"  Quality Level: {buyers.get('quality_level', 'UNKNOWN')}")
                lines.append(f"  Unique Buyers: {buyers.get('unique_buyers', 0)}")
            
            lines.extend([
                "",
                f"Timestamp: {signal.get('timestamp')}",
                "=" * 70,
            ])
            
            return "\n".join(lines)
            
        except Exception as e:
            logger.error(f"Error formatting text: {e}")
            return "Error formatting signal"
    
    def _format_webhook(self, signal: Dict[str, Any]) -> Dict[str, Any]:
        """Format signal for webhook delivery"""
        try:
            return {
                "type": "mamut_signal",
                "signal_id": signal.get("signal_id"),
                "signal_type": signal.get("signal_type"),
                "token": {
                    "mint": signal.get("mint"),
                    "symbol": signal.get("symbol"),
                    "name": signal.get("metadata", {}).get("token_name"),
                },
                "score": {
                    "final": signal.get("score"),
                    "confidence": signal.get("confidence"),
                    "risk_level": signal.get("risk_level"),
                },
                "analysis": signal.get("metadata", {}),
                "reason": signal.get("reason"),
                "timestamp": signal.get("timestamp"),
            }
        except Exception as e:
            logger.error(f"Error formatting webhook: {e}")
            return {}
    
    def _format_discord(self, signal: Dict[str, Any]) -> Dict[str, Any]:
        """Format signal for Discord webhook"""
        try:
            color_map = {
                "EARLY": 0x00FF00,  # Green
                "CONFIRMATION": 0x0099FF,  # Blue
                "ABANDON": 0xFF0000,  # Red
            }
            
            color = color_map.get(signal.get("signal_type"), 0xFFFFFF)
            
            embed = {
                "title": f"🚀 {signal.get('signal_type')} - {signal.get('symbol')}",
                "color": color,
                "fields": [
                    {
                        "name": "Score",
                        "value": f"{signal.get('score', 0):.1f}/100",
                        "inline": True
                    },
                    {
                        "name": "Confidence",
                        "value": f"{signal.get('confidence', 0):.1%}",
                        "inline": True
                    },
                    {
                        "name": "Risk Level",
                        "value": signal.get("risk_level"),
                        "inline": True
                    },
                    {
                        "name": "Reason",
                        "value": signal.get("reason"),
                        "inline": False
                    },
                    {
                        "name": "Mint",
                        "value": f"`{signal.get('mint')}`",
                        "inline": False
                    },
                ],
                "footer": {
                    "text": f"Signal ID: {signal.get('signal_id')}"
                },
                "timestamp": signal.get("timestamp"),
            }
            
            return {"embeds": [embed]}
            
        except Exception as e:
            logger.error(f"Error formatting Discord: {e}")
            return {}
    
    def format(
        self,
        signal: Dict[str, Any],
        format_type: str = "json"
    ) -> Any:
        """
        Format signal for specified output type
        
        Args:
            signal: Signal data
            format_type: Output format (json, text, webhook, discord)
            
        Returns:
            Formatted signal
        """
        try:
            self.formatted_count += 1
            
            if format_type == "json":
                return self._format_json(signal)
            elif format_type == "text":
                return self._format_text(signal)
            elif format_type == "webhook":
                return self._format_webhook(signal)
            elif format_type == "discord":
                return self._format_discord(signal)
            else:
                logger.warning(f"Unknown format type: {format_type}")
                return self._format_json(signal)
            
        except Exception as e:
            logger.error(f"Error formatting signal: {e}")
            return None
    
    def get_stats(self) -> dict:
        """Get formatter statistics"""
        return {
            "formatted_count": self.formatted_count,
        }