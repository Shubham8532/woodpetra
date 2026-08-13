import os
import asyncio
import httpx
from pathlib import Path
from fastapi import FastAPI, Request, Response, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from backend.graph import workflow


# 1. Load local .env variables
load_dotenv()

app = FastAPI(title="Shubham Fashion Assistant - Local Dev (Async)")

# WhatsApp Credentials (Loaded from local .env)
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "woodpetra_secret_token_123")
ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")

# CORS middleware for local frontend/testing
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
TEMPLATE_DIR = FRONTEND_DIR / "template"
DATA_DIR = BASE_DIR / "data"

class ChatRequest(BaseModel):
    query: str
    thread_id: str

NO_CACHE_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0"
}

# --- 2. LOCAL & HEALTH ENDPOINTS ---

@app.get("/")
async def read_root():
    index_file = TEMPLATE_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file), headers=NO_CACHE_HEADERS)
    return {"status": "error", "message": f"Looking for {index_file} but not found."}

@app.get("/health")
def health_check():
    return {"status": "ok", "message": "Shubham Fashion Assistant Local API is running"}

# Local API endpoint for Web UI testing
@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
    config = {"configurable": {"thread_id": request.thread_id}}
    result = workflow.invoke({"query": request.query}, config=config)
    return {
        "response": result.get("response", "Sorry, something went wrong."),
        "displayed_products": result.get("displayed_products", []),
        "similar_products": result.get("similar_products", [])
    }

# --- 3. ASYNC WHATSAPP WEBHOOK WORKER ---

async def process_whatsapp_message(user_text: str, from_number: str):
    """Background task: processes LangGraph workflow and sends WhatsApp messages asynchronously."""
    try:
        url = f"https://graph.facebook.com/v26.0/{PHONE_NUMBER_ID}/messages"
        headers = {
            "Authorization": f"Bearer {ACCESS_TOKEN}",
            "Content-Type": "application/json"
        }

        # Standalone greeting fast-path
        clean_text = "".join(ch for ch in user_text.lower().strip() if ch.isalnum() or ch == " ")
        GREETING_WORDS = {
            "hi", "hii", "hiii", "hello", "hey", "helo", "hlo", "hola",
            "good morning", "good afternoon", "good evening", "goodnight",
            "gud morning", "gud mrng", "greetings", "namaste", "namaskar"
        }

        if clean_text in GREETING_WORDS:
            greet_payload = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": from_number,
                "type": "text",
                "text": {"body": "Hello! Welcome to Shubham Fashion. What apparel or style are you looking for today?"}
            }
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(url, json=greet_payload, headers=headers)
            return

        # Execute LangGraph workflow in background thread
        config = {"configurable": {"thread_id": f"wa_{from_number}"}}
        result = workflow.invoke({"query": user_text}, config=config)

        bot_reply = result.get("response", "Sorry, I couldn't process that.")
        displayed_products = result.get("displayed_products", [])

        async with httpx.AsyncClient(timeout=10.0) as client:
            # 1. Send text response
            text_payload = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": from_number,
                "type": "text",
                "text": {"body": bot_reply}
            }
            await client.post(url, json=text_payload, headers=headers)

            # 2. Send Interactive Product List Drawer
            if displayed_products:
                rows = []
                for idx, prod in enumerate(displayed_products[:10]):
                    prod_id = str(prod.get("id", idx))
                    title = (prod.get("name") or prod.get("title") or f"Item {idx+1}")[:24]

                    price_val = prod.get("price")
                    price = f"₹{price_val}" if price_val is not None and str(price_val).strip() != "" else ""
                    color = prod.get("color") or prod.get("colour") or ""
                    size = prod.get("size") or ""

                    desc_parts = []
                    if color:
                        desc_parts.append(str(color).title())
                    if size:
                        desc_parts.append(f"Size: {size}")
                    if price:
                        desc_parts.append(price)

                    row_desc = " | ".join(desc_parts) if desc_parts else "In Stock"

                    rows.append({
                        "id": f"prod_{prod_id}",
                        "title": title,
                        "description": row_desc[:72]
                    })

                list_payload = {
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": from_number,
                    "type": "interactive",
                    "interactive": {
                        "type": "list",
                        "header": {"type": "text", "text": "Matching Items"},
                        "body": {"text": "Tap below to view item details:"},
                        "footer": {"text": "Shubham Fashion Assistant"},
                        "action": {
                            "button": "View Products",
                            "sections": [{"title": "Search Results", "rows": rows}]
                        }
                    }
                }
                await client.post(url, json=list_payload, headers=headers)

    except Exception as e:
        print(f"[Webhook Background Error]: {e}")


# Webhook Verification (GET)
@app.get("/webhook/whatsapp")
async def verify_webhook(request: Request):
    params = dict(request.query_params)
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return PlainTextResponse(content=challenge, status_code=200)
    return PlainTextResponse(content="Verification failed", status_code=403)


# Webhook Message Receiver (POST - Instant HTTP 200 OK)
@app.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()
    try:
        entry = data.get("entry", [])[0]
        changes = entry.get("changes", [])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])

        if messages:
            msg = messages[0]
            from_number = msg["from"]
            msg_type = msg.get("type", "text")

            user_text = ""
            if msg_type == "text":
                user_text = msg.get("text", {}).get("body", "")
            elif msg_type == "interactive":
                interactive = msg.get("interactive", {})
                if interactive.get("type") == "button_reply":
                    user_text = interactive.get("button_reply", {}).get("title", "")
                elif interactive.get("type") == "list_reply":
                    user_text = interactive.get("list_reply", {}).get("title", "")
            else:
                user_text = "Hello"

            if user_text.strip():
                print(f"\n[WhatsApp Incoming] From: {from_number} | Message: {user_text}")
                background_tasks.add_task(process_whatsapp_message, user_text, from_number)

    except Exception as e:
        print(f"[Webhook Error]: {e}")

    return {"status": "ok"}


# --- 4. STATIC MOUNTS & PAGES ---

if (FRONTEND_DIR / "css").exists():
    app.mount("/css", StaticFiles(directory=str(FRONTEND_DIR / "css")), name="css")

if (FRONTEND_DIR / "js").exists():
    app.mount("/js", StaticFiles(directory=str(FRONTEND_DIR / "js")), name="js")

if DATA_DIR.exists():
    app.mount("/data", StaticFiles(directory=str(DATA_DIR)), name="data")

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

@app.get("/{page_name}")
async def read_page(page_name: str):
    if page_name.startswith(("data", "static", "css", "js", "api", "webhook", "robots")):
        return Response(status_code=404)

    if not page_name.endswith(".html"):
        page_name = f"{page_name}.html"

    page_file = TEMPLATE_DIR / page_name
    if page_file.exists():
        return FileResponse(str(page_file), headers=NO_CACHE_HEADERS)
    return FileResponse(str(TEMPLATE_DIR / "index.html"), headers=NO_CACHE_HEADERS)