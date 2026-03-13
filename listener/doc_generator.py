"""
Error Document Generator.
Creates detailed error reports as professional PDF documents using fpdf2.
Company's LLM generates the content; fpdf2 renders the final PDF.
"""
from openai import OpenAI
import json
import os
import re
from datetime import datetime
from fpdf import FPDF
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config.settings import CompanyAPIConfig

# Initialize the OpenAI-compatible chat client
client = OpenAI(
    base_url=CompanyAPIConfig.BASE_URL,
    api_key=CompanyAPIConfig.API_KEY
)
CHAT_MODEL = CompanyAPIConfig.CHAT_MODEL

DOC_OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "docs")
os.makedirs(DOC_OUTPUT_DIR, exist_ok=True)

DOC_PROMPT = """Generate a detailed ADF pipeline error resolution document.
Return ONLY plain text (no markdown formatting, no # or ** or ``` symbols).
Use simple numbered lists and clear section labels.

Sections to include:

SUMMARY
Brief 2-3 line summary of what happened.

ERROR DETAILS
- Pipeline: {pipeline_name}
- Run ID: {run_id}
- Time: {timestamp}
- Error Type: {error_type_name}
- Priority: {priority}

ROOT CAUSE ANALYSIS
Detailed explanation of why this error occurred (3-5 sentences).

FAILED ACTIVITIES
List each failed activity with its error message.

RESOLUTION STEPS
Numbered step-by-step instructions on how to fix this error.
Be specific to ADF — mention exact portal navigation, code changes, or config fixes.

PREVENTION RECOMMENDATIONS
How to prevent this error from happening again.

IMPACT ASSESSMENT
What data or downstream systems are affected by this failure.

---

Error context:
Pipeline: {pipeline_name}
Error Message: {error_message}
Failed Activities: {failed_activities}
Classification: {classification}
"""


class ErrorReportPDF(FPDF):
    """Custom PDF class for error reports with header/footer."""

    def __init__(self, pipeline_name, error_type, priority):
        super().__init__()
        self.pipeline_name = pipeline_name
        self.error_type = error_type
        self.priority = priority

    def header(self):
        # Red banner
        self.set_fill_color(200, 40, 40)
        self.rect(0, 0, 210, 20, 'F')
        self.set_font('Helvetica', 'B', 14)
        self.set_text_color(255, 255, 255)
        self.set_y(4)
        self.cell(0, 12, 'ADF Pipeline Error Report', align='C')

        # Sub-header
        self.set_fill_color(50, 50, 50)
        self.rect(0, 20, 210, 10, 'F')
        self.set_font('Helvetica', '', 9)
        self.set_y(21)
        self.cell(0, 8,
                  f'{self.pipeline_name}  |  {self.error_type}  |  {self.priority}  |  '
                  f'Generated: {datetime.now().strftime("%Y-%m-%d %H:%M")}',
                  align='C')
        self.ln(15)

    def footer(self):
        self.set_y(-15)
        self.set_font('Helvetica', 'I', 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10,
                  f'Self-Healing ADF Pipeline System  |  Page {self.page_no()}/{{nb}}',
                  align='C')

    def add_section_title(self, title):
        """Add a blue section header."""
        self.set_font('Helvetica', 'B', 12)
        self.set_text_color(30, 80, 160)
        self.set_fill_color(230, 240, 255)
        self.cell(0, 8, f'  {title}', ln=True, fill=True)
        self.ln(2)

    def add_body_text(self, text):
        """Add paragraph text."""
        self.set_font('Helvetica', '', 10)
        self.set_text_color(40, 40, 40)
        # Clean up markdown artifacts
        text = re.sub(r'[#*`]', '', text)
        text = text.encode('latin-1', 'replace').decode('latin-1')
        self.multi_cell(0, 5, text)
        self.ln(2)

    def add_key_value(self, key, value):
        """Add a bold key: value pair."""
        self.set_font('Helvetica', 'B', 10)
        self.set_text_color(60, 60, 60)
        self.cell(45, 6, f'{key}:')
        self.set_font('Helvetica', '', 10)
        self.set_text_color(40, 40, 40)
        value_str = str(value).encode('latin-1', 'replace').decode('latin-1')
        self.cell(0, 6, value_str, ln=True)

    def add_error_box(self, error_text):
        """Add a highlighted error message box."""
        self.set_fill_color(255, 240, 240)
        self.set_draw_color(200, 40, 40)
        self.set_font('Courier', '', 9)
        self.set_text_color(150, 30, 30)
        error_text = error_text.encode('latin-1', 'replace').decode('latin-1')
        self.multi_cell(0, 4.5, error_text, border=1, fill=True)
        self.ln(3)

    def add_numbered_list(self, items):
        """Add a numbered list of items."""
        self.set_font('Helvetica', '', 10)
        self.set_text_color(40, 40, 40)
        for i, item in enumerate(items, 1):
            item_clean = re.sub(r'^\d+[\.\)]\s*', '', item.strip())
            item_clean = re.sub(r'[#*`]', '', item_clean)
            item_clean = item_clean.encode('latin-1', 'replace').decode('latin-1')
            if item_clean:
                self.set_font('Helvetica', 'B', 10)
                self.cell(8, 5, f'{i}.')
                self.set_font('Helvetica', '', 10)
                self.multi_cell(0, 5, f' {item_clean}')
                self.ln(1)


