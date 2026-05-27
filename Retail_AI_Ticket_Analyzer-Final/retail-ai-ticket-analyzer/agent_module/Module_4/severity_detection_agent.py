# ============================================================
# IMPORTS
# ============================================================

import os
import json
import time
import logging
import pandas as pd
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from openai import AzureOpenAI
from dotenv import load_dotenv

# ============================================================
# ENV + LOGGING SETUP
# ============================================================

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("severity_agent")

# ============================================================
# AZURE OPENAI SETUP
# ============================================================

client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"),
)
AZURE_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")

# ============================================================
# CONSTANTS — aligned with contract.txt enums
# ============================================================

SEVERITY_LEVELS = ["critical", "high", "medium", "low"]

ISSUE_TYPE_TO_CATEGORY = {
    "POS - Transaction Error":         "pos_failure",
    "POS - Return Error":              "pos_failure",
    "Hardware - POS Malfunction":      "pos_failure",
    "Hardware - Payment Terminal":     "payment_gateway_failure",
    "Network - System Slowdown":       "network_outage",
    "Security - Voided Transactions":  "fraud_alert",
    "E-commerce - Website Bug":        "inventory_sync_failure",
    "E-commerce - Email Notification": "order_delay",
    "E-commerce - Product Display":    "pricing_mismatch",
    "Supply Chain - Delivery Shortage":"order_delay",
    "Promotions - Discount Error":     "pricing_mismatch",
    "Pricing - Scan Error":            "pricing_mismatch",
    "Inventory - Discrepancy":         "inventory_sync_failure",
    "Integration - BOPIS Sync":        "inventory_sync_failure",
    "Software - CRM Performance":      "network_outage",
    "Reporting - Missing Data":        "inventory_sync_failure",
    "Reporting - Data Inaccuracy":     "inventory_sync_failure",
    "Hardware - Handheld Scanner":     "scanner_issue",
    "Hardware - Printer Issue":        "scanner_issue",
    "Access - User Account":           "account_issue",
}

INCIDENT_TYPE_TO_CATEGORY = {
    "POS System Outage":                             "pos_failure",
    "Online Payment Gateway Interruption":           "payment_gateway_failure",
    "Store Network Connectivity Loss":               "network_outage",
    "Digital Signage Network Outage":                "network_outage",
    "Warehouse Management System (WMS) Discrepancy": "inventory_sync_failure",
    "Returns Processing System Interruption":        "pos_failure",
    "E-commerce Platform Performance Degradation":   "network_outage",
    "Inbound Logistics Delay":                       "order_delay",
    "Payment Terminal Malfunction (In-Store)":       "payment_gateway_failure",
    "Supplier Fulfillment Failure":                  "order_delay",
}

CRITICAL_KEYWORDS = [
    "all stores",
    "payment gateway",
    "payment gateway down",
    "payment gateway failure",
    "network outage",
    "server crash",
    "checkout blocked",
    "security breach",
    "data leak",
    "fraud",
    "voided transactions",
    "pos system outage",
    "complete loss",
    "operations are suspended",
    "revenue completely blocked",
]

HIGH_KEYWORDS = [
    "multiple counters",
    "multiple terminals",
    "multiple stores",
    "inventory sync",
    "checkout slow",
    "scanner offline",
    "7 out of 10",
    "50+ stores",
    "payment processing failure",
    "bopis",
    "system-wide",
    "all terminals",
    "significant delays",
]

ESCALATION_CATEGORIES = [
    "fraud_alert",
    "payment_gateway_failure",
    "network_outage",
]

SLA_BREACH_SEVERITY_BUMP = {
    "low":    "medium",
    "medium": "high",
}

RATE_LIMIT_DELAY = 4


# ============================================================
# TICKET LOADERS
# ============================================================

