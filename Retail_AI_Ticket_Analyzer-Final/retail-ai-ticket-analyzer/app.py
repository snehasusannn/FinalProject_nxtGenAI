import csv  
import json  
import tempfile  
from pathlib import Path  
  
import gradio as gr  
  
from core.orchestrator import run_pipeline, run_bulk_pipeline  
from core.storage import load_all_tickets, get_ticket_by_id, upsert_ticket  
from core.dashboard_service import get_dashboard_metrics  
  
  
# =========================================================  
# PATH CONFIG  
# =========================================================  
BASE_DIR = Path(__file__).resolve().parent  
  
# Try both possible project layouts  
CSV_CANDIDATES = [  
    BASE_DIR / "agent_module" / "Module_4" / "data" / "retail_tickets.csv",  
    BASE_DIR / "Module_4" / "data" / "retail_tickets.csv",  
]  
  
OUTPUT_CSV_CANDIDATES = [  
    BASE_DIR / "agent_module" / "Module_4" / "data" / "retail_tickets_processed.csv",  
    BASE_DIR / "Module_4" / "data" / "retail_tickets_processed.csv",  
]  
  
CSV_PATH = next((p for p in CSV_CANDIDATES if p.exists()), CSV_CANDIDATES[0])  
OUTPUT_CSV_PATH = next((p for p in OUTPUT_CSV_CANDIDATES if p.parent.exists()), OUTPUT_CSV_CANDIDATES[0])  
  
  
# =========================================================  
# HELPERS  
# =========================================================  
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
                or row.get("ticket_text")    
                or row.get("issue_text")  
                or row.get("description")  
                or ""  
            )  
  
            ticket = {  
                "ticket_id": row.get("ticket_id") or f"BULK-{idx:05d}",  
                "timestamp": row.get("timestamp", ""),  
                "channel": row.get("channel") or "bulk_csv",  
                "store_id": row.get("store_id", ""),  
                "customer_id": row.get("customer_id", ""),  
                "customer_name": row.get("customer_name", ""),  
                "issue_description": issue_description,  
            }  
            tickets.append(ticket)  
  
    return tickets  
  
  
def format_ticket_summary(ticket: dict) -> str:  
    if not ticket:  
        return "No ticket data available."  
  
    docs_text = ""  
    docs = ticket.get("retrieved_docs", []) or []  
    if docs:  
        docs_text = "\n\nRetrieved SOP Chunks:\n"  
        for i, doc in enumerate(docs, 1):  
            docs_text += (  
                f"\n[{i}] {doc.get('doc_id')} | Score: {doc.get('score')}\n"  
                f"{doc.get('content')}\n"  
            )  
  
    return f"""  
Ticket ID: {ticket.get("ticket_id")}  
Category: {ticket.get("category")}  
Confidence Score: {ticket.get("confidence_score")}  
Priority: {ticket.get("priority")}  
Sentiment: {ticket.get("sentiment")}  
Summary: {ticket.get("summary")}  
Severity: {ticket.get("severity")}  
Severity Reason: {ticket.get("severity_reason")}  
Escalate: {ticket.get("escalate")}  
Resolution Source: {ticket.get("resolution_source")}  
Suggested Resolution: {ticket.get("suggested_resolution")}  
Human Approved: {ticket.get("human_approved")}  
Approver Notes: {ticket.get("approver_notes")}  
Final Status: {ticket.get("final_status")}  
Retry Count: {ticket.get("retry_count")}  
{docs_text}  
""".strip()  
  
  
def make_ticket_label(ticket: dict) -> str:  
    return (  
        f"{ticket.get('ticket_id', 'NO-ID')} | "  
        f"{ticket.get('customer_id', 'NO-CUSTOMER')} | "  
        f"{str(ticket.get('issue_description', ''))[:100]}"  
    )  
  
  
def build_ticket_map(tickets: list[dict]) -> dict:  
    return {make_ticket_label(ticket): ticket for ticket in tickets}  
  
  
# =========================================================  
# MANUAL ANALYSIS FUNCTIONS  
# =========================================================  
def analyze_ticket(ticket_id, channel, store_id, customer_id, customer_name, issue_description):  
    ticket = {  
        "ticket_id": ticket_id.strip() if ticket_id else "",  
        "channel": channel,  
        "store_id": store_id,  
        "customer_id": customer_id,  
        "customer_name": customer_name,  
        "issue_description": issue_description,  
    }  
  
    result = run_pipeline(ticket)  
    summary = format_ticket_summary(result)  
    pretty_json = json.dumps(result, indent=2, ensure_ascii=False)  
    return pretty_json, summary  
  
  
def fetch_ticket_for_review(ticket_id):  
    ticket = get_ticket_by_id(ticket_id)  
    if not ticket:  
        return "{}", "Ticket not found."  
  
    return json.dumps(ticket, indent=2, ensure_ascii=False), format_ticket_summary(ticket)  
  
  
