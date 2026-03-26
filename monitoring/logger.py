"""Logging configuration for Mamut engine using loguru"""
import sys
from pathlib import Path
from loguru import logger
from typing import Optional

class MamutLogger:
    """Centralized logger configuration for Mamut"""
    
    _instance: Optional['MamutLogger'] = None
    _initialized: bool = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self._setup_logger()
            MamutLogger._initialized = True
    
    @staticmethod
    def _setup_logger():
        """Configure loguru with file and console handlers"""
        
        # Remove default handler
        logger.remove()
        
        # Console handler - INFO level
        logger.add(
            sys.stderr,
            format="<level>{time:YYYY-MM-DD HH:mm:ss.SSS}</level> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
            level="INFO",
            colorize=True,
        )
        
        # File handler - DEBUG level
        log_file = Path("logs/mamut.log")
        log_file.parent.mkdir(exist_ok=True)
        
        logger.add(
            str(log_file),
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
            level="DEBUG",
            rotation="500 MB",
            retention="7 days",
            compression="zip",
        )
        
        # Error file handler
        error_file = Path("logs/mamut_error.log")
        error_file.parent.mkdir(exist_ok=True)
        
        logger.add(
            str(error_file),
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
            level="ERROR",
            rotation="500 MB",
            retention="30 days",
        )
    
    @staticmethod
    def get_logger(name: str):
        """Get logger instance for a module"""
        return logger.bind(module=name)

def setup_logger(name: str) -> object:
    """Setup and return logger for a specific module"""
    MamutLogger()
    return MamutLogger.get_logger(name)

# Module-level logger
logger_instance = MamutLogger()