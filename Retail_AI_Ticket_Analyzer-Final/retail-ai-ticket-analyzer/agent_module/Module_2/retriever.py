
# retriever.py (FINAL)
# Usage:
#   from retriever import retrieve_documents
#   results = retrieve_documents("POS terminal frozen", "pos_failure")
#
# Run directly to test:
#   python retriever.py

import os
import json
import numpy as np
import faiss
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

# ----------------------------------------------------------------
# CONFIGURATION
# ----------------------------------------------------------------

GOOGLE_API_KEY   = os.getenv("GOOGLE_API_KEY")
EMBEDDING_MODEL  = "gemini-embedding-001"
CURRENT_DIR      = os.path.dirname(os.path.abspath(__file__))
INDEX_DIR        = os.path.join(CURRENT_DIR, "faiss_index")
INDEX_FILE       = os.path.join(INDEX_DIR, "index.faiss")
METADATA_FILE    = os.path.join(INDEX_DIR, "metadata.json")

TOP_K            = 5      # fetch top 5 for re-ranking
FINAL_TOP_K      = 3      # return top 3 after re-ranking
SCORE_THRESHOLD  = 0.8    # L2 distance cutoff — lower = stricter
MIN_SCORE        = 0.56   # minimum similarity score to include result

# ----------------------------------------------------------------
# VALID CATEGORIES — must match contract exactly
# ----------------------------------------------------------------

VALID_CATEGORIES = [
    "pos_failure",
    "scanner_issue",
    "self_checkout_failure",
    "pricing_mismatch",
    "network_outage",
    "payment_gateway_failure",
    "inventory_sync_failure",
    "order_delay",
    "product_defect",
    "account_issue",
    "fraud_alert",
]

# ----------------------------------------------------------------
# LOAD INDEX AND METADATA
# ----------------------------------------------------------------

def _load_resources():
    if not os.path.exists(INDEX_FILE):
        raise FileNotFoundError(
            f"FAISS index not found at {INDEX_FILE}. "
            "Run ingest.py first."
        )
    if not os.path.exists(METADATA_FILE):
        raise FileNotFoundError(
            f"Metadata not found at {METADATA_FILE}. "
            "Run ingest.py first."
        )
    index = faiss.read_index(INDEX_FILE)
    with open(METADATA_FILE, "r", encoding="utf-8") as f:
        metadata = json.load(f)
    print(f"RAG: Loaded FAISS index with {index.ntotal} vectors.")
    print(f"RAG: Loaded metadata with {len(metadata)} chunks.")
    return index, metadata


if not GOOGLE_API_KEY:
    raise ValueError(
        "GOOGLE_API_KEY not found. "
        "Add it to your .env file as GOOGLE_API_KEY=your_key_here"
    )

client = genai.Client(api_key=GOOGLE_API_KEY)
_faiss_index, _metadata = _load_resources()

# ----------------------------------------------------------------
# EMBED QUERY
# ----------------------------------------------------------------

def _embed_query(query: str) -> np.ndarray:
    result = client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=query,
        config=types.EmbedContentConfig(
            task_type="RETRIEVAL_QUERY"
        )
    )
    vector = np.array(result.embeddings[0].values, dtype=np.float32)
    return vector.reshape(1, -1)

# ----------------------------------------------------------------
# CATEGORY FILTER
# ----------------------------------------------------------------

def _filter_by_category(results: list[dict],
                         category: str) -> list[dict]:
    filtered = [r for r in results if r["category"] == category]
    if not filtered:
        print(f"RAG WARNING: No chunks found for category "
              f"'{category}'. Returning unfiltered results.")
        return results
    return filtered

# ----------------------------------------------------------------
# L2 DISTANCE TO SIMILARITY SCORE
# ----------------------------------------------------------------

def _l2_to_score(l2_distance: float) -> float:
    return round(1 / (1 + float(l2_distance)), 4)

# ----------------------------------------------------------------
# MAIN RETRIEVAL FUNCTION
# ----------------------------------------------------------------

