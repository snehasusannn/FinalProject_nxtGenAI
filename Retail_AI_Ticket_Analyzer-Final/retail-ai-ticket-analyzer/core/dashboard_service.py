
from core.storage import load_all_tickets  

def get_dashboard_metrics():  
    tickets = load_all_tickets()  

    severity_breakdown = {  
        "critical": 0,  
        "high": 0,  
        "medium": 0,  
        "low": 0  
    }  

    total = len(tickets)  
    pending_review = 0  
    resolved = 0  
    rejected = 0  
    escalated = 0  
    auto_approved = 0  

    for t in tickets:  
        sev = t.get("severity")  
        if sev in severity_breakdown:  
            severity_breakdown[sev] += 1  

        if t.get("final_status") == "pending_review":  
            pending_review += 1  
        elif t.get("final_status") == "resolved":  
            resolved += 1  
        elif t.get("final_status") == "rejected":  
            rejected += 1  

        if t.get("escalate") is True:  
            escalated += 1  

        if t.get("approver_notes") == "Auto-approved by policy":  
            auto_approved += 1  

    return {  
        "total_processed": total,  
        "severity_breakdown": severity_breakdown,  
        "pending_review": pending_review,  
        "resolved": resolved,  
        "rejected": rejected,  
        "escalated": escalated,  
        "auto_approved": auto_approved  
    }  
