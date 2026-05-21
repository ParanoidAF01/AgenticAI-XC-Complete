"""
Error Processor — The orchestrator of the intelligence layer.
Receives raw error details from the listener, embeds them, searches for similar errors,
classifies them via the tiered pipeline, and returns a classification result.

The SQL listener (sql_listener.py) handles the action (restart/escalate) and
SQL write-back. This module is purely classification + storage.

Action logic:
  - Types 3, 4, 5 (auto-recoverable): Listener handles restart scheduling
  - Types 1, 2, 6 (non-recoverable): Listener handles escalation
  - After 3 failed restart attempts: Listener escalates
"""
import requests
import json
import sys
import os
import time
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from intelligence.chroma_store import store_error, search_similar_errors
from intelligence.tiered_classifier import classify_tiered
from config.metadata_store import get_pipeline, log_error
from config.settings import NotificationConfig


# ── Restart Tracker ────────────────────────────────────────────
MAX_RESTART_ATTEMPTS = 3


class RestartTracker:
    """
    In-memory tracker for restart attempts per (pipeline_name, error_type) pair.
    Used by the ADF listener for backward compatibility.
    The SQL listener uses the ModelActions table as the durable tracker instead.
    """

    def __init__(self):
        # Key: (pipeline_name, error_type) → {count, original_run_id, child_run_ids}
        self._attempts = {}
        # Set of run IDs created by restarts (so listener knows they are retry children)
        self._restart_run_ids = set()

    def get_attempt_count(self, pipeline_name: str, error_type: int) -> int:
        """Get the current retry count for a pipeline+error_type pair."""
        key = (pipeline_name, error_type)
        entry = self._attempts.get(key)
        return entry["count"] if entry else 0

    def can_restart(self, pipeline_name: str, error_type: int) -> bool:
        """Check if restarts are still allowed for this pipeline+error_type."""
        return self.get_attempt_count(pipeline_name, error_type) < MAX_RESTART_ATTEMPTS

    def record_restart(self, pipeline_name: str, error_type: int,
                       original_run_id: str, new_run_id: str):
        """Record a restart attempt and track the new run ID."""
        key = (pipeline_name, error_type)
        if key not in self._attempts:
            self._attempts[key] = {
                "count": 0,
                "original_run_id": original_run_id,
                "child_run_ids": []
            }
        self._attempts[key]["count"] += 1
        self._attempts[key]["child_run_ids"].append(new_run_id)
        self._restart_run_ids.add(new_run_id)

    def is_restart_child(self, run_id: str) -> bool:
        """Check if a run ID was created by a restart (child of a previous failure)."""
        return run_id in self._restart_run_ids

    def get_child_attempt_number(self, run_id: str) -> int:
        """Get the retry attempt number (1-based) for a child run ID."""
        for entry in self._attempts.values():
            if run_id in entry.get("child_run_ids", []):
                return entry["child_run_ids"].index(run_id) + 1
        return 0

    def get_all_child_run_ids(self) -> set:
        """Return all currently tracked child run IDs."""
        return set(self._restart_run_ids)

    def get_info(self, pipeline_name: str, error_type: int) -> dict:
        """Get the full tracking info for a pipeline+error_type pair."""
        key = (pipeline_name, error_type)
        return self._attempts.get(key, {
            "count": 0, "original_run_id": None, "child_run_ids": []
        })

    def reset(self, pipeline_name: str, error_type: int):
        """Reset the counter after escalation or successful run."""
        key = (pipeline_name, error_type)
        entry = self._attempts.pop(key, None)
        if entry:
            # Clean up child run IDs from the tracking set
            for rid in entry.get("child_run_ids", []):
                self._restart_run_ids.discard(rid)

    def reset_pipeline(self, pipeline_name: str):
        """Reset all counters for a specific pipeline (e.g., after a successful run)."""
        keys_to_remove = [k for k in self._attempts if k[0] == pipeline_name]
        for key in keys_to_remove:
            self.reset(key[0], key[1])


# Global singleton — shared between error_processor and adf_listener
restart_tracker = RestartTracker()


# ── Wait strategies per error type ─────────────────────────────
RESTART_STRATEGIES = {
    3: ("Retry after credential rotation/refresh", 60),
    4: ("Retry with delay for transient timeout", 120),
    5: ("Retry after server recovery window", 90),
}


