import csv  
import json  
import sys  
from pathlib import Path  
from datetime import datetime  
  
from core.classifier_adapter import classify_ticket  
from core.human_approval import human_approval_step  
from core.logger_utils import log_agent_event, log_pipeline_event  
from core.storage import upsert_ticket  
  
BASE_DIR = Path(__file__).resolve().parents[1]  
AGENT_MODULE_DIR = BASE_DIR / "agent_module"  
  
MODULE_4_PATH = AGENT_MODULE_DIR / "Module_4"  
MODULE_5_PATH = AGENT_MODULE_DIR / "Module_5"  
MODULE_2_PATH = AGENT_MODULE_DIR / "Module_2"
  
if str(MODULE_4_PATH) not in sys.path:  
    sys.path.append(str(MODULE_4_PATH))  
  
if str(MODULE_5_PATH) not in sys.path:  
    sys.path.append(str(MODULE_5_PATH))  
 
# Ensure the agent_module root is on sys.path so sibling modules (e.g. Module_2)
# can be imported as top-level packages like `Module_2.retriever`.
if str(AGENT_MODULE_DIR) not in sys.path:
    sys.path.append(str(AGENT_MODULE_DIR))

# Also add Module_2 path to sys.path to be robust when modules expect direct
# access to its contents.
if str(MODULE_2_PATH) not in sys.path:
    sys.path.append(str(MODULE_2_PATH))
  
from severity_detection_agent import detect_severity  
from resolution_agent import suggest_resolution  
  
MAX_RETRIES = 2  
  
  
def ensure_ticket_defaults(ticket: dict) -> dict:  
    ticket.setdefault("ticket_id", f"TKT-{int(datetime.utcnow().timestamp())}")  
    ticket.setdefault("timestamp", datetime.utcnow().isoformat())  
    ticket.setdefault("channel", "app")  
    ticket.setdefault("store_id", "")  
    ticket.setdefault("customer_id", "")  
    ticket.setdefault("customer_name", "")  
    ticket.setdefault("issue_description", "")  
  
    ticket.setdefault("category", None)  
    ticket.setdefault("confidence_score", None)  
    ticket.setdefault("priority", None)  
    ticket.setdefault("sentiment", None)  
    ticket.setdefault("summary", None)  
    ticket.setdefault("customer_context", None)  
  
    ticket.setdefault("severity", None)  
    ticket.setdefault("severity_reason", None)  
    ticket.setdefault("escalate", None)  
  
    ticket.setdefault("retrieved_docs", [])  
    ticket.setdefault("suggested_resolution", None)  
    ticket.setdefault("resolution_source", None)  
  
    ticket.setdefault("human_approved", None)  
    ticket.setdefault("approver_notes", None)  
    ticket.setdefault("final_status", None)  
  
    ticket.setdefault("error_log", [])  
    ticket.setdefault("retry_count", 0)  
    return ticket  
  
  
def run_with_retry(agent_name: str, func, ticket: dict) -> dict:  
    last_error = None  
  
    for attempt in range(MAX_RETRIES + 1):  
        try:  
            result = func(ticket)  
  
            log_agent_event(  
                ticket_id=result.get("ticket_id", "UNKNOWN"),  
                agent=agent_name,  
                status="success",  
                payload={  
                    "attempt": attempt + 1,  
                    "output_snapshot": {  
                        "category": result.get("category"),  
                        "priority": result.get("priority"),  
                        "sentiment": result.get("sentiment"),  
                        "summary": result.get("summary"),  
                        "severity": result.get("severity"),  
                        "severity_reason": result.get("severity_reason"),  
                        "escalate": result.get("escalate"),  
                        "resolution_source": result.get("resolution_source"),  
                        "final_status": result.get("final_status"),  
                    }  
                }  
            )  
            return result  
  
        except Exception as e:  
            last_error = str(e)  
            ticket["retry_count"] = ticket.get("retry_count", 0) + 1  
            ticket.setdefault("error_log", []).append({  
                "agent": agent_name,  
                "error": f"Attempt {attempt + 1} failed: {last_error}"  
            })  
  
            log_agent_event(  
                ticket_id=ticket.get("ticket_id", "UNKNOWN"),  
                agent=agent_name,  
                status="retry_failed",  
                payload={  
                    "attempt": attempt + 1,  
                    "error": last_error  
                }  
            )  
  
    log_pipeline_event(  
        ticket_id=ticket.get("ticket_id", "UNKNOWN"),  
        stage=agent_name,  
        status="failed_after_retries",  
        message=last_error or "Unknown error"  
    )  
    return ticket  
  
  
