
import json  
from pathlib import Path  

OUTPUT_DIR = Path(__file__).resolve().parents[1] / "outputs"  
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)  

TICKETS_FILE = OUTPUT_DIR / "final_tickets.json"  

def load_all_tickets() -> list:  
    if not TICKETS_FILE.exists():  
        return []  
    with open(TICKETS_FILE, "r", encoding="utf-8") as f:  
        try:  
            return json.load(f)  
        except Exception:  
            return []  

def save_all_tickets(tickets: list):  
    with open(TICKETS_FILE, "w", encoding="utf-8") as f:  
        json.dump(tickets, f, indent=2, ensure_ascii=False)  

def upsert_ticket(ticket: dict):  
    tickets = load_all_tickets()  
    updated = False  

    for i, t in enumerate(tickets):  
        if t.get("ticket_id") == ticket.get("ticket_id"):  
            tickets[i] = ticket  
            updated = True  
            break  

    if not updated:  
        tickets.append(ticket)  

    save_all_tickets(tickets)  

def get_ticket_by_id(ticket_id: str):  
    tickets = load_all_tickets()  
    for t in tickets:  
        if t.get("ticket_id") == ticket_id:  
            return t  
    return None  