def load_tickets_from_csv(
    filepath: str = "data/retail_tickets.csv"
) -> list[dict]:
    df = pd.read_csv(filepath)
    tickets = []

    for _, row in df.iterrows():
        issue_type = str(row.get("issue_type", ""))
        category = ISSUE_TYPE_TO_CATEGORY.get(issue_type, "unclassified")

        ticket = {
            "ticket_id":            str(row.get("ticket_id", "")),
            "timestamp":            str(row.get("created_at", "")),
            "channel":              str(row.get("channel", "app")).lower(),
            "store_id":             str(row.get("location", "UNKNOWN")),
            "customer_id":          str(row.get("customer_id", "")),
            "customer_name":        "",
            "issue_description":    str(row.get("ticket_text", "")),
            "category":             category,
            "confidence_score":     0.85,
            "severity":             None,
            "severity_reason":      None,
            "escalate":             None,
            "retrieved_docs":       [],
            "suggested_resolution": None,
            "resolution_source":    None,
            "human_approved":       None,
            "approver_notes":       None,
            "final_status":         None,
            "error_log":            [],
            "retry_count":          0,
            "_sla_breach":          str(row.get("sla_breach", "No")),
            "_priority":            str(row.get("priority", "Medium")),
            "_customer_tier":       str(row.get("customer_tier", "Silver")),
            "_requires_escalation": str(row.get("requires_escalation", "No")),
            "_system_status":       "Operational",
        }
        tickets.append(ticket)

    logger.info("Loaded %d tickets from %s", len(tickets), filepath)
    return tickets


def load_incidents_from_csv(
    filepath: str = "data/retail_incident_logs.csv"
) -> list[dict]:
    df = pd.read_csv(filepath)
    tickets = []

    for _, row in df.iterrows():
        incident_type = str(row.get("incident_type", ""))
        category = INCIDENT_TYPE_TO_CATEGORY.get(incident_type, "unclassified")

        severity_hint = str(row.get("severity", "medium")).lower()
        if severity_hint not in SEVERITY_LEVELS:
            severity_hint = "medium"

        ticket = {
            "ticket_id":            str(row.get("log_id", "")),
            "timestamp":            str(row.get("timestamp", "")),
            "channel":              "in_store",
            "store_id":             str(row.get("location", "UNKNOWN")),
            "customer_id":          "INTERNAL",
            "customer_name":        "Operations Team",
            "issue_description":    str(row.get("description", "")),
            "category":             category,
            "confidence_score":     0.90,
            "severity":             None,
            "severity_reason":      None,
            "escalate":             None,
            "retrieved_docs":       [],
            "suggested_resolution": None,
            "resolution_source":    None,
            "human_approved":       None,
            "approver_notes":       None,
            "final_status":         None,
            "error_log":            [],
            "retry_count":          0,
            "_sla_breach":                 "No",
            "_priority":                   severity_hint.capitalize(),
            "_customer_tier":              "Internal",
            "_requires_escalation":        "No",
            "_system_status":              str(row.get("system_status", "Operational")),
            "_affected_team":              str(row.get("affected_team", "")),
            "_incident_severity_hint":     severity_hint,
        }
        tickets.append(ticket)

    logger.info("Loaded %d incidents from %s", len(tickets), filepath)
    return tickets


# ============================================================
# ACCEPT TICKET FROM MODULE 3 (Poojari)
# ============================================================

def accept_ticket_from_classifier(ticket: dict) -> dict:
    if not ticket.get("category"):
        logger.warning(
            "ticket_id=%s has no category — defaulting to unclassified.",
            ticket.get("ticket_id")
        )
        ticket["category"] = "unclassified"

    if ticket.get("confidence_score") is None:
        logger.warning(
            "ticket_id=%s has no confidence_score — defaulting to 0.5",
            ticket.get("ticket_id")
        )
        ticket["confidence_score"] = 0.5

    ticket.setdefault("_sla_breach", "No")
    ticket.setdefault("_priority", "Medium")
    ticket.setdefault("_customer_tier", "Silver")
    ticket.setdefault("_requires_escalation", "No")
    ticket.setdefault("_system_status", "Operational")

    return ticket


# ============================================================
# PROMPT BUILDER
# ============================================================