def review_ticket(ticket_id, action, approver_notes, modified_resolution):  
    ticket = get_ticket_by_id(ticket_id)  
    if not ticket:  
        return "{}", "Ticket not found."  
  
    action = (action or "").lower().strip()  
  
    if action == "approve":  
        ticket["human_approved"] = True  
        ticket["approver_notes"] = approver_notes or "Approved by human"  
        ticket["final_status"] = "resolved"  
  
    elif action == "reject":  
        ticket["human_approved"] = False  
        ticket["approver_notes"] = approver_notes or "Rejected by human"  
        ticket["final_status"] = "rejected"  
  
    elif action == "modify":  
        ticket["human_approved"] = True  
        ticket["suggested_resolution"] = modified_resolution or ticket.get("suggested_resolution")  
        ticket["approver_notes"] = approver_notes or "Modified by human"  
        ticket["final_status"] = "resolved"  
  
    else:  
        return "{}", "Invalid action. Use approve, reject, or modify."  
  
    upsert_ticket(ticket)  
    return json.dumps(ticket, indent=2, ensure_ascii=False), format_ticket_summary(ticket)  
  
  
def get_dashboard_data():  
    metrics = get_dashboard_metrics()  
    tickets = load_all_tickets()  
    pending = [t for t in tickets if t.get("final_status") == "pending_review"]  
  
    pending_rows = []  
    for t in pending:  
        pending_rows.append([  
            t.get("ticket_id"),  
            t.get("category"),  
            t.get("severity"),  
            t.get("store_id"),  
            t.get("final_status")  
        ])  
  
    all_rows = []  
    for t in tickets:  
        all_rows.append([  
            t.get("ticket_id"),  
            t.get("category"),  
            t.get("severity"),  
            t.get("escalate"),  
            t.get("final_status")  
        ])  
  
    return (  
        json.dumps(metrics, indent=2, ensure_ascii=False),  
        pending_rows,  
        all_rows  
    )  
  
  
# =========================================================  
# CSV TICKET FUNCTIONS  
# =========================================================  
def load_available_csv_tickets(search_text=""):  
    try:  
        tickets = load_tickets_from_csv(str(CSV_PATH))  
  
        if search_text and search_text.strip():  
            s = search_text.lower().strip()  
            tickets = [  
                t for t in tickets  
                if s in str(t.get("ticket_id", "")).lower()  
                or s in str(t.get("customer_id", "")).lower()  
                or s in str(t.get("customer_name", "")).lower()  
                or s in str(t.get("issue_description", "")).lower()  
            ]  
  
        ticket_map = build_ticket_map(tickets)  
        labels = list(ticket_map.keys())  
  
        rows = []  
        for t in tickets:  
            rows.append([  
                t.get("ticket_id"),  
                t.get("customer_id"),  
                t.get("customer_name"),  
                t.get("channel"),  
                t.get("store_id"),  
                t.get("issue_description"),  
            ])  
  
        first_label = labels[0] if labels else None  
        first_ticket = ticket_map[first_label] if first_label else {}  
  
        return (  
            gr.update(choices=labels, value=first_label),  
            rows,  
            json.dumps(first_ticket, indent=2, ensure_ascii=False),  
            json.dumps(  
                {  
                    "status": "loaded",  
                    "csv_path": str(CSV_PATH),  
                    "ticket_count": len(tickets)  
                },  
                indent=2,  
                ensure_ascii=False  
            )  
        )  
  
    except Exception as e:  
        return (  
            gr.update(choices=[], value=None),  
            [],  
            "{}",  
            json.dumps({"status": "error", "message": str(e)}, indent=2, ensure_ascii=False)  
        )  
  
  
def show_selected_csv_ticket(selected_label, search_text=""):  
    try:  
        tickets = load_tickets_from_csv(str(CSV_PATH))  
  
        if search_text and search_text.strip():  
            s = search_text.lower().strip()  
            tickets = [  
                t for t in tickets  
                if s in str(t.get("ticket_id", "")).lower()  
                or s in str(t.get("customer_id", "")).lower()  
                or s in str(t.get("customer_name", "")).lower()  
                or s in str(t.get("issue_description", "")).lower()  
            ]  
  
        ticket_map = build_ticket_map(tickets)  
        ticket = ticket_map.get(selected_label, {})  
        return json.dumps(ticket, indent=2, ensure_ascii=False)  
  
    except Exception as e:  
        return json.dumps({"status": "error", "message": str(e)}, indent=2, ensure_ascii=False)  
  
  
