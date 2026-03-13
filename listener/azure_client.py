"""
Azure ADF Client — Handles authentication and pipeline operations.
Uses Service Principal credentials from .env to interact with Azure Data Factory REST API.
"""
import requests
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config.settings import AzureConfig


def get_azure_token():
    """
    Authenticate with Azure AD using Service Principal (client credentials flow).
    Returns a Bearer token for Azure Management API calls.
    """
    url = f"https://login.microsoftonline.com/{AzureConfig.TENANT_ID}/oauth2/v2.0/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": AzureConfig.CLIENT_ID,
        "client_secret": AzureConfig.CLIENT_SECRET,
        "scope": "https://management.azure.com/.default"
    }

    try:
        response = requests.post(url, data=data, timeout=15)
        if response.status_code == 200:
            return response.json().get("access_token")
        else:
            print(f"   [ERROR] Azure auth failed ({response.status_code}): {response.text[:200]}")
            return None
    except Exception as e:
        print(f"   [ERROR] Azure auth error: {str(e)}")
        return None


def restart_pipeline(pipeline_name: str, parameters: dict = None) -> dict:
    """
    Trigger a new run of an ADF pipeline via Azure REST API.

    POST https://management.azure.com/subscriptions/{sub}/resourceGroups/{rg}/
         providers/Microsoft.DataFactory/factories/{factory}/pipelines/{pipeline}/
         createRun?api-version=2018-06-01

    Args:
        pipeline_name: Name of the ADF pipeline to restart
        parameters: Optional dict of pipeline parameters to pass

    Returns:
        dict with 'success', 'run_id', and 'message' keys
    """
    # Validate Azure config
    if not all([AzureConfig.TENANT_ID, AzureConfig.CLIENT_ID,
                AzureConfig.CLIENT_SECRET, AzureConfig.SUBSCRIPTION_ID,
                AzureConfig.RESOURCE_GROUP, AzureConfig.FACTORY_NAME]):
        return {
            "success": False,
            "run_id": None,
            "message": "Azure credentials not fully configured in .env"
        }

    # Get auth token
    token = get_azure_token()
    if not token:
        return {
            "success": False,
            "run_id": None,
            "message": "Failed to authenticate with Azure AD"
        }

    # Build the REST API URL
    url = (
        f"https://management.azure.com"
        f"/subscriptions/{AzureConfig.SUBSCRIPTION_ID}"
        f"/resourceGroups/{AzureConfig.RESOURCE_GROUP}"
        f"/providers/Microsoft.DataFactory"
        f"/factories/{AzureConfig.FACTORY_NAME}"
        f"/pipelines/{pipeline_name}"
        f"/createRun?api-version=2018-06-01"
    )

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    body = parameters or {}

    try:
        response = requests.post(url, headers=headers, json=body, timeout=30)

        if response.status_code == 200:
            run_id = response.json().get("runId", "unknown")
            return {
                "success": True,
                "run_id": run_id,
                "message": f"Pipeline '{pipeline_name}' restarted successfully (Run ID: {run_id})"
            }
        elif response.status_code == 404:
            return {
                "success": False,
                "run_id": None,
                "message": f"Pipeline '{pipeline_name}' not found in factory '{AzureConfig.FACTORY_NAME}'"
            }
        elif response.status_code == 403:
            return {
                "success": False,
                "run_id": None,
                "message": "Service Principal lacks permission to run pipelines. Assign 'Data Factory Contributor' role."
            }
        else:
            return {
                "success": False,
                "run_id": None,
                "message": f"Azure returned {response.status_code}: {response.text[:300]}"
            }

    except requests.exceptions.Timeout:
        return {
            "success": False,
            "run_id": None,
            "message": "Azure API request timed out"
        }
    except Exception as e:
        return {
            "success": False,
            "run_id": None,
            "message": f"Error calling Azure API: {str(e)}"
        }


def get_pipeline_run_status(run_id: str) -> dict:
    """
    Check the status of a pipeline run.

    GET https://management.azure.com/subscriptions/{sub}/resourceGroups/{rg}/
        providers/Microsoft.DataFactory/factories/{factory}/
        pipelineruns/{runId}?api-version=2018-06-01
    """
    token = get_azure_token()
    if not token:
        return {"status": "Unknown", "message": "Auth failed"}

    url = (
        f"https://management.azure.com"
        f"/subscriptions/{AzureConfig.SUBSCRIPTION_ID}"
        f"/resourceGroups/{AzureConfig.RESOURCE_GROUP}"
        f"/providers/Microsoft.DataFactory"
        f"/factories/{AzureConfig.FACTORY_NAME}"
        f"/pipelineruns/{run_id}?api-version=2018-06-01"
    )

    headers = {"Authorization": f"Bearer {token}"}

    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 200:
            data = response.json()
            return {
                "status": data.get("status", "Unknown"),
                "run_start": data.get("runStart"),
                "run_end": data.get("runEnd"),
                "message": data.get("message", "")
            }
        return {"status": "Unknown", "message": f"HTTP {response.status_code}"}
    except Exception as e:
        return {"status": "Unknown", "message": str(e)}
