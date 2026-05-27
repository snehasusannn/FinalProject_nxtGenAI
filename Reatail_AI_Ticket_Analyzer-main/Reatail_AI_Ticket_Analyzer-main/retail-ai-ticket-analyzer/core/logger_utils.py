
import json  
from pathlib import Path  
from datetime import datetime  

LOG_DIR = Path(__file__).resolve().parents[1] / "logs"  
LOG_DIR.mkdir(parents=True, exist_ok=True)  

AGENT_LOG_FILE = LOG_DIR / "agent_logs.jsonl"  
PIPELINE_LOG_FILE = LOG_DIR / "pipeline_logs.jsonl"  

def log_agent_event(ticket_id: str, agent: str, status: str, payload: dict):  
    entry = {  
        "ticket_id": ticket_id,  
        "agent": agent,  
        "status": status,  
        "payload": payload,  
        "timestamp": datetime.utcnow().isoformat()  
    }  
    with open(AGENT_LOG_FILE, "a", encoding="utf-8") as f:  
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")  

def log_pipeline_event(ticket_id: str, stage: str, status: str, message: str):  
    entry = {  
        "ticket_id": ticket_id,  
        "stage": stage,  
        "status": status,  
        "message": message,  
        "timestamp": datetime.utcnow().isoformat()  
    }  
    with open(PIPELINE_LOG_FILE, "a", encoding="utf-8") as f:  
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")  
