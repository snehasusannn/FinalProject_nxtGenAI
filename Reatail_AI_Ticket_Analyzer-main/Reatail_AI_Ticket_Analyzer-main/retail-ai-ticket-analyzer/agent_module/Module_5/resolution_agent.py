# ============================================================
# MODULE 5 — RESOLUTION SUGGESTION AGENT
# ============================================================

from typing import Dict
from datetime import datetime
import os
from dotenv import load_dotenv
from google import genai

# IMPORT RAG RETRIEVER FROM MODULE 2
from Module_2.retriever import retrieve_documents


load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

client = genai.Client(api_key=GOOGLE_API_KEY)


# ============================================================
# LOGGER
# ============================================================

def log_agent_action(
    ticket_id,
    agent,
    status,
    message
):

    log = {
        "ticket_id": ticket_id,
        "agent": agent,
        "status": status,
        "message": message,
        "timestamp": str(datetime.now())
    }

    print(log)


# ============================================================
# PROMPT TEMPLATE
# ============================================================

RESOLUTION_PROMPT = """
You are a retail AI support assistant.

Ticket Information:
Issue:
{issue}

Category:
{category}

Severity:
{severity}

Retrieved SOP Context:
{context}

Instructions:
- Suggest a concise resolution
- Use SOP context
- Mention escalation if needed
"""



def generate_resolution(prompt: str) -> str:

    try:

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )

        return response.text.strip()

    except Exception as e:
        print("LLM ERROR:", e)

    return (
        "Unable to generate AI resolution. "
        "Escalate to human support."
    )


# ============================================================
# MAIN AGENT FUNCTION
# ============================================================

def suggest_resolution(ticket: Dict) -> Dict:
    """
    Reads:
      - category
      - severity
      - issue_description

    Calls:
      - retrieve_documents() from Module 2

    Writes:
      - retrieved_docs
      - suggested_resolution
      - resolution_source
    """

    # --------------------------------------------------------
    # HANDLE EMPTY / NONE INPUT
    # --------------------------------------------------------

    if not ticket:

        return {
            "suggested_resolution":
                "Escalate to human support agent.",

            "resolution_source":
                "fallback",

            "error_log": [
                {
                    "agent": "resolution",
                    "error": "Received empty ticket input"
                }
            ]
        }

    try:

        # ----------------------------------------------------
        # ENSURE ERROR LOG EXISTS
        # ----------------------------------------------------

        ticket.setdefault("error_log", [])

        issue = ticket.get("issue_description", "")
        category = ticket.get("category", "unclassified")
        severity = ticket.get("severity", "medium")

        # ----------------------------------------------------
        # STEP 1 — RAG DOCUMENT RETRIEVAL
        # ----------------------------------------------------

        docs = retrieve_documents(
            issue_description=issue,
            category=category
        )

        # WRITE ONLY ASSIGNED FIELD
        ticket["retrieved_docs"] = docs

        # ----------------------------------------------------
        # STEP 2 — GENERATE RESOLUTION
        # ----------------------------------------------------

        if docs:

            # Combine retrieved chunks into context
            context = "\n".join([
                doc["content"]
                for doc in docs
            ])

            # Build prompt
            prompt = RESOLUTION_PROMPT.format(
                issue=issue,
                category=category,
                severity=severity,
                context=context
            )

            # Generate response 
            resolution = generate_resolution(prompt)

            # WRITE ONLY ASSIGNED FIELDS
            ticket["suggested_resolution"] = resolution
            ticket["resolution_source"] = "rag_doc"

        else:

            # ------------------------------------------------
            # FALLBACK WHEN NO DOCUMENTS FOUND
            # ------------------------------------------------

            ticket["suggested_resolution"] = (
                "Restart the affected system and verify "
                "network/device connectivity. "
                "If the issue persists, escalate to "
                "human support."
            )

            ticket["resolution_source"] = "llm_generated"

        # ----------------------------------------------------
        # LOG SUCCESS
        # ----------------------------------------------------

        log_agent_action(
            ticket.get("ticket_id", "unknown"),
            "resolution",
            "success",
            "Resolution generated successfully"
        )

    except Exception as e:

        # ----------------------------------------------------
        # SAFE FALLBACK ON FAILURE
        # ----------------------------------------------------

        ticket["suggested_resolution"] = (
            "Escalate to human support agent."
        )

        ticket["resolution_source"] = "fallback"

        ticket.setdefault("error_log", []).append({
            "agent": "resolution",
            "error": str(e)
        })

        # ----------------------------------------------------
        # LOG FAILURE
        # ----------------------------------------------------

        log_agent_action(
            ticket.get("ticket_id", "unknown"),
            "resolution",
            "failure",
            str(e)
        )

    return ticket

# ============================================================
# TEST MODULE
# ============================================================

if __name__ == "__main__":

    sample_ticket = {
        "ticket_id": "TKT-1042",
        "timestamp": "2025-05-20T10:30:00",
        "channel": "app",
        "store_id": "STORE-021",
        "customer_id": "CUST-887",
        "customer_name": "Ravi Kumar",

        "issue_description":
            "Damaged product recieved",

        "category": "product_defect",
        "confidence_score": 0.91,

        "severity": "high",
        "severity_reason": "POS stopped during business hours",
        "escalate": False,

        "retrieved_docs": [],
        "suggested_resolution": None,
        "resolution_source": None,

        "human_approved": None,
        "approver_notes": None,
        "final_status": None,

        "error_log": [],
        "retry_count": 0
    }

    result = suggest_resolution(sample_ticket)

    print("\n================ FINAL OUTPUT ================\n")

    for key, value in result.items():
        print(f"{key}: {value}")