def process_error(error_details: dict) -> dict:
    """
    Full error processing pipeline:
    1. Search for similar past errors in ChromaDB
    2. Get pipeline metadata from SQLite
    3. Classify the error using the tiered pipeline (L1→L2→L3)
    4. Store the error + classification in ChromaDB
    5. Log to SQLite
    6. Return classification result — the CALLER (sql_listener) handles action

    Returns:
        dict with action, error_type, classification, wait_seconds, etc.
    """
    pipeline_name = error_details.get("pipeline_name", "unknown")
    run_id = error_details.get("run_id", "unknown")
    error_text = error_details.get("combined_error", "")

    print(f"\n{'=' * 50}")
    print(f"[PROCESS] Processing error for pipeline: {pipeline_name}")
    print(f"{'=' * 50}")

    # Step 1: Get pipeline metadata
    print("   [META] Fetching pipeline metadata...")
    pipeline_metadata = get_pipeline(pipeline_name)

    # Step 2: Classify via 3-layer tiered pipeline (L1 CSV → L2 ChromaDB → L3 LLM)
    print("   [CLASSIFY] Running tiered classification (L1 → L2 → L3)...")
    classification = classify_tiered(error_details, pipeline_metadata)

    # Step 4: Store in ChromaDB with classification metadata
    store_error(
        error_id=run_id,
        error_text=error_text,
        metadata={
            "pipeline_name": pipeline_name,
            "error_type": f"{classification['error_type']} - {classification['error_type_name']}",
            "error_type_name": classification["error_type_name"],
            "error_message": error_text[:500],
            "root_cause": classification["root_cause_summary"][:500],
            "action_taken": "pending",
            "priority": classification["priority"],
            "timestamp": error_details.get("timestamp", "")
        },
        namespace=pipeline_name
    )

    # Step 5: Determine action (but DON'T execute it — the listener does that)
    error_type = classification["error_type"]
    error_type_name = classification["error_type_name"]
    is_auto = error_type in (3, 4, 5)

    if is_auto:
        action = "auto_restart"
        strategy, wait_secs = RESTART_STRATEGIES.get(error_type, ("Retry pipeline", 60))
        print(f"   [CLASSIFY] Type {error_type} ({error_type_name}) → auto-recoverable")
        print(f"   [STRATEGY] {strategy} (wait {wait_secs}s before restart)")
    else:
        action = "escalate"
        wait_secs = 0
        print(f"   [CLASSIFY] Type {error_type} ({error_type_name}) → escalation required")

    # Log to SQLite error history
    log_error(pipeline_name, run_id, error_type, error_text[:1000], action, error_type_name)

    print(f"   [DONE] Classification complete for run: {run_id}")

    return {
        "action": action,
        "error_type": error_type,
        "error_type_name": error_type_name,
        "classification": classification,
        "pipeline_metadata": pipeline_metadata,
        "wait_seconds": wait_secs,
    }


def handle_escalation(error_details, classification, pipeline_metadata, reason=None):
    """
    Handle non-recoverable errors (Types 1, 2, 6) or max-retry-exhausted errors:
    generate doc + email notification.

    Called by the SQL listener after classification or after max retries exhausted.
    """
    error_type = classification["error_type"]
    type_name = classification["error_type_name"]
    pipeline_name = error_details.get("pipeline_name", "unknown")

    if reason == "max_retries_exhausted":
        print(f"   [ESCALATE] MAX RETRIES EXHAUSTED - Type {error_type} ({type_name})")
    else:
        print(f"   [ESCALATE] ESCALATION REQUIRED - Type {error_type} ({type_name})")

    # Generate error resolution document
    doc_path = None
    print(f"   [DOC] Generating error resolution document...")
    try:
        from listener.doc_generator import generate_error_document
        payload = {
            "pipeline_name": pipeline_name,
            "run_id": error_details.get("run_id", "unknown"),
            "timestamp": error_details.get("timestamp", ""),
            "error_message": error_details.get("combined_error", ""),
            "classification": classification,
            "failed_activities": error_details.get("failed_activities", []),
        }

        # Add retry info if this is a max-retries escalation
        if reason == "max_retries_exhausted":
            payload["retry_info"] = error_details.get("retry_info", {})

        doc_path = generate_error_document(payload)
        print(f"   [DOC] Document saved: {doc_path}")
    except Exception as e:
        print(f"   [WARN] Doc generation skipped: {str(e)}")

    # Send email notification
    recipient = (pipeline_metadata or {}).get("owner_email", NotificationConfig.NOTIFY_RECIPIENT)
    _send_email_notification(pipeline_name, classification, error_details, doc_path, recipient, reason)