def retrieve_documents(issue_description: str,
                       category: str) -> list[dict]:
    """
    Retrieve top 3 most relevant SOP chunks for a given ticket.

    Parameters:
        issue_description : str — the customer's issue text
        category          : str — must be one of VALID_CATEGORIES

    Returns:
        list of dicts: [{"doc_id": str, "content": str, "score": float}]
        Returns [] if no relevant document found above threshold.
    """
    try:
        # --- Validate category ---
        if category not in VALID_CATEGORIES:
            print(f"RAG WARNING: '{category}' is not a valid category. "
                  f"Valid values: {VALID_CATEGORIES}")
            print(f"RAG WARNING: Proceeding without category filter.")
            category = None

        # --- Embed query ---
        query_vector = _embed_query(issue_description)

        # --- FAISS search ---
        distances, indices = _faiss_index.search(query_vector, TOP_K)
        distances = distances[0]
        indices   = indices[0]

        # --- Build result list ---
        raw_results = []
        for dist, idx in zip(distances, indices):
            if idx == -1:
                continue
            chunk_meta = _metadata[idx]
            raw_results.append({
                "doc_id"  : chunk_meta["doc_id"],
                "content" : chunk_meta["content"],
                "category": chunk_meta["category"],
                "source"  : chunk_meta["source"],
                "l2_dist" : float(dist),
                "score"   : _l2_to_score(dist),
            })

        # --- Score threshold check ---
        if not raw_results or raw_results[0]["l2_dist"] > SCORE_THRESHOLD:
            print(
                f"RAG: No relevant document found. "
                f"Best L2: "
                f"{raw_results[0]['l2_dist'] if raw_results else 'N/A':.4f} "
                f"(threshold: {SCORE_THRESHOLD})"
            )
            return []

        # --- Category filter ---
        if category:
            filtered_results = _filter_by_category(raw_results, category)
        else:
            filtered_results = raw_results

        # --- Re-rank by score ---
        reranked = sorted(filtered_results,
                          key=lambda x: x["score"],
                          reverse=True)

        # --- Minimum score filter ---
        reranked = [r for r in reranked if r["score"] >= MIN_SCORE]

        if not reranked:
            print(f"RAG: All results below minimum score "
                  f"({MIN_SCORE}). Returning [].")
            return []

        # --- Return top FINAL_TOP_K ---
        final_results = reranked[:FINAL_TOP_K]

        output = [
            {
                "doc_id" : r["doc_id"],
                "content": r["content"],
                "score"  : r["score"],
            }
            for r in final_results
        ]

        print(f"RAG: Retrieved {len(output)} chunks for "
              f"category '{category}'.")
        for r in output:
            print(f"  {r['doc_id']} | score: {r['score']}")

        return output

    except Exception as e:
        print(f"RAG ERROR: retrieve_documents failed: {e}")
        return []


# ----------------------------------------------------------------
# TEST BLOCK 
# ----------------------------------------------------------------

if __name__ == "__main__":

    YOUR_QUERIES = [
        {
            "description": "POS freeze at counter",
            "query"      : "POS terminal at counter 3 froze during peak hours and wont restart",
            "category"   : "pos_failure",
        },
        {
            "description": "Damaged product received",
            "query"      : "Customer received a damaged item, box was torn and product broken inside",
            "category"   : "product_defect",   
        },
        {
            "description": "Payment not going through",
            "query"      : "Card payment is failing at checkout, tried multiple cards but none work",
            "category"   : "payment_gateway_failure",
        },
        {
            "description": "Order not delivered",
            "query"      : "My order was supposed to arrive 5 days ago and there is no update",
            "category"   : "order_delay",
        },
        {
            "description": "Suspicious transaction",
            "query"      : "Suspicious transaction flagged on customer account, possible stolen card",
            "category"   : "fraud_alert",
        },
        {
            "description": "Fallback test — irrelevant query",
            "query"      : "the weather is nice today and I like pizza",
            "category"   : "order_delay",
        },
    ]

    print("\n" + "="*60)
    print("RETRIEVER TEST — Running your queries")
    print("="*60)

    for i, test in enumerate(YOUR_QUERIES):
        print(f"\n[TEST {i+1}] {test['description']}")
        print(f"Query    : {test['query']}")
        print(f"Category : {test['category']}")
        print("-" * 40)

        results = retrieve_documents(
            issue_description=test["query"],
            category=test["category"]
        )

        if not results:
            print("RESULT   : No relevant document found — fallback triggered.")
        else:
            print(f"RESULT   : {len(results)} chunk(s) retrieved")
            for j, r in enumerate(results):
                print(f"\n  Chunk {j+1}:")
                print(f"  doc_id  : {r['doc_id']}")
                print(f"  score   : {r['score']}")
                print(f"  content : {r['content'][:300]}...")

    print("\n" + "="*60)
    print("All tests complete.")
    print("="*60)
  