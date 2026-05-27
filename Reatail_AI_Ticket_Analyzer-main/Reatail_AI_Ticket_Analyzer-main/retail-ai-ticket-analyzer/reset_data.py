from pathlib import Path  
  
base = Path(__file__).resolve().parent  
  
(base / "outputs" / "final_tickets.json").write_text("[]", encoding="utf-8")  
(base / "logs" / "agent_logs.jsonl").write_text("", encoding="utf-8")  
(base / "logs" / "pipeline_logs.jsonl").write_text("", encoding="utf-8")  
  
print("Data cleared successfully.")  