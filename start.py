"""
Master startup script.
Supports multiple listener modes via LISTENER_MODE environment variable.
The website (future) will control this via the FastAPI listener_manager.

Usage:
    LISTENER_MODE=sql python start.py     # SQL table listener (default)
    LISTENER_MODE=adf python start.py     # ADF SDK listener
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

# Read listener mode from environment (default: sql)
LISTENER_MODE = os.getenv("LISTENER_MODE", "sql").lower()

# Registry of available listeners
# Future: add "databricks", "snowflake", etc.
AVAILABLE_LISTENERS = {
    "adf": {
        "module": "listener.adf_listener",
        "label": "ADF SDK Listener",
        "description": "Polls Azure Data Factory SDK for failed pipeline runs",
    },
    "sql": {
        "module": "listener.sql_listener",
        "label": "SQL Table Listener",
        "description": "Polls PipelineRunLog table for failed pipeline runs",
    },
}


def get_listener(mode: str):
    """Import and return the start_listener function for the given mode."""
    if mode not in AVAILABLE_LISTENERS:
        return None, None
    info = AVAILABLE_LISTENERS[mode]
    module = __import__(info["module"], fromlist=["start_listener"])
    return module.start_listener, info


def main():
    print("=" * 60)
    print("Self-Healing ADF System - Starting")
    print("=" * 60)
    print()

    start_listener, info = get_listener(LISTENER_MODE)

    if not start_listener:
        print(f"  [ERROR] Unknown LISTENER_MODE: '{LISTENER_MODE}'")
        print(f"  Available modes: {', '.join(AVAILABLE_LISTENERS.keys())}")
        sys.exit(1)

    print(f"  Listener Mode:   {LISTENER_MODE.upper()}")
    print(f"  Listener:        {info['label']}")
    print(f"  Description:     {info['description']}")
    print()
    print("  Components:")
    print(f"  - {info['label']:<20s} {info['description']}")
    print("  - LLM Classifier      Classifies errors into 6 types")
    print("  - ChromaDB Store       Similarity search for past errors")
    print("  - Azure Restart        Auto-restarts recoverable pipelines")
    print("  - PDF Doc Generator    Creates resolution docs for escalations")
    print("  - Email Notifier       Sends PDF reports to pipeline owners")
    print()

    # Start the listener (blocks main thread)
    start_listener()


if __name__ == "__main__":
    main()