def _build_severity_prompt(ticket: dict) -> str:
    extra_context = ""

    if ticket.get("_sla_breach", "No") == "Yes":
        extra_context += "\n- SLA has already been breached for this ticket."

    if ticket.get("_customer_tier") == "Platinum":
        extra_context += (
            "\n- This is a Platinum-tier customer — higher sensitivity required."
        )

    system_status = ticket.get("_system_status", "Operational")
    if system_status == "Down":
        extra_context += "\n- Affected system is currently fully DOWN."
    elif system_status == "Partially Down":
        extra_context += "\n- Affected system is Partially Down."

    if str(ticket.get("_priority", "")).lower() == "critical":
        extra_context += "\n- Ticket was pre-flagged as Critical priority."

    return f"""
You are an enterprise retail incident severity analyst.

Your task:
Determine the severity level of this retail support incident.

TICKET DETAILS:
- Issue Description: {ticket.get("issue_description", "N/A")}
- Category: {ticket.get("category", "unclassified")}
- Channel: {ticket.get("channel", "unknown")}
- Store / Location: {ticket.get("store_id", "unknown")}
- Customer ID: {ticket.get("customer_id", "unknown")}
{extra_context}

SEVERITY DEFINITIONS:
- critical : Revenue completely blocked / security breach /
             fraud / all stores or payment systems down /
             major outage affecting all operations
- high     : Major operational disruption / multiple customers
             impacted / multiple systems or terminals affected
- medium   : Partial disruption / limited business impact /
             single system or counter affected
- low      : Minor issue / cosmetic or UI bug /
             no immediate business impact

PRIORITIZE:
- Operational impact (storewide > multi-terminal > single)
- Revenue loss (payment systems down = critical)
- Customer impact (Platinum tier = higher sensitivity)
- SLA breach status
- Fraud and security risk

Respond ONLY with valid JSON. No explanation outside JSON.

FORMAT:
{{
    "severity": "<critical|high|medium|low>",
    "severity_reason": "<one business-aware sentence>"
}}
""".strip()


# ============================================================
# AZURE OPENAI CALL
# ============================================================

def _call_azure_openai(ticket: dict) -> dict:
    """
    Calls real Azure OpenAI API.
    Model: gpt-4o (via Azure deployment)
    Uses json_object response format for guaranteed valid JSON.
    """
    prompt = _build_severity_prompt(ticket)

    response = client.chat.completions.create(
        model=AZURE_DEPLOYMENT,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        max_tokens=300,
        temperature=0,
    )

    raw = response.choices[0].message.content.strip()

    # json_object mode guarantees valid JSON — no markdown stripping needed
    parsed = json.loads(raw)
    severity = parsed.get("severity", "").lower()
    reason = parsed.get("severity_reason", "No reason generated.")

    if severity not in SEVERITY_LEVELS:
        raise ValueError(f"Invalid severity from LLM: '{severity}'")

    return {"severity": severity, "severity_reason": reason}


# ============================================================
# RETRY WITH RATE LIMIT HANDLING
# ============================================================

def _retry_openai_call(
    ticket: dict,
    retries: int = 3
) -> dict:
    """
    Retries Azure OpenAI call with smart backoff.

    Handles two error types:
    1. 429 Rate limit — waits then retries
    2. Other errors  — exponential backoff (2s, 4s, 8s)
    """
    for attempt in range(retries):
        try:
            return _call_azure_openai(ticket)

        except Exception as e:
            error_str = str(e)

            retry_after = 30
            if "retry_after" in error_str.lower():
                try:
                    import re
                    match = re.search(r"retry.?after[^\d]*(\d+)", error_str, re.IGNORECASE)
                    if match:
                        retry_after = int(match.group(1)) + 2
                except Exception:
                    retry_after = 30

            if "429" in error_str or "RateLimitError" in error_str:
                logger.warning(
                    "Rate limit hit | ticket_id=%s | "
                    "waiting %ds before retry %d/%d",
                    ticket.get("ticket_id"),
                    retry_after,
                    attempt + 1,
                    retries
                )
                time.sleep(retry_after)
            else:
                wait_time = 2 ** attempt
                logger.warning(
                    "Azure OpenAI error | ticket_id=%s | "
                    "retry %d/%d | waiting %ds | error=%s",
                    ticket.get("ticket_id"),
                    attempt + 1,
                    retries,
                    wait_time,
                    error_str[:100]
                )
                time.sleep(wait_time)

    raise Exception(
        f"Azure OpenAI failed after {retries} retries for "
        f"ticket {ticket.get('ticket_id')}"
    )


