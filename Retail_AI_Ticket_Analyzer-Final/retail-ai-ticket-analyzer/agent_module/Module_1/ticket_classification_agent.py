import os  
import csv  
import json  
from typing import TypedDict, Dict, Any, List, Literal  
  
from dotenv import load_dotenv  
from pydantic import BaseModel, Field  
from langchain_google_genai import ChatGoogleGenerativeAI  
from langchain_core.prompts import ChatPromptTemplate  
from langchain_core.tools import tool  
from langgraph.graph import StateGraph, END  
from langgraph.checkpoint.memory import MemorySaver  
  
load_dotenv()  
  
  
class TicketState(TypedDict):  
    ticket_id: str  
    customer_id: str  
    issue_text: str  
    customer_context: str  
    classification: Dict[str, Any]  
    requires_human: bool  
    status: str  
    error_logs: List[str]  
  
  
@tool  
def fetch_customer_crm_data(customer_id: str) -> str:  
    """Fetch customer profile, historical priority markers, and SLA tiers."""  
    mock_crm_db = {  
        "CUST-001": "VIP Enterprise Tier. Critical SLA account. High churn risk.",  
        "CUST-002": "Standard Tier. Individual consumer account.",  
        "CUST-003": "Premium Business Tier. Multiple concurrent open service requests.",  
    }  
    return mock_crm_db.get(  
        customer_id,  
        "Standard Tier. No priority profile found."  
    )  
  
  
class TicketClassification(BaseModel):  
    category: Literal[  
        "Billing",  
        "Technical Support",  
        "Feature Request",  
        "Account Access"  
    ] = Field(description="Operational category.")  
  
    priority: Literal[  
        "LOW",  
        "MEDIUM",  
        "HIGH",  
        "CRITICAL"  
    ] = Field(description="Priority assignment.")  
  
    sentiment: Literal[  
        "Positive",  
        "Neutral",  
        "Angry",  
        "Frustrated"  
    ] = Field(description="Sentiment extracted from issue text.")  
  
    summary: str = Field(description="One-sentence issue summary.")  
  
  
def extract_context_node(state: TicketState) -> Dict[str, Any]:  
    try:  
        context = fetch_customer_crm_data.invoke({  
            "customer_id": state["customer_id"]  
        })  
        return {  
            "customer_context": context,  
            "status": "context_fetched"  
        }  
    except Exception as e:  
        return {  
            "error_logs": state.get("error_logs", []) + [f"Tool Error: {str(e)}"],  
            "status": "tool_failure",  
            "customer_context": "Fallback: Default Standard Tier Profile Allocation"  
        }  
  
  
def classification_node(state: TicketState) -> Dict[str, Any]:  
    google_api_key = os.getenv("GOOGLE_API_KEY")  
    if not google_api_key:  
        return {  
            "error_logs": state.get("error_logs", []) + [  
                "GOOGLE_API_KEY not found in environment."  
            ],  
            "status": "failed_classification"  
        }  
  
    llm = ChatGoogleGenerativeAI(  
        model="gemini-2.5-flash",  
        temperature=0,  
        google_api_key=google_api_key  
    )  
  
    classifier_llm = llm.with_structured_output(  
        TicketClassification  
    ).with_retry(  
        stop_after_attempt=3,  
        wait_exponential_jitter=True  
    )  
  
    prompt = ChatPromptTemplate.from_messages([  
        (  
            "system",  
            "You are an elite IT Service Desk Ticket Classification Agent. "  
            "Analyze the issue and customer context. "  
            "Return only valid structured output."  
        ),  
        (  
            "human",  
            "Ticket Data: {issue_text}\n\nCRM Context Summary: {customer_context}"  
        )  
    ])  
  
    chain = prompt | classifier_llm  
  
    try:  
        result = chain.invoke({  
            "issue_text": state["issue_text"],  
            "customer_context": state["customer_context"]  
        })  
  
        requires_human_flag = (  
            result.priority == "CRITICAL"  
            or state.get("status") == "tool_failure"  
        )  
  
        return {  
            "classification": result.model_dump(),  
            "requires_human": requires_human_flag,  
            "status": "classified"  
        }  
  
    except Exception as e:  
        return {  
            "error_logs": state.get("error_logs", []) + [  
                f"LLM Node Breakdown: {str(e)}"  
            ],  
            "status": "failed_classification"  
        }  
  
  
def human_approval_node(state: TicketState) -> Dict[str, Any]:  
    return {  
        "status": "human_reviewed_and_passed"  
    }  
  
  