def analyze_selected_csv_ticket(selected_label, search_text=""):  
    try:  
        tickets = load_tickets_from_csv(str(CSV_PATH))  
  
        if search_text and search_text.strip():  
            s = search_text.lower().strip()  
            tickets = [  
                t for t in tickets  
                if s in str(t.get("ticket_id", "")).lower()  
                or s in str(t.get("customer_id", "")).lower()  
                or s in str(t.get("customer_name", "")).lower()  
                or s in str(t.get("issue_description", "")).lower()  
            ]  
  
        ticket_map = build_ticket_map(tickets)  
  
        if not selected_label or selected_label not in ticket_map:  
            return "{}", "No valid ticket selected.", None  
  
        selected_ticket = dict(ticket_map[selected_label])  
        result = run_pipeline(selected_ticket)  
  
        temp_json = tempfile.NamedTemporaryFile(  
            delete=False,  
            suffix=".json",  
            mode="w",  
            encoding="utf-8"  
        )  
        json.dump(result, temp_json, indent=2, ensure_ascii=False)  
        temp_json.close()  
  
        return (  
            json.dumps(result, indent=2, ensure_ascii=False),  
            format_ticket_summary(result),  
            temp_json.name  
        )  
  
    except Exception as e:  
        return (  
            json.dumps({"status": "error", "message": str(e)}, indent=2, ensure_ascii=False),  
            str(e),  
            None  
        )  
  
  
def analyze_all_csv_tickets():  
    try:  
        OUTPUT_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)  
  
        results = run_bulk_pipeline(  
            csv_path=str(CSV_PATH),  
            output_csv_path=str(OUTPUT_CSV_PATH)  
        )  
  
        rows = []  
        for t in results:  
            rows.append([  
                t.get("ticket_id"),  
                t.get("category"),  
                t.get("severity"),  
                t.get("escalate"),  
                t.get("final_status"),  
            ])  
  
        temp_json = tempfile.NamedTemporaryFile(  
            delete=False,  
            suffix=".json",  
            mode="w",  
            encoding="utf-8"  
        )  
        json.dump(results, temp_json, indent=2, ensure_ascii=False)  
        temp_json.close()  
  
        status = {  
            "status": "success",  
            "processed_count": len(results),  
            "output_csv": str(OUTPUT_CSV_PATH)  
        }  
  
        return (  
            rows,  
            json.dumps(status, indent=2, ensure_ascii=False),  
            temp_json.name,  
            str(OUTPUT_CSV_PATH) if OUTPUT_CSV_PATH.exists() else None  
        )  
  
    except Exception as e:  
        return (  
            [],  
            json.dumps({"status": "error", "message": str(e)}, indent=2, ensure_ascii=False),  
            None,  
            None  
        )  
  
  
