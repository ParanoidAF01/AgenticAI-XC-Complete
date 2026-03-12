"""
Error Processor — The orchestrator of the intelligence layer.
Receives raw error details from the listener, embeds them, searches for similar errors,
classifies them via Gemini, and takes action:
  - Types 1-4 (auto-recoverable): Log as auto-restart candidate
  - Types 5-6 (non-recoverable): Generate error document + send email notification
"""
import requests
import json
import sys
import os
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


def process_error(error_details: dict):
    """
    Full error processing pipeline:
    1. Search for similar past errors in Pinecone
    2. Get pipeline metadata from SQLite
    3. Classify the error using Gemini
    4. Store the error + classification in Pinecone
    5. Log to SQLite
    6. Take action: auto-restart OR generate doc + email notification
    """
    pipeline_name = error_details.get("pipeline_name", "unknown")
    run_id = error_details.get("run_id", "unknown")
    error_text = error_details.get("combined_error", "")

    print(f"\n{'=' * 50}")
    print(f"⚡ Processing error for pipeline: {pipeline_name}")
    print(f"{'=' * 50}")

    # Step 1: Search for similar past errors
    print("   🔍 Searching for similar past errors...")
    similar_errors = search_similar_errors(
        error_text=error_text,
        namespace=pipeline_name,
        top_k=5
    )
    print(f"   📊 Found {len(similar_errors)} similar past errors.")

    # Step 2: Get pipeline metadata
    print("   📋 Fetching pipeline metadata...")
    pipeline_metadata = get_pipeline(pipeline_name)

    # Step 3: Classify the error
    print("   🧠 Classifying error with Gemini...")
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

    # Step 5: Determine action and log
    is_auto = classification["is_auto_recoverable"]
    action = "auto_restart" if is_auto else "escalate_to_human"
    log_error(pipeline_name, run_id, classification["error_type"], error_text[:1000], action)

    # Step 6: Take action based on classification
    if is_auto:
        _handle_auto_restart(error_details, classification, pipeline_metadata)
    else:
        _handle_escalation(error_details, classification, pipeline_metadata)

    print(f"   ✅ Processing complete for run: {run_id}")


def _handle_auto_restart(error_details, classification, pipeline_metadata):
    """Handle auto-recoverable errors (Types 1-4): restart the pipeline via Azure REST API."""
    error_type = classification["error_type"]
    type_name = classification["error_type_name"]
    pipeline_name = error_details.get("pipeline_name", "unknown")

    strategies = {
        1: ("Fix parameters from metadata", 30),
        2: ("Apply dataset type corrections", 30),
        3: ("Rotate expired credentials/tokens", 60),
        4: ("Enable chunking / increase timeout", 120),
    }

    strategy, wait_secs = strategies.get(error_type, ("Retry pipeline", 60))

    print(f"   🟢 AUTO-RECOVERABLE — Type {error_type} ({type_name})")
    print(f"   🔧 Strategy: {strategy}")
    print(f"   ⏱️  Wait: {wait_secs}s before restart")

    # Actually restart the pipeline via Azure REST API
    print(f"   🔄 Restarting pipeline '{pipeline_name}' via Azure REST API...")
    try:
        from listener.azure_client import restart_pipeline
        result = restart_pipeline(pipeline_name)

        if result["success"]:
            print(f"   ✅ Pipeline restarted! New Run ID: {result['run_id']}")
        else:
            print(f"   ⚠️ Restart failed: {result['message']}")
    except Exception as e:
        print(f"   ⚠️ Restart error: {str(e)}")


def _handle_escalation(error_details, classification, pipeline_metadata):
    """Handle non-recoverable errors (Types 5-6): generate doc + email notification."""
    error_type = classification["error_type"]
    type_name = classification["error_type_name"]
    pipeline_name = error_details.get("pipeline_name", "unknown")

    print(f"   🔴 ESCALATION REQUIRED — Type {error_type} ({type_name})")

    # Generate error resolution document
    doc_path = None
    print(f"   📄 Generating error resolution document...")
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
        doc_path = generate_error_document(payload)
        print(f"   📄 Document saved: {doc_path}")
    except Exception as e:
        print(f"   ⚠️ Doc generation skipped: {str(e)}")

    # Send email notification
    recipient = (pipeline_metadata or {}).get("owner_email", NotificationConfig.NOTIFY_RECIPIENT)
    _send_email_notification(pipeline_name, classification, error_details, doc_path, recipient)


def _send_email_notification(pipeline_name, classification, error_details, doc_path, recipient):
    """Send email notification with PDF attachment about the escalated error."""
    smtp_email = NotificationConfig.SMTP_EMAIL
    smtp_password = NotificationConfig.SMTP_PASSWORD
    recipient = recipient or NotificationConfig.NOTIFY_RECIPIENT

    if not all([smtp_email, smtp_password, recipient]):
        print("   ⚠️ Email not configured (missing SMTP credentials in .env)")
        return

    error_type = classification["error_type"]
    type_name = classification["error_type_name"]
    priority = classification["priority"]
    root_cause = classification.get("root_cause_summary", "Unknown")

    subject = f"[{priority}] ADF Pipeline Alert: {pipeline_name} - {type_name}"

    html_body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; color: #333;">
        <h2 style="color: #d32f2f;">Pipeline Error — Escalation Required</h2>
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
            print(f"   📎 PDF attached: {pdf_filename}")

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(smtp_email, smtp_password)
            server.send_message(msg)
        print(f"   📧 Email with PDF sent to {recipient}")
    except smtplib.SMTPAuthenticationError:
        print(f"   ⚠️ Email auth failed — use a Gmail App Password in .env (not your regular password)")
        print(f"      Get one at: https://myaccount.google.com/apppasswords")
    except Exception as e:
        print(f"   ⚠️ Email failed: {str(e)}")

