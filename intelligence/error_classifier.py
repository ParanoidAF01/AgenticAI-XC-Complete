"""
Error Classifier using Company's LLM API.
Takes an error log + similar past errors and classifies it into one of 6 types.
Uses an OpenAI-compatible endpoint with claude-sonnet-4-6.
"""
from openai import OpenAI
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config.settings import CompanyAPIConfig

# Initialize the OpenAI-compatible chat client
client = OpenAI(
    base_url=CompanyAPIConfig.BASE_URL,
    api_key=CompanyAPIConfig.API_KEY
)
CHAT_MODEL = CompanyAPIConfig.CHAT_MODEL

# The classification prompt — this is the "brain" of the system
CLASSIFICATION_PROMPT = """You are an Azure Data Factory error classification expert.

Analyze the following ADF pipeline error and classify it into EXACTLY ONE of these 6 categories:

**Category 1 - Parameter Errors** (★★★★★ Self-heal suitability): Incorrect or missing pipeline parameters, wrong parameter values, parameter type mismatches, null parameters, default parameter issues. Extremely frequent, repeatable, easy to self-heal.
**Category 2 - Dataset Type Errors** (★★★★★ Self-heal suitability): Wrong dataset types, schema mismatches, column mapping failures, data type conversion errors, format mismatches between source and sink. Common, predictable corrections.
**Category 3 - Credentials Expired** (★★★★ Self-heal suitability): Expired service principal secrets, expired SAS tokens, expired Key Vault secrets, expired managed identity tokens, expired connection strings. Simple automated fix, high repeatability.
**Category 4 - Large Data / Timeout** (★★★★ Self-heal suitability): Data volume too large for single run, copy activity timeouts, data flow timeouts, memory exceeded due to data size, integration runtime timeouts. Heavy effort savings, predictable chunking.
**Category 5 - Server Slow** (★★★ Self-heal suitability): Slow source/sink servers, high latency connections, throttled APIs, overloaded databases, Azure service degradation. Needs smart retries/load management.
**Category 6 - Subscription Corrupt** (★★ Self-heal suitability): Corrupted Azure subscription settings, broken resource group configurations, invalid ARM templates, corrupted linked services, broken integration runtime configs. Template-based regeneration possible.

=== ERROR DETAILS ===
Pipeline: {pipeline_name}
Error Message: {error_message}
Failed Activities: {failed_activities}

=== SIMILAR PAST ERRORS (for reference) ===
{similar_errors}

=== PIPELINE METADATA ===
{pipeline_metadata}

=== YOUR RESPONSE ===
Respond in this exact JSON format (no other text):
{{
    "error_type": <number 1-6>,
    "error_type_name": "<name of the category>",
    "confidence": <0.0 to 1.0>,
    "root_cause_summary": "<2-3 sentence explanation of what went wrong>",
    "is_auto_recoverable": <true if type 1, 2, 3, or 4 — false if type 5 or 6>,
    "recommended_action": "<what should be done>",
    "priority": "<P1/P2/P3/P4>"
}}"""


def classify_error(error_details: dict, similar_errors: list, pipeline_metadata: dict = None) -> dict:
    """
    Classify an ADF error using the company's LLM.

    Args:
        error_details: Dict with pipeline_name, combined_error, failed_activities
        similar_errors: List of similar past errors from Pinecone
        pipeline_metadata: Dict with pipeline info from SQLite

    Returns:
        Classification result as a dict.
    """
    # Format similar errors for the prompt
    similar_str = "None found." if not similar_errors else ""
    for i, err in enumerate(similar_errors, 1):
        meta = err.get("metadata", {})
        similar_str += (
            f"\n{i}. [Score: {err['score']:.2f}] "
            f"Type {meta.get('error_type', '?')}: "
            f"{meta.get('error_message', 'N/A')[:200]}"
        )

    # Format pipeline metadata
    meta_str = "No metadata available."
    if pipeline_metadata:
        meta_str = (
            f"Owner: {pipeline_metadata.get('owner_name', 'Unknown')}, "
            f"Criticality: {pipeline_metadata.get('criticality', 'medium')}, "
            f"Schedule: {pipeline_metadata.get('schedule', 'unknown')}"
        )

    # Build the prompt
    prompt = CLASSIFICATION_PROMPT.format(
        pipeline_name=error_details.get("pipeline_name", "Unknown"),
        error_message=error_details.get("combined_error", "No error message"),
        failed_activities=json.dumps(error_details.get("failed_activities", []), indent=2),
        similar_errors=similar_str,
        pipeline_metadata=meta_str
    )

    try:
        response = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1
        )
        result_text = response.choices[0].message.content.strip()

        # Clean up — remove markdown code fences if present
        if result_text.startswith("```"):
            result_text = result_text.split("\n", 1)[1]
            result_text = result_text.rsplit("```", 1)[0]

        result = json.loads(result_text)
        print(
            f"   [CLASSIFY] Type {result['error_type']} "
            f"({result['error_type_name']}) - Confidence: {result['confidence']}"
        )
        return result

    except Exception as e:
        print(f"   [ERROR] Classification failed: {str(e)}")
        # Default to non-recoverable if classification fails
        return {
            "error_type": 6,
            "error_type_name": "Subscription Corrupt",
            "confidence": 0.0,
            "root_cause_summary": f"Classification failed: {str(e)}",
            "is_auto_recoverable": False,
            "recommended_action": "Manual investigation required.",
            "priority": "P2"
        }