# ============================================================
# BUSINESS RULE VALIDATION
# ============================================================

def _apply_business_rules(
    ticket: dict,
    llm_result: dict
) -> dict:
    severity = llm_result["severity"]
    description = ticket.get("issue_description", "").lower()
    category = ticket.get("category", "")

    # Rule 1: Fraud always critical
    if category == "fraud_alert":
        severity = "critical"
        llm_result["severity_reason"] = (
            "Fraud alert — escalated to critical per "
            "Retail Fraud Alert SOP Section 4.1."
        )

    # Rule 2: Critical keywords override LLM
    elif any(k in description for k in CRITICAL_KEYWORDS):
        severity = "critical"

    # Rule 3: High-impact keywords = minimum high
    elif any(k in description for k in HIGH_KEYWORDS):
        if severity in ["low", "medium"]:
            severity = "high"

    # Rule 4: SLA breach bumps one level
    if ticket.get("_sla_breach") == "Yes":
        bumped = SLA_BREACH_SEVERITY_BUMP.get(severity)
        if bumped:
            severity = bumped

    # Rule 5: System fully Down = minimum high
    if ticket.get("_system_status") == "Down":
        if severity in ["low", "medium"]:
            severity = "high"

    # Rule 6: Pre-flagged Critical 
    if str(ticket.get("_priority", "")).lower() == "critical":
        if severity not in ["critical", "high"]:
            severity = "high"

    llm_result["severity"] = severity
    return llm_result


# ============================================================
# RISK SCORE ENGINE
# ============================================================

def _calculate_risk_score(ticket: dict) -> int:
    score = 0
    category = ticket.get("category", "")
    confidence = ticket.get("confidence_score", 1.0)
    description = ticket.get("issue_description", "").lower()

    category_scores = {
        "fraud_alert":             50,
        "payment_gateway_failure": 40,
        "network_outage":          35,
        "pos_failure":             30,
        "inventory_sync_failure":  20,
        "order_delay":             15,
        "pricing_mismatch":        10,
        "scanner_issue":           10,
        "account_issue":           10,
    }
    score += category_scores.get(category, 5)

    if confidence < 0.5:
        score += 20
    elif confidence < 0.7:
        score += 10

    for keyword in CRITICAL_KEYWORDS:
        if keyword in description:
            score += 15
            break

    for keyword in HIGH_KEYWORDS:
        if keyword in description:
            score += 10
            break

    if ticket.get("_sla_breach") == "Yes":
        score += 15

    if ticket.get("_customer_tier") == "Platinum":
        score += 10

    if ticket.get("_system_status") == "Down":
        score += 20
    elif ticket.get("_system_status") == "Partially Down":
        score += 10

    return min(score, 100)


# ============================================================
# ROUTER LOGIC
# ============================================================

def _determine_escalation(ticket: dict) -> bool:
    severity   = ticket.get("severity")
    confidence = ticket.get("confidence_score", 1.0)
    category   = ticket.get("category", "")

    if severity == "critical":
        return True

    if confidence < 0.5:
        return True

    if category in ESCALATION_CATEGORIES:
        return True

    if (
        ticket.get("_requires_escalation", "No") == "Yes"
        and severity in ["critical", "high"]
    ):
        return True

    if ticket.get("_system_status") == "Down":
        return True

    return False


# ============================================================
# AGENT DECISION LOGGER
# ============================================================

def _log_decision(ticket: dict, status: str, error: str = None):
    log_entry = {
        "ticket_id": ticket.get("ticket_id"),
        "agent":     "severity_detection_agent",
        "input_fields": {
            "category":          ticket.get("category"),
            "confidence_score":  ticket.get("confidence_score"),
            "issue_description": ticket.get("issue_description"),
        },
        "output_fields": {
            "severity":        ticket.get("severity"),
            "severity_reason": ticket.get("severity_reason"),
            "escalate":        ticket.get("escalate"),
        },
        "status":    status,
        "timestamp": datetime.utcnow().isoformat(),
    }
    if error:
        log_entry["error"] = error

    logger.info("AGENT_LOG: %s", json.dumps(log_entry))


# ============================================================
# MAIN PUBLIC FUNCTION — called
# ============================================================

