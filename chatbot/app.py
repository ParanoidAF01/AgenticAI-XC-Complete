"""
Chainlit Chatbot for ADF Self-Healing System.
Developers can ask questions about pipeline errors and get AI-powered answers.
"""
import chainlit as cl
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from chatbot.rag_pipeline import query


@cl.on_chat_start
async def start():
    """Runs when a user opens the chatbot."""
    await cl.Message(
        content="""# 🔧 ADF Self-Healing Assistant

Welcome! I can help you with:

- **🔍 Error Investigation**: *"Why did pipeline X fail?"*
- **🛠️ Resolution Steps**: *"How do I fix a schema mismatch error?"*
- **📊 Error Patterns**: *"Show me recent failures for pipeline Y"*
- **📋 General ADF Help**: *"What causes timeout errors in ADF?"*

> **Tip:** Mention a specific pipeline name for more targeted answers.
"""
    ).send()


@cl.on_message
async def handle_message(message: cl.Message):
    """Process each user message."""
    user_input = message.content

    # Try to extract pipeline name from the message
    pipeline_name = _extract_pipeline_name(user_input)

    # Show thinking indicator
    msg = cl.Message(content="🔍 Searching error logs and analyzing...")
    await msg.send()

    try:
        # Query the RAG pipeline
        response = query(user_input, pipeline_name=pipeline_name)

        # Update the message with the response
        msg.content = response
        await msg.update()

    except Exception as e:
        msg.content = f"❌ Sorry, I encountered an error: {str(e)}\n\nPlease try again."
        await msg.update()


def _extract_pipeline_name(text: str) -> str:
    """Try to extract a pipeline name from the user's message."""
    words = text.split()
    for word in words:
        # ADF pipelines often start with "pl_" or "pipeline_"
        if word.startswith("pl_") or word.startswith("pipeline_"):
            return word.strip("?.,!'\"")

    # Check if any word after "pipeline" is a name
    for i, word in enumerate(words):
        if word.lower() == "pipeline" and i + 1 < len(words):
            return words[i + 1].strip("?.,!'\"")

    return None
