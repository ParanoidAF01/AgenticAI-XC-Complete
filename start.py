"""
Master startup script.
Starts the ADF pipeline listener that polls for errors and processes them.
Doc generation + email notifications are handled inline by the error processor.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from listener.adf_listener import start_listener


def main():
    print("=" * 60)
    print("Self-Healing ADF System - Starting")
    print("=" * 60)
    print()
    print("  Components:")
    print("  - ADF Listener       Polls Azure for pipeline failures")
    print("  - LLM Classifier     Classifies errors into 6 types")
    print("  - Pinecone Store     Similarity search for past errors")
    print("  - Azure Restart      Auto-restarts recoverable pipelines")
    print("  - PDF Doc Generator  Creates resolution docs for escalations")
    print("  - Email Notifier     Sends PDF reports to pipeline owners")
    print()

    # Start the ADF listener (blocks main thread)
    start_listener()


if __name__ == "__main__":
    main()
