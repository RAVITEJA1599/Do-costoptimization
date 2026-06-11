import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Base configuration."""

    # DigitalOcean API
    DIGITALOCEAN_TOKEN = os.getenv("DIGITALOCEAN_TOKEN", "")
    DO_API_TIMEOUT = 30
    DO_API_BASE = "https://api.digitalocean.com/v2"

    # Claude AI
    CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "")

    # PostgreSQL
    DATABASE_URL = os.getenv("DATABASE_URL", "")

    # JWT — no fallback; startup validation enforces this is set
    JWT_SECRET: str = os.getenv("JWT_SECRET", "")

    # FastAPI
    ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
    DEBUG = ENVIRONMENT == "development"
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

    # Default Admin User — no fallback; startup validation enforces these are set
    ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")

    # CORS
    CORS_ORIGINS = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ]

    if os.getenv("ALLOWED_ORIGINS"):
        CORS_ORIGINS.extend(os.getenv("ALLOWED_ORIGINS", "").split(","))

    # Validation — app refuses to start if any of these are absent or empty
    REQUIRED_ENV_VARS = ["DIGITALOCEAN_TOKEN", "JWT_SECRET", "ADMIN_EMAIL", "ADMIN_PASSWORD"]

    @staticmethod
    def validate():
        """Validate required environment variables."""
        missing = [var for var in Config.REQUIRED_ENV_VARS if not os.getenv(var)]
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")


class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True
    LOG_LEVEL = "DEBUG"


class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False
    LOG_LEVEL = "INFO"


class TestingConfig(Config):
    """Testing configuration."""
    DEBUG = True
    DIGITALOCEAN_TOKEN = "test_token"
    CLAUDE_API_KEY = "test_claude_key"
    DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/costdetective_test"
    JWT_SECRET: str = "test-only-jwt-secret-not-for-production"


def get_config() -> Config:
    """Get configuration based on environment."""
    env = os.getenv("ENVIRONMENT", "development")

    if env == "production":
        return ProductionConfig()
    elif env == "testing":
        return TestingConfig()
    else:
        return DevelopmentConfig()


config = get_config()
