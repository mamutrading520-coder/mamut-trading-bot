"""Setup script to create all necessary directories and files"""
from pathlib import Path

ROOT = Path(__file__).parent

DIRECTORIES = [
    "logs", "data",
    "config", "core", "storage", "monitoring",
    "discovery", "enrich", "filters", "scoring",
    "analysis", "signals", "validation", "utils",
]

def create_directories():
    print("Creating directories...")
    for directory in DIRECTORIES:
        dir_path = ROOT / directory
        dir_path.mkdir(parents=True, exist_ok=True)
        print(f"✓ {directory}/")

def create_env_file():
    print("Creating .env file...")
    env = """PUMP_WS_URL=wss://pumpportal.fun/api/data
PUMP_RECONNECT_DELAY=5
PUMP_MAX_RETRIES=10
RAYDIUM_API_URL=https://api.raydium.io/v2/sdk/liquidity/mainnet.json
RAYDIUM_POOL_TIMEOUT=30
SOLANA_RPC_URL=https://api.mainnet-beta.solana.com
DATABASE_URL=sqlite:///./mamut.db
LOG_LEVEL=INFO
WEBHOOK_URL=
ALERT_ENABLED=false
"""
    (ROOT / ".env").write_text(env, encoding='utf-8')

def create_requirements():
    print("Creating requirements.txt...")
    req = """aiohttp==3.13.3
websockets==13.1
sqlalchemy==2.0.40
pydantic==2.10.6
pydantic-settings==2.7.1
python-dotenv==1.0.1
httpx==0.28.1
loguru==0.7.3
"""
    (ROOT / "requirements.txt").write_text(req, encoding='utf-8')

def create_gitignore():
    print("Creating .gitignore...")
    git = """__pycache__/
*.py[cod]
*.db
mamut.db
logs/
.env
.venv
venv/
"""
    (ROOT / ".gitignore").write_text(git, encoding='utf-8')

def main():
    print("=" * 60)
    print("SETUP MAMUT PROJECT")
    print("=" * 60)
    create_directories()
    create_env_file()
    create_requirements()
    create_gitignore()
    print("=" * 60)
    print("✅ SETUP COMPLETADO")
    print("=" * 60)

if __name__ == "__main__":
    main()