def run_pipeline(ticket: dict) -> dict:  
    ticket = ensure_ticket_defaults(ticket)  
  
    try:  
        log_pipeline_event(  
            ticket["ticket_id"],  
            "pipeline",  
            "started",  
            "Pipeline execution started"  
        )  
  
        ticket = run_with_retry("classifier", classify_ticket, ticket)  
        ticket = run_with_retry("severity", detect_severity, ticket)  
        ticket = run_with_retry("resolution", suggest_resolution, ticket)  
        ticket = run_with_retry("human_approval", human_approval_step, ticket)  
  
        upsert_ticket(ticket)  
  
        log_pipeline_event(  
            ticket["ticket_id"],  
            "pipeline",  
            "completed",  
            "Pipeline execution completed"  
        )  
        return ticket  
  
    except Exception as e:  
        ticket.setdefault("error_log", []).append({  
            "agent": "orchestrator",  
            "error": str(e)  
        })  
        ticket["final_status"] = "pending_review"  
        upsert_ticket(ticket)  
  
        log_pipeline_event(  
            ticket["ticket_id"],  
            "pipeline",  
            "fatal_error",  
            str(e)  
        )  
        return ticket  
  
  
def load_tickets_from_csv(csv_path: str) -> list[dict]:  
    csv_file = Path(csv_path)  
    if not csv_file.exists():  
        raise FileNotFoundError(f"CSV file not found: {csv_path}")  
  
    tickets = []  
    with open(csv_file, "r", encoding="utf-8", newline="") as f:  
        reader = csv.DictReader(f)  
        for idx, row in enumerate(reader, start=1):  
            issue_description = (  
                row.get("issue_description")  
                or row.get("issue_text")  
                or row.get("description")  
                or ""  
            )  
  
            ticket = {  
                "ticket_id": row.get("ticket_id") or f"BULK-{idx:05d}",  
                "timestamp": row.get("timestamp") or datetime.utcnow().isoformat(),  
                "channel": row.get("channel") or "bulk_csv",  
                "store_id": row.get("store_id", ""),  
                "customer_id": row.get("customer_id", ""),  
                "customer_name": row.get("customer_name", ""),  
                "issue_description": issue_description,  
            }  
            tickets.append(ticket)  
  
    return tickets  
  
  
def save_bulk_results_to_csv(results: list[dict], output_path: str) -> None:  
    if not results:  
        return  
  
    output_file = Path(output_path)  
    output_file.parent.mkdir(parents=True, exist_ok=True)  
  
    flattened_results = []  
    for row in results:  
        flat_row = {}  
        for key, value in row.items():  
            if isinstance(value, (dict, list)):  
                flat_row[key] = json.dumps(value)  
            else:  
                flat_row[key] = value  
        flattened_results.append(flat_row)  
  
    fieldnames = sorted({k for row in flattened_results for k in row.keys()})  
  
    with open(output_file, "w", encoding="utf-8", newline="") as f:  
        writer = csv.DictWriter(f, fieldnames=fieldnames)  
        writer.writeheader()  
        writer.writerows(flattened_results)  
  
  
def run_bulk_pipeline(csv_path: str, output_csv_path: str | None = None) -> list[dict]:  
    tickets = load_tickets_from_csv(csv_path)  
    results = []  
  
    log_pipeline_event(  
        ticket_id="BULK_RUN",  
        stage="bulk_pipeline",  
        status="started",  
        message=f"Bulk pipeline started for {len(tickets)} ticket(s)"  
    )  
  
    for ticket in tickets:  
        result = run_pipeline(ticket)  
        results.append(result)  
  
    if output_csv_path:  
        save_bulk_results_to_csv(results, output_csv_path)  
  
    log_pipeline_event(  
        ticket_id="BULK_RUN",  
        stage="bulk_pipeline",  
        status="completed",  
        message=f"Bulk pipeline completed for {len(results)} ticket(s)"  
    )  
  
    return results  