def _send_email_notification(pipeline_name, classification, error_details, doc_path, recipient, reason=None):
    """Send email notification with PDF attachment about the escalated error."""
    smtp_email = NotificationConfig.SMTP_EMAIL
    smtp_password = NotificationConfig.SMTP_PASSWORD
    recipient = recipient or NotificationConfig.NOTIFY_RECIPIENT

    if not all([smtp_email, smtp_password, recipient]):
        print("   [WARN] Email not configured (missing SMTP credentials in .env)")
        return

    error_type = classification["error_type"]
    type_name = classification["error_type_name"]
    priority = classification["priority"]
    root_cause = classification.get("root_cause_summary", "Unknown")

    # Adjust subject for max-retries escalation
    if reason == "max_retries_exhausted":
        subject = f"[{priority}] ADF RESTART FAILED ({MAX_RESTART_ATTEMPTS}x): {pipeline_name} - {type_name}"
    else:
        subject = f"[{priority}] ADF Pipeline Alert: {pipeline_name} - {type_name}"

    # Build the escalation reason text for the email
    escalation_note = ""
    if reason == "max_retries_exhausted":
        escalation_note = f"""
        <tr style="background: #fff3cd;">
            <td style="padding: 8px; font-weight: bold; color: #856404;">Restart Attempts</td>
            <td style="padding: 8px; color: #856404;">
                {MAX_RESTART_ATTEMPTS} restart attempts failed. Manual intervention required.
            </td>
        </tr>
        """

    html_body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; color: #333;">
        <h2 style="color: #d32f2f;">Pipeline Error — {'Restart Failed' if reason == 'max_retries_exhausted' else 'Escalation Required'}</h2>
        <table style="border-collapse: collapse; width: 100%; max-width: 600px;">
            <tr style="background: #f5f5f5;">
                <td style="padding: 8px; font-weight: bold;">Pipeline</td>
                <td style="padding: 8px;">{pipeline_name}</td>
            </tr>
            <tr>
                <td style="padding: 8px; font-weight: bold;">Error Type</td>
                <td style="padding: 8px;">Type {error_type} - {type_name}</td>
            </tr>
            <tr style="background: #f5f5f5;">
                <td style="padding: 8px; font-weight: bold;">Priority</td>
                <td style="padding: 8px;">{priority}</td>
            </tr>
            <tr>
                <td style="padding: 8px; font-weight: bold;">Run ID</td>
                <td style="padding: 8px;">{error_details.get('run_id', 'N/A')}</td>
            </tr>
            <tr style="background: #f5f5f5;">
                <td style="padding: 8px; font-weight: bold;">Timestamp</td>
                <td style="padding: 8px;">{error_details.get('timestamp', 'N/A')}</td>
            </tr>
            <tr>
                <td style="padding: 8px; font-weight: bold;">Root Cause</td>
                <td style="padding: 8px;">{root_cause}</td>
            </tr>
            {escalation_note}
        </table>
        <p style="margin-top: 16px;"><b>Please see the attached PDF for the full error resolution report.</b></p>
        <hr style="margin-top: 20px;">
        <p style="color: #888; font-size: 12px;">
            Sent by Self-Healing ADF Pipeline System
        </p>
    </body>
    </html>
    """

    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = smtp_email
    msg["To"] = recipient
    msg.attach(MIMEText(html_body, "html"))

    # Attach PDF if it was generated
    if doc_path and os.path.exists(doc_path):
        with open(doc_path, "rb") as f:
            pdf_attachment = MIMEBase("application", "pdf")
            pdf_attachment.set_payload(f.read())
            encoders.encode_base64(pdf_attachment)
            pdf_filename = os.path.basename(doc_path)
            pdf_attachment.add_header(
                "Content-Disposition",
                f"attachment; filename={pdf_filename}"
            )
            msg.attach(pdf_attachment)
            print(f"   [ATTACH] PDF attached: {pdf_filename}")

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(smtp_email, smtp_password)
            server.send_message(msg)
        print(f"   [EMAIL] Email with PDF sent to {recipient}")
    except smtplib.SMTPAuthenticationError:
        print(f"   [ERROR] Email auth failed - use a Gmail App Password in .env (not your regular password)")
        print(f"           Get one at: https://myaccount.google.com/apppasswords")
    except Exception as e:
        print(f"   [ERROR] Email failed: {str(e)}")
