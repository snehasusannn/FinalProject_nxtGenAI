import sys  
from pathlib import Path  
  
TEAMMATE_ROOT = Path(__file__).resolve().parents[1] / "agent_module"  
MODULE_1_PATH = TEAMMATE_ROOT / "Module_1"  
  
if str(MODULE_1_PATH) not in sys.path:  
    sys.path.append(str(MODULE_1_PATH))  
  
from ticket_classification_agent import classify_single_ticket  
  
  
def classify_ticket(ticket: dict) -> dict:  
    result = classify_single_ticket(  
        ticket_id=ticket.get("ticket_id", "AUTO-TICKET"),  
        customer_id=ticket.get("customer_id", "UNKNOWN"),  
        issue_text=ticket.get("issue_description", "")  
    )  
  
    classification = result.get("classification", {})  
  
    ticket["customer_context"] = result.get("customer_context")  
    ticket["category"] = classification.get("category")  
    ticket["priority"] = classification.get("priority")  
    ticket["sentiment"] = classification.get("sentiment")  
    ticket["summary"] = classification.get("summary")  
    ticket["confidence_score"] = None  
    ticket["escalate"] = result.get("requires_human", False)  
  
    for err in result.get("error_logs", []):  
        ticket.setdefault("error_log", []).append({  
            "agent": "classifier",  
            "error": err  
        })  
  
    return ticket  