def detect_severity(ticket: dict) -> dict:
    """
    MODULE 4 MAIN FUNCTION

    Called by:  run_pipeline() 
    Reads:      category, confidence_score, issue_description
    Writes:     severity, severity_reason, escalate
    Returns:    FULL ticket object

    Never crashes the pipeline.
    On failure: severity=medium, escalate=False, error logged.
    """
    ticket_id = ticket.get("ticket_id", "UNKNOWN")
    logger.info("Severity agent started | ticket_id=%s", ticket_id)
    start_time = time.time()

    ticket = accept_ticket_from_classifier(ticket)

    try:
        # Azure OpenAI API call
        llm_result = _retry_openai_call(ticket)

        # Business rule validation
        final_result = _apply_business_rules(ticket, llm_result)

        # Write contract fields
        ticket["severity"]        = final_result["severity"]
        ticket["severity_reason"] = final_result["severity_reason"]

        # Router decision
        ticket["escalate"] = _determine_escalation(ticket)

        # Risk score
        risk_score = _calculate_risk_score(ticket)

        # Metadata
        ticket.setdefault("metadata", {})
        ticket["metadata"]["severity_model"]      = f"azure/{AZURE_DEPLOYMENT}"
        ticket["metadata"]["risk_score"]          = risk_score
        ticket["metadata"]["severity_latency_ms"] = round(
            (time.time() - start_time) * 1000, 2
        )

        _log_decision(ticket, "success")
        logger.info(
            "Severity complete | ticket_id=%s | severity=%s | "
            "risk_score=%d | escalate=%s",
            ticket_id, ticket["severity"], risk_score, ticket["escalate"]
        )

    except Exception as e:
        err_msg = str(e)
        logger.error(
            "Severity agent FAILED | ticket_id=%s | error=%s",
            ticket_id, err_msg
        )

        ticket["severity"]        = "medium"
        ticket["severity_reason"] = "Fallback severity — agent error occurred."
        ticket["escalate"]        = False

        ticket.setdefault("error_log", []).append({
            "agent":     "severity_detection_agent",
            "error":     err_msg,
            "fallback":  True,
            "timestamp": datetime.utcnow().isoformat()
        })

        _log_decision(ticket, "failed", err_msg)

    return ticket


# ============================================================
# BATCH PROCESSING
# ============================================================

def detect_severity_batch(
    tickets: list[dict],
    delay_between_calls: float = RATE_LIMIT_DELAY
) -> list[dict]:
    """
    Processes tickets sequentially with delay between calls
    to respect Azure OpenAI rate limits.
    """
    results = []
    total = len(tickets)

    for idx, ticket in enumerate(tickets):
        logger.info(
            "Processing ticket %d/%d | ticket_id=%s",
            idx + 1, total, ticket.get("ticket_id")
        )

        result = detect_severity(ticket)
        results.append(result)

        if idx < total - 1:
            time.sleep(delay_between_calls)

    return results


def detect_severity_batch_parallel(
    tickets: list[dict],
    max_workers: int = 4
) -> list[dict]:
    """
    PARALLEL VERSION — use when Azure quota allows.
    """
    results = [None] * len(tickets)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_idx = {
            executor.submit(detect_severity, ticket): idx
            for idx, ticket in enumerate(tickets)
        }
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                results[idx] = future.result()
            except Exception as e:
                logger.error(
                    "Parallel worker failed | index=%d | error=%s", idx, e
                )
                results[idx] = tickets[idx]

    return results


# ============================================================
# PIPELINE ENTRY POINT
# ============================================================

