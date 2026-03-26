"""
Error Processor — The orchestrator of the intelligence layer.
Receives raw error details from the listener, embeds them, searches for similar errors,
classifies them via LLM, and takes action:
  - Types 1-4 (auto-recoverable): Attempt restart (max 3 per pipeline+error_type)
  - Types 5-6 (non-recoverable): Generate error document + send email notification
  - After 3 failed restart attempts: Escalate (same as Types 5-6)
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

from intelligence.pinecone_store import store_error, search_similar_errors
from intelligence.error_classifier import classify_error
from config.metadata_store import get_pipeline, log_error
from config.settings import NotificationConfig


# ── Restart Tracker ────────────────────────────────────────────
MAX_RESTART_ATTEMPTS = 3


class RestartTracker:
    """
    Tracks restart attempts per (pipeline_name, error_type) pair.
    Prevents infinite restart loops by capping retries at MAX_RESTART_ATTEMPTS.

    Also tracks which run IDs were created by restarts, so the listener
    can link child runs back to the original failure.
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


def process_error(error_details: dict):
    """
    Full error processing pipeline:
    1. Search for similar past errors in Pinecone
    2. Get pipeline metadata from SQLite
    3. Classify the error using LLM
    4. Store the error + classification in Pinecone
    5. Log to SQLite
    6. Take action: auto-restart (if attempts < 3) OR escalate
    """
    pipeline_name = error_details.get("pipeline_name", "unknown")
    run_id = error_details.get("run_id", "unknown")
    error_text = error_details.get("combined_error", "")

    print(f"\n{'=' * 50}")
    print(f"[PROCESS] Processing error for pipeline: {pipeline_name}")
    print(f"{'=' * 50}")

    # Step 1: Search for similar past errors
    print("   [SEARCH] Searching for similar past errors...")
    similar_errors = search_similar_errors(
        error_text=error_text,
        namespace=pipeline_name,
        top_k=5
    )
    print(f"   [SEARCH] Found {len(similar_errors)} similar past errors.")

    # Step 2: Get pipeline metadata
    print("   [META] Fetching pipeline metadata...")
    pipeline_metadata = get_pipeline(pipeline_name)

    # Step 3: Classify the error
    print("   [CLASSIFY] Classifying error with LLM...")
    classification = classify_error(error_details, similar_errors, pipeline_metadata)

    # Step 4: Store in Pinecone with classification metadata
    store_error(
        error_id=run_id,
        error_text=error_text,
        metadata={
            "pipeline_name": pipeline_name,
            "error_type": classification["error_type"],
            "error_type_name": classification["error_type_name"],
            "error_message": error_text[:500],
            "root_cause": classification["root_cause_summary"][:500],
            "action_taken": "pending",
            "priority": classification["priority"],
            "timestamp": error_details.get("timestamp", "")
        },
        namespace=pipeline_name
    )

    # Step 5: Determine action
    # Types 3, 4, 5 are auto-recoverable (transient/environment issues)
    # Types 1, 2, 6 require immediate escalation (definition-level / infrastructure bugs)
    error_type = classification["error_type"]
    is_auto = error_type in (3, 4, 5)

    if is_auto:
        # Check restart attempts before restarting
        attempt_count = restart_tracker.get_attempt_count(pipeline_name, error_type)
        can_restart = restart_tracker.can_restart(pipeline_name, error_type)

        if can_restart:
            action = "auto_restart"
            log_error(pipeline_name, run_id, error_type, error_text[:1000], action)
            _handle_auto_restart(error_details, classification, pipeline_metadata)
        else:
            # Max retries exhausted — escalate
            action = "escalate_max_retries"
            log_error(pipeline_name, run_id, error_type, error_text[:1000], action)
            print(f"   [LIMIT] Restart limit reached ({MAX_RESTART_ATTEMPTS}/{MAX_RESTART_ATTEMPTS}) "
                  f"for pipeline '{pipeline_name}' + Type {error_type}")
            print(f"   [LIMIT] Escalating to human review instead of restarting.")
            _handle_escalation(error_details, classification, pipeline_metadata,
                               reason="max_retries_exhausted")
            # Reset the counter after escalation
            restart_tracker.reset(pipeline_name, error_type)
    else:
        action = "escalate_to_human"
        log_error(pipeline_name, run_id, error_type, error_text[:1000], action)
        _handle_escalation(error_details, classification, pipeline_metadata)

    print(f"   [DONE] Processing complete for run: {run_id}")


def _handle_auto_restart(error_details, classification, pipeline_metadata):
    """Handle auto-recoverable errors (Types 3, 4, 5): restart the pipeline via Azure REST API."""
    error_type = classification["error_type"]
    type_name = classification["error_type_name"]
    pipeline_name = error_details.get("pipeline_name", "unknown")
    run_id = error_details.get("run_id", "unknown")

    # Get current attempt info
    attempt_count = restart_tracker.get_attempt_count(pipeline_name, error_type) + 1

    strategies = {
        3: ("Retry after credential rotation/refresh", 60),
        4: ("Retry with delay for transient timeout", 120),
        5: ("Retry after server recovery window", 90),
    }

    strategy, wait_secs = strategies.get(error_type, ("Retry pipeline", 60))

    print(f"   [AUTO-RECOVER] Type {error_type} ({type_name})")
    print(f"   [ATTEMPT] Restart attempt {attempt_count}/{MAX_RESTART_ATTEMPTS}")
    print(f"   [STRATEGY] {strategy}")
    print(f"   [WAIT] {wait_secs}s before restart")

    # Wait before restart
    time.sleep(wait_secs)

    # Actually restart the pipeline via Azure REST API
    print(f"   [RESTART] Restarting pipeline '{pipeline_name}' via Azure REST API...")
    try:
        from listener.azure_client import restart_pipeline
        result = restart_pipeline(pipeline_name)

        if result["success"]:
            new_run_id = result["run_id"]
            print(f"   [OK] Pipeline restarted. New Run ID: {new_run_id}")
            print(f"   [TRACK] Tracking new run as retry child ({attempt_count}/{MAX_RESTART_ATTEMPTS})")

            # Record this restart attempt
            restart_tracker.record_restart(pipeline_name, error_type, run_id, new_run_id)
        else:
            print(f"   [WARN] Restart failed: {result['message']}")
    except Exception as e:
        print(f"   [ERROR] Restart error: {str(e)}")


def _handle_escalation(error_details, classification, pipeline_metadata, reason=None):
    """
    Handle non-recoverable errors (Types 5-6) or max-retry-exhausted errors:
    generate doc + email notification.
    """
    error_type = classification["error_type"]
    type_name = classification["error_type_name"]
    pipeline_name = error_details.get("pipeline_name", "unknown")

    if reason == "max_retries_exhausted":
        tracker_info = restart_tracker.get_info(pipeline_name, error_type)
        print(f"   [ESCALATE] MAX RETRIES EXHAUSTED - Type {error_type} ({type_name})")
        print(f"   [ESCALATE] Failed {tracker_info['count']} times. "
              f"Run IDs: {tracker_info.get('original_run_id', 'N/A')} -> "
              f"{tracker_info.get('child_run_ids', [])}")
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
            tracker_info = restart_tracker.get_info(pipeline_name, error_type)
            payload["retry_info"] = {
                "max_retries": MAX_RESTART_ATTEMPTS,
                "attempts": tracker_info["count"],
                "original_run_id": tracker_info["original_run_id"],
                "child_run_ids": tracker_info["child_run_ids"]
            }

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
