
def human_approval_step(ticket: dict) -> dict:  
    try:  
        ticket.setdefault("error_log", [])  
        severity = ticket.get("severity")  
        escalate = ticket.get("escalate", False)  

        if escalate is True or severity in ["critical", "high"]:  
            ticket["human_approved"] = "pending"  
            ticket["approver_notes"] = "Awaiting human approval"  
            ticket["final_status"] = "pending_review"  
        else:  
            ticket["human_approved"] = True  
            ticket["approver_notes"] = "Auto-approved by policy"  
            ticket["final_status"] = "resolved"  

        return ticket  

    except Exception as e:  
        ticket.setdefault("error_log", []).append({  
            "agent": "human_approval",  
            "error": str(e)  
        })  
        ticket["human_approved"] = "pending"  
        ticket["approver_notes"] = "Approval step failed, manual review required"  
        ticket["final_status"] = "pending_review"  
        return ticket  