# =========================================================  
# UI  
# =========================================================  
with gr.Blocks(title="Retail AI Ticket Analyzer") as demo:  
    gr.Markdown("# Retail AI Ticket Analyzer")  
    gr.Markdown(  
        "Multi-agent ticket pipeline with severity detection, RAG resolution, "  
        "human approval, and CSV ticket browsing."  
    )  
  
    # -----------------------------------------------------  
    # TAB 1: MANUAL ANALYZE TICKET  
    # -----------------------------------------------------  
    with gr.Tab("Analyze Ticket"):  
        with gr.Row():  
            with gr.Column():  
                ticket_id = gr.Textbox(label="Ticket ID", placeholder="TKT-5001")  
                channel = gr.Dropdown(  
                    label="Channel",  
                    choices=["app", "email", "call", "in_store"],  
                    value="app"  
                )  
                store_id = gr.Textbox(label="Store ID", placeholder="STORE-021")  
                customer_id = gr.Textbox(label="Customer ID", placeholder="CUST-887")  
                customer_name = gr.Textbox(label="Customer Name", placeholder="Ravi Kumar")  
                issue_description = gr.Textbox(  
                    label="Issue Description",  
                    lines=6,  
                    placeholder="Describe the issue..."  
                )  
                analyze_btn = gr.Button("Analyze Ticket", variant="primary")  
  
            with gr.Column():  
                result_json = gr.Code(label="Pipeline Output JSON", language="json")  
                result_summary = gr.Textbox(label="Formatted Summary", lines=20)  
  
        analyze_btn.click(  
            fn=analyze_ticket,  
            inputs=[ticket_id, channel, store_id, customer_id, customer_name, issue_description],  
            outputs=[result_json, result_summary]  
        )  
  
    # -----------------------------------------------------  
    # TAB 2: AVAILABLE TICKETS FROM CSV  
    # -----------------------------------------------------  
    with gr.Tab("Available Tickets"):  
        gr.Markdown(f"Browse and analyze tickets from CSV: `{CSV_PATH}`")  
  
        with gr.Row():  
            load_csv_btn = gr.Button("Load Tickets From CSV", variant="primary")  
            search_csv = gr.Textbox(  
                label="Search",  
                placeholder="Search by ticket_id / customer_id / customer_name / issue"  
            )  
  
        csv_status = gr.Code(label="CSV Load Status", language="json", value='{"status":"idle"}')  
  
        csv_ticket_selector = gr.Dropdown(  
            label="Available Tickets",  
            choices=[],  
            value=None,  
            interactive=True  
        )  
  
        # Buttons placed high so they are clearly visible  
        with gr.Row():  
            analyze_selected_btn = gr.Button("Analyze Selected Ticket", variant="primary")  
            analyze_all_btn = gr.Button("Analyze All CSV Tickets", variant="secondary")  
  
        csv_table = gr.Dataframe(  
            headers=["ticket_id", "customer_id", "customer_name", "channel", "store_id", "issue_description"],  
            label="Tickets From CSV",  
            interactive=False  
        )  
  
        with gr.Row():  
            with gr.Column():  
                csv_selected_ticket = gr.Code(label="Selected Ticket JSON", language="json")  
            with gr.Column():  
                csv_result_json = gr.Code(label="Processed Ticket JSON", language="json")  
                csv_result_summary = gr.Textbox(label="Processed Ticket Summary", lines=18)  
  
        csv_bulk_results = gr.Dataframe(  
            headers=["ticket_id", "category", "severity", "escalate", "final_status"],  
            label="Bulk Processing Results",  
            interactive=False  
        )  
  
        with gr.Row():  
            selected_result_download = gr.File(label="Download Selected Result JSON")  
            bulk_json_download = gr.File(label="Download Bulk Results JSON")  
            bulk_csv_download = gr.File(label="Download Bulk Results CSV")  
  
        load_csv_btn.click(  
            fn=load_available_csv_tickets,  
            inputs=[search_csv],  
            outputs=[csv_ticket_selector, csv_table, csv_selected_ticket, csv_status]  
        )  
  
        search_csv.change(  
            fn=load_available_csv_tickets,  
            inputs=[search_csv],  
            outputs=[csv_ticket_selector, csv_table, csv_selected_ticket, csv_status]  
        )  
  
        csv_ticket_selector.change(  
            fn=show_selected_csv_ticket,  
            inputs=[csv_ticket_selector, search_csv],  
            outputs=[csv_selected_ticket]  
        )  
  
        analyze_selected_btn.click(  
            fn=analyze_selected_csv_ticket,  
            inputs=[csv_ticket_selector, search_csv],  
            outputs=[csv_result_json, csv_result_summary, selected_result_download]  
        )  
  
        analyze_all_btn.click(  
            fn=analyze_all_csv_tickets,  
            inputs=[],  
            outputs=[csv_bulk_results, csv_status, bulk_json_download, bulk_csv_download]  
        )  
  
    # -----------------------------------------------------  
    # TAB 3: HUMAN APPROVAL  
    # -----------------------------------------------------  
    with gr.Tab("Human Approval"):  
        with gr.Row():  
            with gr.Column():  
                review_ticket_id = gr.Textbox(label="Ticket ID for Review", placeholder="TKT-5001")  
                fetch_btn = gr.Button("Fetch Ticket")  
                action = gr.Dropdown(  
                    label="Action",  
                    choices=["approve", "reject", "modify"],  
                    value="approve"  
                )  
                approver_notes = gr.Textbox(label="Approver Notes", lines=3)  
                modified_resolution = gr.Textbox(label="Modified Resolution", lines=4)  
                review_btn = gr.Button("Submit Review", variant="primary")  
  
            with gr.Column():  
                review_json = gr.Code(label="Reviewed Ticket JSON", language="json")  
                review_summary = gr.Textbox(label="Review Summary", lines=20)  
  
        fetch_btn.click(  
            fn=fetch_ticket_for_review,  
            inputs=[review_ticket_id],  
            outputs=[review_json, review_summary]  
        )  
  
        review_btn.click(  
            fn=review_ticket,  
            inputs=[review_ticket_id, action, approver_notes, modified_resolution],  
            outputs=[review_json, review_summary]  
        )  
  
    # -----------------------------------------------------  
    # TAB 4: DASHBOARD  
    # -----------------------------------------------------  
    with gr.Tab("Dashboard"):  
        refresh_btn = gr.Button("Refresh Dashboard")  
        metrics_json = gr.Code(label="Metrics JSON", language="json")  
        pending_table = gr.Dataframe(  
            headers=["ticket_id", "category", "severity", "store_id", "final_status"],  
            label="Pending Review Tickets",  
            interactive=False  
        )  
        all_table = gr.Dataframe(  
            headers=["ticket_id", "category", "severity", "escalate", "final_status"],  
            label="All Tickets",  
            interactive=False  
        )  
  
        refresh_btn.click(  
            fn=get_dashboard_data,  
            inputs=[],  
            outputs=[metrics_json, pending_table, all_table]  
        )  
  
  
if __name__ == "__main__":  
    demo.launch()  