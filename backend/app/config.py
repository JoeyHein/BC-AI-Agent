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
    BC_COMPANY_NAME: str = "Open Distribution Company Inc."  # For OData endpoints
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

    # Google Maps — Distance Matrix API for install travel auto-lookup.
    # Resolves any town name to road-km from Medicine Hat. Optional; if
    # unset, install_pricing_service falls back to its static dict.
    GOOGLE_MAPS_API_KEY: Optional[str] = None

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

    # CORS — comma-separated list of allowed origins
    ALLOWED_ORIGINS: str = "http://localhost:3000,http://localhost:3001,http://localhost:3002,http://localhost:3003,http://localhost:5173"

    # Application URLs
    API_URL: str = "http://localhost:8000"

    # Customer Portal Notifications
    NOTIFICATION_SENDER_EMAIL: str = "noreply@opendc.ca"
    ADMIN_NOTIFICATION_EMAILS: str = "joey@opendc.ca"  # Comma-separated list
    CUSTOMER_PORTAL_URL: str = "http://localhost:3001/customer.html"
    ADMIN_PORTAL_URL: str = "http://localhost:3001"

    # Daily planning workbook (4 AM job)
    # Recipients for the emailed workbook; falls back to ADMIN_NOTIFICATION_EMAILS.
    PLANNING_WORKBOOK_RECIPIENTS: Optional[str] = None  # comma-separated
    # SharePoint/Excel Online publish (fast-follow — needs Files/Sites Graph perm).
    # While disabled, delivery is by email attachment only.
    PLANNING_SHAREPOINT_ENABLED: bool = False
    PLANNING_SHAREPOINT_DRIVE_ID: Optional[str] = None       # Graph drive id of the doc library
    PLANNING_SHAREPOINT_FILE_PATH: str = "Planning/OPENDC_Planning.xlsx"  # path within the drive
    PLANNING_SHAREPOINT_WEB_URL: Optional[str] = None        # shown in the notification email

    # Production schedule (nightly job) — same Graph app/drive as the planning
    # workbook, different file. Shop-floor tracking sheet (Panels/Hardware/
    # Tracks/Springs/Shafts/Weather Stripping/Operators per open SO), hand-edited
    # directly in SharePoint/Excel Online between refreshes.
    PRODSCHED_SHAREPOINT_ENABLED: bool = False
    PRODSCHED_SHAREPOINT_DRIVE_ID: Optional[str] = None
    PRODSCHED_SHAREPOINT_FILE_PATH: str = "Production Schedule/OPENDC_Production_Schedule.xlsx"
    PRODSCHED_SHAREPOINT_WEB_URL: Optional[str] = None

    # AI invoice intake — reads vendor invoice PDFs from a monitored mailbox,
    # extracts + matches via Claude, and creates BC purchase invoices in
    # Draft status only (never posts). Defaults to the same inbox as the
    # existing email-quote monitor; point it at a dedicated invoices@ address
    # via env if that's where they actually land.
    INVOICE_INTAKE_ENABLED: bool = False
    INVOICE_INTAKE_MAILBOX: Optional[str] = None  # falls back to EMAIL_INBOX_1 if unset
    INVOICE_INTAKE_LOOKBACK_HOURS: int = 24

    # Feature Flags
    ENABLE_EMAIL_MONITORING: bool = True
    ENABLE_AI_PARSING: bool = True
    ENABLE_VENDOR_INTELLIGENCE: bool = True
    ENABLE_CUSTOMER_NOTIFICATIONS: bool = True

    # Email Monitoring Settings
    EMAIL_CHECK_INTERVAL_MINUTES: int = 15  # How often to check for new emails

    # Mailchimp (Weekly Email Agent)
    MAILCHIMP_API_KEY: Optional[str] = None
    MAILCHIMP_SERVER_PREFIX: Optional[str] = None  # e.g. us14
    MAILCHIMP_AUDIENCE_ID: Optional[str] = None
    MAILCHIMP_FROM_NAME: str = "Joey at OPENDC"
    MAILCHIMP_FROM_EMAIL: str = "joey@opendc.ca"

    # Integrations (service-to-service API key for Donna PA and other AI agents)
    INTEGRATIONS_API_KEY: Optional[str] = None

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
    def bc_odata_url(self) -> str:
        """Construct BC OData URL for web services"""
        if not all([self.BC_TENANT_ID, self.BC_ENVIRONMENT]):
            return ""
        return f"{self.BC_BASE_URL}/{self.BC_TENANT_ID}/{self.BC_ENVIRONMENT}/ODataV4"

    @property
    def bc_picking_api_url(self) -> str:
        """Construct the BC custom API URL for the Upwardor picking extension.

        Custom API pages live under api/{publisher}/{group}/{version}, NOT under
        api/v2.0. Requires the picking API pages (70134-70140) to be deployed to
        the target environment - until then every call here returns 404.
        """
        if not all([self.BC_TENANT_ID, self.BC_ENVIRONMENT]):
            return ""
        return (
            f"{self.BC_BASE_URL}/{self.BC_TENANT_ID}/{self.BC_ENVIRONMENT}"
            f"/api/upwardor/picking/v1.0"
        )

    @property
    def is_production(self) -> bool:
        """Check if running in production"""
        return self.ENVIRONMENT.lower() == "production"


# Global settings instance
settings = Settings()