def generate_error_document(payload: dict) -> str:
    """
    Generate a detailed error document as PDF using Company LLM + fpdf2.
    Returns the path to the generated PDF file.
    """
    classification = payload.get("classification", {})
    pipeline_name = payload.get("pipeline_name", "Unknown")
    error_type_name = classification.get("error_type_name", "Unknown")
    priority = classification.get("priority", "P3")

    # Generate content with company's LLM
    prompt = DOC_PROMPT.format(
        pipeline_name=pipeline_name,
        run_id=payload.get("run_id", "Unknown"),
        timestamp=payload.get("timestamp", "Unknown"),
        error_type_name=error_type_name,
        priority=priority,
        error_message=payload.get("error_message", "No message"),
        failed_activities=json.dumps(payload.get("failed_activities", []), indent=2),
        classification=json.dumps(classification, indent=2)
    )

    response = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )
    doc_content = response.choices[0].message.content

    # Build PDF
    pdf = ErrorReportPDF(pipeline_name, error_type_name, priority)
    pdf.alias_nb_pages()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=20)

    # Error Details section
    pdf.add_section_title("ERROR DETAILS")
    pdf.add_key_value("Pipeline", pipeline_name)
    pdf.add_key_value("Run ID", payload.get("run_id", "N/A"))
    pdf.add_key_value("Timestamp", payload.get("timestamp", "N/A"))
    pdf.add_key_value("Error Type", f"Type {classification.get('error_type', '?')} - {error_type_name}")
    pdf.add_key_value("Priority", priority)
    pdf.add_key_value("Root Cause", classification.get("root_cause_summary", "N/A"))
    pdf.ln(3)

    # Error Message box
    pdf.add_section_title("ERROR MESSAGE")
    error_msg = payload.get("error_message", "N/A")[:500]
    pdf.add_error_box(error_msg)

    # Failed Activities
    activities = payload.get("failed_activities", [])
    if activities:
        pdf.add_section_title("FAILED ACTIVITIES")
        for act in activities:
            pdf.add_key_value("Activity", act.get("activity_name", "N/A"))
            pdf.add_key_value("Type", act.get("activity_type", "N/A"))
            pdf.add_key_value("Error Code", act.get("error_code", "N/A"))
            pdf.add_body_text(f"Message: {act.get('error_message', 'N/A')}")
            pdf.ln(1)

    # Parse LLM response into sections and render
    sections = _parse_sections(doc_content)

    for section_name, section_content in sections.items():
        if section_name.upper() in ["ERROR DETAILS", "FAILED ACTIVITIES"]:
            continue  # Already rendered above

        pdf.add_section_title(section_name.upper())

        # Check if content has numbered items
        lines = [l.strip() for l in section_content.strip().split('\n') if l.strip()]
        numbered = [l for l in lines if re.match(r'^\d+[\.\)]', l)]

        if len(numbered) > 2:
            pdf.add_numbered_list(numbered)
        else:
            pdf.add_body_text(section_content.strip())

    # Save PDF
    filename = (
        f"error_report_{pipeline_name}"
        f"_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    )
    filepath = os.path.join(DOC_OUTPUT_DIR, filename)
    pdf.output(filepath)

    print(f"   [DOC] PDF report saved: {filepath}")
    return filepath


def _parse_sections(text):
    """Parse LLM's plain-text output into named sections."""
    sections = {}
    current_section = "SUMMARY"
    current_lines = []

    section_keywords = [
        "SUMMARY", "ROOT CAUSE ANALYSIS", "ROOT CAUSE", "RESOLUTION STEPS",
        "PREVENTION RECOMMENDATIONS", "PREVENTION", "IMPACT ASSESSMENT",
        "IMPACT", "FAILED ACTIVITIES", "ERROR DETAILS"
    ]

    for line in text.split('\n'):
        clean = re.sub(r'[#*`]', '', line).strip()
        upper = clean.upper().rstrip(':')

        if upper in section_keywords:
            if current_lines:
                sections[current_section] = '\n'.join(current_lines)
            current_section = upper
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        sections[current_section] = '\n'.join(current_lines)

    return sections
