# Mamut 🦣

Advanced Token Analysis & Trading Signals Engine for Solana Blockchain

A sophisticated system for discovering, analyzing, and tracking emerging tokens on Solana with real-time risk assessment and signal generation.

## Features

- 🔍 Real-time Token Discovery - Monitor pump.fun and Raydium launches
- 📊 Advanced Analytics - Momentum, flow, and velocity analysis
- ⚠️ Multi-layer Filtering - Honeypot detection, concentration checks, creator profiling
- 📈 Risk Scoring - Comprehensive risk assessment with weighted factors
- 🚨 Signal Generation - Actionable trading signals with confidence levels
- 📝 Event Bus Architecture - Decoupled, scalable event processing
- 💾 State Management - Persistent storage with SQLite
- 📊 Monitoring & Logging - Comprehensive observability

## Quick Start

1. Clone and Setup
   cd Mamut
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt

2. Configure Environment
   cp .env.example .env

3. Run the Engine
   python main.py
