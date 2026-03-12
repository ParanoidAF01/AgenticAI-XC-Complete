"""
Central configuration loader.
Reads all settings from .env file and makes them available to all modules.
"""
import os
from dotenv import load_dotenv

# Load .env file
load_dotenv()


class AzureConfig:
    """Azure credentials and ADF details."""
    TENANT_ID = os.getenv("AZURE_TENANT_ID")
    CLIENT_ID = os.getenv("AZURE_CLIENT_ID")
    CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")
    SUBSCRIPTION_ID = os.getenv("AZURE_SUBSCRIPTION_ID")
    RESOURCE_GROUP = os.getenv("ADF_RESOURCE_GROUP")
    FACTORY_NAME = os.getenv("ADF_FACTORY_NAME")


class PineconeConfig:
    """Pinecone vector database settings."""
    API_KEY = os.getenv("PINECONE_API_KEY")
    INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "adf-error-logs")


class CompanyAPIConfig:
    """Company's OpenAI-compatible API settings."""
    BASE_URL = os.getenv("COMPANY_API_BASE_URL")
    API_KEY = os.getenv("COMPANY_API_KEY")
    CHAT_MODEL = os.getenv("COMPANY_CHAT_MODEL", "claude-sonnet-4-6")
    EMBEDDING_MODEL = os.getenv("COMPANY_EMBEDDING_MODEL", "text-embedding-3-large")


class NotificationConfig:
    """Email and notification settings."""
    SMTP_EMAIL = os.getenv("SMTP_EMAIL")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
    NOTIFY_RECIPIENT = os.getenv("NOTIFY_RECIPIENT")


# Polling interval in seconds
POLL_INTERVAL = 30
