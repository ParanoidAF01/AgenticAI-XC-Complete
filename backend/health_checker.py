"""
Health Checker — verifies connectivity to all external services.

Runs checks in parallel using ThreadPoolExecutor so the total wait time
equals the slowest single check (~3-4s), not the sum of all checks (~12s).

Results are cached in-memory with a 30-second TTL so the frontend
can poll /api/listener/health frequently without triggering real network calls.
"""
import os
import sys
import time
import threading
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config.settings import AzureConfig, SqlConfig, ChromaConfig, CompanyAPIConfig

# How long cached results stay valid (seconds)
CACHE_TTL = 30

# Timeout per individual health check (seconds)
CHECK_TIMEOUT = 10


class HealthResult:
    """Single service health check result."""

    def __init__(self, service: str, status: str = "unchecked",
                 message: str = "", latency_ms: int = 0):
        self.service = service
        self.status = status        # "connected", "failed", "checking", "unchecked"
        self.message = message      # Success info or error reason
        self.latency_ms = latency_ms
        self.checked_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "service": self.service,
            "status": self.status,
            "message": self.message,
            "latency_ms": self.latency_ms,
            "checked_at": self.checked_at,
        }


class HealthChecker:
    """
    Checks connectivity to all external services used by the self-healing system.

    Services:
        1. Azure AD Auth — validates service principal credentials
        2. ADF SDK — verifies Data Factory access
        3. SQL Server — tests PipelineRunLog database connectivity
        4. ChromaDB — heartbeat check on the vector store
        5. LLM API — small embedding call to verify API access
    """

    # Ordered list of services (matches the prototype UI card order)
    SERVICES = [
        "Azure AD Auth",
        "ADF SDK",
        "SQL Server",
        "ChromaDB",
        "LLM API",
    ]

    def __init__(self):
        self._cache: dict[str, HealthResult] = {}
        self._cache_time: float = 0
        self._lock = threading.Lock()
        self._checking = False

    def get_cached_results(self) -> dict:
        """Return cached health results. Returns stale flag if cache is expired."""
        with self._lock:
            stale = (time.time() - self._cache_time) > CACHE_TTL if self._cache_time > 0 else True
            results = [
                self._cache.get(svc, HealthResult(service=svc)).to_dict()
                for svc in self.SERVICES
            ]
            return {
                "services": results,
                "stale": stale,
                "checking": self._checking,
                "cached_at": datetime.fromtimestamp(
                    self._cache_time, tz=timezone.utc
                ).isoformat() if self._cache_time > 0 else None,
            }

    def run_checks(self) -> dict:
        """
        Run all health checks in parallel. Blocks until complete (~3-4s).
        Updates the cache and returns fresh results.
        """
        self._checking = True

        check_functions = {
            "Azure AD Auth": self._check_azure_ad,
            "ADF SDK": self._check_adf_sdk,
            "SQL Server": self._check_sql_server,
            "ChromaDB": self._check_chromadb,
            "LLM API": self._check_llm_api,
        }

        results = {}

        with ThreadPoolExecutor(max_workers=5) as executor:
            future_to_service = {
                executor.submit(func): svc
                for svc, func in check_functions.items()
            }

            for future in as_completed(future_to_service, timeout=CHECK_TIMEOUT + 2):
                service = future_to_service[future]
                try:
                    result = future.result(timeout=CHECK_TIMEOUT)
                    results[service] = result
                except Exception as e:
                    results[service] = HealthResult(
                        service=service,
                        status="failed",
                        message=f"Check timed out or crashed: {str(e)[:200]}",
                    )

        # Fill in any missing services (shouldn't happen, but safety)
        for svc in self.SERVICES:
            if svc not in results:
                results[svc] = HealthResult(
                    service=svc,
                    status="failed",
                    message="Health check did not complete",
                )

        # Update cache
        with self._lock:
            self._cache = results
            self._cache_time = time.time()
            self._checking = False

        return self.get_cached_results()

    def run_checks_background(self):
        """Trigger health checks in a background thread (non-blocking)."""
        if self._checking:
            return  # Already running
        thread = threading.Thread(target=self.run_checks, daemon=True)
        thread.start()

    # ─── Individual Check Methods ──────────────────────────────────

    def _check_azure_ad(self) -> HealthResult:
        """Check Azure AD authentication using service principal."""
        start = time.time()
        try:
            from azure.identity import ClientSecretCredential

            if not all([AzureConfig.TENANT_ID, AzureConfig.CLIENT_ID, AzureConfig.CLIENT_SECRET]):
                return HealthResult(
                    service="Azure AD Auth",
                    status="failed",
                    message="Missing Azure credentials in .env (TENANT_ID, CLIENT_ID, or CLIENT_SECRET)",
                )

            credential = ClientSecretCredential(
                tenant_id=AzureConfig.TENANT_ID,
                client_id=AzureConfig.CLIENT_ID,
                client_secret=AzureConfig.CLIENT_SECRET,
            )
            # Request a token for the Azure management scope
            token = credential.get_token("https://management.azure.com/.default")
            latency = int((time.time() - start) * 1000)

            return HealthResult(
                service="Azure AD Auth",
                status="connected",
                message=f"Authenticated as {AzureConfig.CLIENT_ID[:12]}...",
                latency_ms=latency,
            )
        except Exception as e:
            latency = int((time.time() - start) * 1000)
            return HealthResult(
                service="Azure AD Auth",
                status="failed",
                message=str(e)[:200],
                latency_ms=latency,
            )

    def _check_adf_sdk(self) -> HealthResult:
        """Check Azure Data Factory SDK connectivity."""
        start = time.time()
        try:
            from azure.identity import ClientSecretCredential
            from azure.mgmt.datafactory import DataFactoryManagementClient

            if not all([AzureConfig.SUBSCRIPTION_ID, AzureConfig.RESOURCE_GROUP, AzureConfig.FACTORY_NAME]):
                return HealthResult(
                    service="ADF SDK",
                    status="failed",
                    message="Missing ADF config in .env (SUBSCRIPTION_ID, RESOURCE_GROUP, or FACTORY_NAME)",
                )

            credential = ClientSecretCredential(
                tenant_id=AzureConfig.TENANT_ID,
                client_id=AzureConfig.CLIENT_ID,
                client_secret=AzureConfig.CLIENT_SECRET,
            )
            client = DataFactoryManagementClient(credential, AzureConfig.SUBSCRIPTION_ID)
            factory = client.factories.get(AzureConfig.RESOURCE_GROUP, AzureConfig.FACTORY_NAME)
            latency = int((time.time() - start) * 1000)

            return HealthResult(
                service="ADF SDK",
                status="connected",
                message=f"Factory: {factory.name} ({factory.location})",
                latency_ms=latency,
            )
        except Exception as e:
            latency = int((time.time() - start) * 1000)
            return HealthResult(
                service="ADF SDK",
                status="failed",
                message=str(e)[:200],
                latency_ms=latency,
            )

    def _check_sql_server(self) -> HealthResult:
        """Check Azure SQL Server connectivity."""
        start = time.time()
        try:
            import pyodbc

            if not all([SqlConfig.SERVER, SqlConfig.DATABASE, SqlConfig.USERNAME, SqlConfig.PASSWORD]):
                return HealthResult(
                    service="SQL Server",
                    status="failed",
                    message="Missing SQL config in .env (SERVER, DATABASE, USERNAME, or PASSWORD)",
                )

            conn_str = (
                f"DRIVER={{ODBC Driver 18 for SQL Server}};"
                f"SERVER={SqlConfig.SERVER};"
                f"DATABASE={SqlConfig.DATABASE};"
                f"UID={SqlConfig.USERNAME};"
                f"PWD={SqlConfig.PASSWORD};"
                f"Encrypt=yes;"
                f"TrustServerCertificate=no;"
                f"Connection Timeout=10;"
            )
            conn = pyodbc.connect(conn_str)
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.close()
            conn.close()
            latency = int((time.time() - start) * 1000)

            return HealthResult(
                service="SQL Server",
                status="connected",
                message=f"Connected to {SqlConfig.SERVER} / {SqlConfig.DATABASE}",
                latency_ms=latency,
            )
        except Exception as e:
            latency = int((time.time() - start) * 1000)
            return HealthResult(
                service="SQL Server",
                status="failed",
                message=str(e)[:200],
                latency_ms=latency,
            )

    def _check_chromadb(self) -> HealthResult:
        """Check ChromaDB vector store connectivity."""
        start = time.time()
        try:
            import chromadb

            persist_dir = ChromaConfig.PERSIST_DIR
            if not os.path.exists(persist_dir):
                return HealthResult(
                    service="ChromaDB",
                    status="failed",
                    message=f"Persist directory not found: {persist_dir}",
                )

            client = chromadb.PersistentClient(path=persist_dir)
            heartbeat = client.heartbeat()
            collections = client.list_collections()
            latency = int((time.time() - start) * 1000)

            return HealthResult(
                service="ChromaDB",
                status="connected",
                message=f"Ready. {len(collections)} collection(s) loaded.",
                latency_ms=latency,
            )
        except Exception as e:
            latency = int((time.time() - start) * 1000)
            return HealthResult(
                service="ChromaDB",
                status="failed",
                message=str(e)[:200],
                latency_ms=latency,
            )

    def _check_llm_api(self) -> HealthResult:
        """Check LLM/Embedding API connectivity with a small test call."""
        start = time.time()
        try:
            from openai import OpenAI

            if not all([CompanyAPIConfig.BASE_URL, CompanyAPIConfig.API_KEY]):
                return HealthResult(
                    service="LLM API",
                    status="failed",
                    message="Missing LLM API config in .env (BASE_URL or API_KEY)",
                )

            # Check if placeholder values are still present
            if "your-company" in (CompanyAPIConfig.API_KEY or "").lower():
                return HealthResult(
                    service="LLM API",
                    status="failed",
                    message="API key is a placeholder. Update COMPANY_API_KEY in .env",
                )

            client = OpenAI(
                base_url=CompanyAPIConfig.BASE_URL,
                api_key=CompanyAPIConfig.API_KEY,
            )
            # Small embedding call to verify connectivity
            response = client.embeddings.create(
                model=CompanyAPIConfig.EMBEDDING_MODEL,
                input="health check",
            )
            latency = int((time.time() - start) * 1000)

            return HealthResult(
                service="LLM API",
                status="connected",
                message=f"Model: {CompanyAPIConfig.EMBEDDING_MODEL} ({latency}ms latency)",
                latency_ms=latency,
            )
        except Exception as e:
            latency = int((time.time() - start) * 1000)
            return HealthResult(
                service="LLM API",
                status="failed",
                message=str(e)[:200],
                latency_ms=latency,
            )


# Singleton instance
health_checker = HealthChecker()