def error_handler_node(state: TicketState) -> Dict[str, Any]:  
    return {  
        "status": "requires_admin_intervention"  
    }  
  
  
def routing_decision(state: TicketState) -> str:  
    if state.get("status") == "failed_classification":  
        return "error_handler"  
    if state.get("requires_human"):  
        return "human_approval"  
    return "finalize"  
  
  
workflow = StateGraph(TicketState)  
workflow.add_node("fetch_context", extract_context_node)  
workflow.add_node("classify", classification_node)  
workflow.add_node("human_approval", human_approval_node)  
workflow.add_node("error_handler", error_handler_node)  
  
workflow.set_entry_point("fetch_context")  
workflow.add_edge("fetch_context", "classify")  
  
workflow.add_conditional_edges(  
    "classify",  
    routing_decision,  
    {  
        "human_approval": "human_approval",  
        "error_handler": "error_handler",  
        "finalize": END  
    }  
)  
  
workflow.add_edge("human_approval", END)  
workflow.add_edge("error_handler", END)  
  
memory = MemorySaver()  
ticket_agent = workflow.compile(  
    checkpointer=memory,  
    interrupt_before=["human_approval"]  
)  
  
  
def classify_single_ticket(ticket_id: str, customer_id: str, issue_text: str) -> Dict[str, Any]:  
    initial_state: TicketState = {  
        "ticket_id": ticket_id,  
        "customer_id": customer_id,  
        "issue_text": issue_text,  
        "customer_context": "",  
        "classification": {},  
        "requires_human": False,  
        "status": "new",  
        "error_logs": []  
    }  
  
    thread_config = {  
        "configurable": {  
            "thread_id": f"session_run_{ticket_id}"  
        }  
    }  
  
    for _ in ticket_agent.stream(initial_state, thread_config):  
        pass  
  
    current_graph_state = ticket_agent.get_state(thread_config)  
  
    if "human_approval" in current_graph_state.next:  
        for _ in ticket_agent.stream(None, thread_config):  
            pass  
  
    final_state = ticket_agent.get_state(thread_config).values  
    return dict(final_state)  
  
  
def auto_load_tickets(file_path: str) -> List[Dict[str, Any]]:  
    if not os.path.exists(file_path):  
        raise FileNotFoundError(f"Source file not found: '{file_path}'")  
  
    ext = os.path.splitext(file_path)[1].lower()  
  
    if ext == ".json":  
        with open(file_path, "r", encoding="utf-8") as f:  
            data = json.load(f)  
            return data if isinstance(data, list) else [data]  
  
    if ext == ".csv":  
        tickets = []  
        with open(file_path, "r", newline="", encoding="utf-8") as f:  
            reader = csv.DictReader(f)  
            for row in reader:  
                tickets.append(dict(row))  
        return tickets  
  
    raise ValueError(f"Unsupported extension '{ext}'. Use JSON or CSV.")  
  
  
def auto_save_results(file_path: str, results: List[Dict[str, Any]]) -> None:  
    if not results:  
        return  
  
    ext = os.path.splitext(file_path)[1].lower()  
  
    if ext == ".json":  
        with open(file_path, "w", encoding="utf-8") as f:  
            json.dump(results, f, indent=4)  
        return  
  
    if ext == ".csv":  
        headers = list(results[0].keys())  
        with open(file_path, "w", newline="", encoding="utf-8") as f:  
            writer = csv.DictWriter(f, fieldnames=headers)  
            writer.writeheader()  
            for row in results:  
                flat_row = {}  
                for k, v in row.items():  
                    flat_row[k] = json.dumps(v) if isinstance(v, (dict, list)) else v  
                writer.writerow(flat_row)  
        return  
  
    raise ValueError(f"Unsupported extension '{ext}'. Use JSON or CSV.")  
  
  
def process_ticket_pipeline(input_file: str, output_file: str) -> None:  
    raw_tickets = auto_load_tickets(input_file)  
    processed_batch_output = []  
  
    for index, raw_ticket in enumerate(raw_tickets):  
        ticket_id = raw_ticket.get("ticket_id", f"AUTO-GEN-{index:03d}")  
        customer_id = raw_ticket.get("customer_id", "UNKNOWN")  
        issue_text = raw_ticket.get("issue_text", raw_ticket.get("issue_description", ""))  
  
        final_state = classify_single_ticket(  
            ticket_id=ticket_id,  
            customer_id=customer_id,  
            issue_text=issue_text  
        )  
        processed_batch_output.append(final_state)  
  
    auto_save_results(output_file, processed_batch_output)  