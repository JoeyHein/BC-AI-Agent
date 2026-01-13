"""
Configuration management using pydantic-settings
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    # Application
    APP_NAME: str = "BC AI Agent"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    SECRET_KEY: str = "change-me-in-production"

    # Business Central API
    BC_TENANT_ID: Optional[str] = None
    BC_CLIENT_ID: Optional[str] = None
    BC_CLIENT_SECRET: Optional[str] = None
    BC_ENVIRONMENT: str = "Sandbox"
    BC_COMPANY_ID: Optional[str] = None
    BC_BASE_URL: str = "https://api.businesscentral.dynamics.com/v2.0"

    # Microsoft Graph API
    GRAPH_TENANT_ID: Optional[str] = None
    GRAPH_CLIENT_ID: Optional[str] = None
    GRAPH_CLIENT_SECRET: Optional[str] = None
    # Email inboxes (legacy - supports up to 10 inboxes)
    EMAIL_INBOX_1: Optional[str] = None
    EMAIL_INBOX_2: Optional[str] = None
    EMAIL_INBOX_3: Optional[str] = None
    EMAIL_INBOX_4: Optional[str] = None
    EMAIL_INBOX_5: Optional[str] = None
    EMAIL_INBOX_6: Optional[str] = None
    EMAIL_INBOX_7: Optional[str] = None
    EMAIL_INBOX_8: Optional[str] = None
    EMAIL_INBOX_9: Optional[str] = None
    EMAIL_INBOX_10: Optional[str] = None

    # Anthropic Claude AI
    ANTHROPIC_API_KEY: Optional[str] = None

    # Database
    DATABASE_URL: str = "postgresql://user:password@localhost:5432/bc_ai_agent"
    DATABASE_ECHO: bool = False

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Azure Services
    AZURE_KEY_VAULT_URL: Optional[str] = None
    AZURE_STORAGE_CONNECTION_STRING: Optional[str] = None
    AZURE_APPLICATION_INSIGHTS_CONNECTION_STRING: Optional[str] = None

    # OpenPhone (Phase 1+)
    OPENPHONE_API_KEY: Optional[str] = None

    # Feature Flags
    ENABLE_EMAIL_MONITORING: bool = True
    ENABLE_AI_PARSING: bool = True
    ENABLE_VENDOR_INTELLIGENCE: bool = True

    # Email Monitoring Settings
    EMAIL_CHECK_INTERVAL_MINUTES: int = 15  # How often to check for new emails

    # Logging
    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )

    @property
    def bc_api_url(self) -> str:
        """Construct full BC API URL"""
        if not all([self.BC_TENANT_ID, self.BC_ENVIRONMENT]):
            return ""
        return f"{self.BC_BASE_URL}/{self.BC_TENANT_ID}/{self.BC_ENVIRONMENT}/api/v2.0"

    @property
    def is_production(self) -> bool:
        """Check if running in production"""
        return self.ENVIRONMENT.lower() == "production"


# Global settings instance
settings = Settings()
