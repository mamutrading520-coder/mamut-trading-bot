"""Smoke tests for main functionality"""
import pytest

def test_imports():
    """Test that main modules can be imported"""
    from config.settings import Settings
    from core.orchestrator import Orchestrator
    assert Settings is not None
    assert Orchestrator is not None
