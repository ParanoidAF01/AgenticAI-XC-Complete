"""
RAG (Retrieval-Augmented Generation) Pipeline.
Searches Pinecone for relevant errors, then uses company's LLM to answer questions.
"""
from openai import OpenAI
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from intelligence.pinecone_store import search_similar_errors
from config.metadata_store import get_pipeline, get_error_history
from config.settings import CompanyAPIConfig

# Initialize the OpenAI-compatible chat client
client = OpenAI(
    base_url=CompanyAPIConfig.BASE_URL,
    api_key=CompanyAPIConfig.API_KEY
)
CHAT_MODEL = CompanyAPIConfig.CHAT_MODEL

CHAT_PROMPT = """You are an Azure Data Factory expert assistant. You help developers understand and resolve pipeline errors.

You have access to the following context from the error log database:

=== RELEVANT ERROR LOGS ===
{relevant_errors}

=== PIPELINE METADATA ===
{pipeline_metadata}

=== RECENT ERROR HISTORY ===
{error_history}

=== DEVELOPER'S QUESTION ===
{question}

=== INSTRUCTIONS ===
- Answer the question using the context above
- If asked about a specific pipeline failure, explain what happened and how to fix it
- If asked about error patterns, analyze the history and provide insights
- Always provide actionable, step-by-step guidance
- If you don't have enough context, say so honestly
- Format your response in clear Markdown with headers and bullet points
"""


def query(question: str, pipeline_name: str = None) -> str:
    """
    Answer a developer's question using RAG.

    Args:
        question: The developer's question
        pipeline_name: Optional — filter search to a specific pipeline

    Returns:
        LLM-generated answer as a string
    """
    # Step 1: Search Pinecone for relevant errors
    namespace = pipeline_name if pipeline_name else "default"

    # Search across the given namespace
    relevant_errors = search_similar_errors(question, namespace=namespace, top_k=5)

    # Format results
    errors_str = "No relevant errors found."
    if relevant_errors:
        errors_str = ""
        for i, err in enumerate(relevant_errors, 1):
            meta = err.get("metadata", {})
            errors_str += f"\n{i}. [Similarity: {err['score']:.2f}]\n"
            errors_str += f"   Pipeline: {meta.get('pipeline_name', 'N/A')}\n"
            errors_str += f"   Error Type: {meta.get('error_type_name', 'N/A')}\n"
            errors_str += f"   Message: {meta.get('error_message', 'N/A')}\n"
            errors_str += f"   Root Cause: {meta.get('root_cause', 'N/A')}\n"
            errors_str += f"   Time: {meta.get('timestamp', 'N/A')}\n"

    # Step 2: Get pipeline metadata
    meta_str = "No pipeline specified."
    if pipeline_name:
        meta = get_pipeline(pipeline_name)
        if meta:
            meta_str = (
                f"Name: {meta['pipeline_name']}, Owner: {meta['owner_name']}, "
                f"Email: {meta['owner_email']}, Criticality: {meta['criticality']}, "
                f"Schedule: {meta['schedule']}"
            )

    # Step 3: Get recent error history
    history = get_error_history(pipeline_name, limit=10)
    history_str = "No history available."
    if history:
        history_str = ""
        for h in history:
            history_str += (
                f"- [{h['timestamp']}] Type {h['error_type']}: "
                f"{h['error_message'][:100]}... → {h['action_taken']}\n"
            )

    # Step 4: Build prompt and query LLM
    prompt = CHAT_PROMPT.format(
        relevant_errors=errors_str,
        pipeline_metadata=meta_str,
        error_history=history_str,
        question=question
    )

    response = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )
    return response.choices[0].message.content