def run_severity_on_csv(
    tickets_csv:   str = "data/retail_tickets.csv",
    incidents_csv: str = "data/retail_incident_logs.csv",
    output_csv:    str = "data/severity_output.csv",
    limit:         int = None
) -> pd.DataFrame:
    """
    Full pipeline: loads CSVs → runs Azure OpenAI
    severity detection → saves severity_output.csv.
    """
    logger.info("=== Severity Batch Pipeline Started ===")

    tickets   = load_tickets_from_csv(tickets_csv)
    incidents = load_incidents_from_csv(incidents_csv)
    all_tickets = tickets + incidents

    if limit:
        all_tickets = all_tickets[:limit]
        logger.info("LIMIT applied — processing first %d tickets", limit)

    logger.info(
        "Total to process: %d (%d tickets + %d incidents)",
        len(all_tickets), len(tickets), len(incidents)
    )

    results = detect_severity_batch(all_tickets)

    output_rows = []
    for t in results:
        output_rows.append({
            "ticket_id":         t.get("ticket_id"),
            "issue_description": t.get("issue_description"),
            "category":          t.get("category"),
            "confidence_score":  t.get("confidence_score"),
            "severity":          t.get("severity"),
            "severity_reason":   t.get("severity_reason"),
            "escalate":          t.get("escalate"),
            "risk_score":        t.get("metadata", {}).get("risk_score", 0),
            "sla_breach":        t.get("_sla_breach", "No"),
            "customer_tier":     t.get("_customer_tier", ""),
            "store_id":          t.get("store_id"),
            "timestamp":         t.get("timestamp"),
            "latency_ms":        t.get("metadata", {}).get("severity_latency_ms", 0),
            "error_count":       len(t.get("error_log", [])),
        })

    df = pd.DataFrame(output_rows)
    df.to_csv(output_csv, index=False)

    logger.info("=== Severity Pipeline Complete ===")
    logger.info("Total processed : %d", len(df))
    logger.info("Critical        : %d", len(df[df["severity"] == "critical"]))
    logger.info("High            : %d", len(df[df["severity"] == "high"]))
    logger.info("Medium          : %d", len(df[df["severity"] == "medium"]))
    logger.info("Low             : %d", len(df[df["severity"] == "low"]))
    logger.info("Escalated       : %d", len(df[df["escalate"] == True]))
    logger.info("Errors          : %d", len(df[df["error_count"] > 0]))
    logger.info("Output saved to : %s", output_csv)

    return df


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    print("\n========== TEST 1: Single Ticket — Azure OpenAI GPT-4o ==========\n")

    single_ticket = {
        "ticket_id":            "TKT-1042",
        "timestamp":            "2025-05-20T10:30:00",
        "channel":              "app",
        "store_id":             "STORE-021",
        "customer_id":          "CUST-887",
        "customer_name":        "Ravi Kumar",
        "issue_description":    (
            "Payment gateway failure affecting all stores "
            "during peak hours."
        ),
        "category":             "payment_gateway_failure",
        "confidence_score":     0.91,
        "severity":             None,
        "severity_reason":      None,
        "escalate":             None,
        "retrieved_docs":       [],
        "suggested_resolution": None,
        "resolution_source":    None,
        "human_approved":       None,
        "approver_notes":       None,
        "final_status":         None,
        "error_log":            [],
        "retry_count":          0,
        "_sla_breach":          "Yes",
        "_customer_tier":       "Platinum",
        "_system_status":       "Down",
        "_priority":            "Critical",
        "_requires_escalation": "Yes",
    }

    result = detect_severity(single_ticket)
    print(json.dumps({
        "ticket_id":       result["ticket_id"],
        "severity":        result["severity"],
        "severity_reason": result["severity_reason"],
        "escalate":        result["escalate"],
        "risk_score":      result.get("metadata", {}).get("risk_score"),
        "latency_ms":      result.get("metadata", {}).get("severity_latency_ms"),
        "error_log":       result["error_log"],
    }, indent=2))

    print("\n========== TEST 2: First 5 tickets from CSV ==========\n")
    print("(Real Azure OpenAI — ~20 seconds for 5 tickets)\n")

    try:
        df = run_severity_on_csv(
            tickets_csv="data/retail_tickets.csv",
            incidents_csv="data/retail_incident_logs.csv",
            output_csv="data/severity_output.csv",
            limit=5
        )

        print("\nSeverity Distribution:")
        print(df["severity"].value_counts().to_string())

        print("\nEscalation Count:")
        print(df["escalate"].value_counts().to_string())

        print("\nDetailed Results:")
        print(
            df[[
                "ticket_id", "category", "severity",
                "escalate", "risk_score", "sla_breach"
            ]].to_string()
        )

    except FileNotFoundError:
        print(
            "CSV files not found — run "
            "module first to generate data/ folder."
        )