import os
import asyncio
import httpx
from pathlib import Path
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel
from backend.graph import workflow

app = FastAPI(title="Shubham Fashion Assistant - Azure Production")

# WhatsApp Credentials (Fetched directly from Azure App Service Configuration)
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "woodpetra_secret_token_123")
ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")

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

# 1. Primary Root & Health Check Routes
@app.get("/")
async def read_root():
    index_file = TEMPLATE_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file), headers=NO_CACHE_HEADERS)
    return {"status": "error", "message": f"Looking for {index_file} but not found."}

@app.get("/health")
def health_check():
    return {"status": "ok", "message": "Shubham Fashion Assistant API is running"}

# 2. Chat API Endpoint
@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
    config = {
        "configurable": {
            "thread_id": request.thread_id
        }
    }
    result = workflow.invoke(
        {"query": request.query},
        config=config
    )
    return {
        "response": result.get("response", "Sorry, something went wrong."),
        "displayed_products": result.get("displayed_products", []),
        "similar_products": result.get("similar_products", [])
    }

# --- 3. WHATSAPP WEBHOOK ENDPOINTS ---

# Verification Handshake Endpoint (GET)
@app.get("/webhook/whatsapp")
async def verify_webhook(request: Request):
    params = dict(request.query_params)
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    print(f"\n[Meta Verification] Mode: {mode} | Token: {token} | Challenge: {challenge}")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return PlainTextResponse(content=challenge, status_code=200)
    return PlainTextResponse(content="Verification failed", status_code=403)

# Message Listener Endpoint (POST - Async & Interactive UI Optimized)
@app.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request):
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

            # Extract text from user message
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

            if not user_text.strip():
                return {"status": "ok"}

            print(f"\n[WhatsApp Incoming] From: {from_number} | Message: {user_text}")

            url = f"https://graph.facebook.com/v26.0/{PHONE_NUMBER_ID}/messages"
            headers = {
                "Authorization": f"Bearer {ACCESS_TOKEN}",
                "Content-Type": "application/json"
            }

            # STRICT FAST-PATH EXIT FOR GREETINGS (Bypasses LLM entirely -> < 200ms)
            clean_text = "".join(ch for ch in user_text.lower().strip() if ch.isalnum() or ch == " ")
            GREETING_WORDS = {
                "hi", "hii", "hiii", "hello", "hey", "helo", "hlo", "hola",
                "good morning", "good afternoon", "good evening", "goodnight",
                "gud morning", "gud mrng", "greetings"
            }
            
            if clean_text in GREETING_WORDS or any(clean_text.startswith(g) for g in GREETING_WORDS):
                greet_payload = {
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": from_number,
                    "type": "text",
                    "text": {"body": "Hello! Welcome to Shubham Fashion. What apparel or style are you looking for today?"}
                }
                async with httpx.AsyncClient(timeout=5.0) as client:
                    await client.post(url, json=greet_payload, headers=headers)
                return {"status": "ok"}

            # Execute LangGraph workflow for complex product searches
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

                # 2. Send Interactive List Drawer for Products (Fast & Clean UI)
                if displayed_products:
                    rows = []
                    for idx, prod in enumerate(displayed_products[:10]):
                        prod_id = str(prod.get("id", idx))
                        title = (prod.get("title") or prod.get("name") or f"Item {idx+1}")[:24]
                        price = f"₹{prod.get('price', '')}" if prod.get('price') else "In Stock"
                        
                        rows.append({
                            "id": f"prod_{prod_id}",
                            "title": title,
                            "description": price[:72]
                        })

                    list_payload = {
                        "messaging_product": "whatsapp",
                        "recipient_type": "individual",
                        "to": from_number,
                        "type": "interactive",
                        "interactive": {
                            "type": "list",
                            "header": {"type": "text", "text": "Matching Items"},
                            "body": {"text": "Select an item to view details on our store:"},
                            "footer": {"text": "Shubham Fashion Assistant"},
                            "action": {
                                "button": "View Products",
                                "sections": [{"title": "Results Found", "rows": rows}]
                            }
                        }
                    }
                    await client.post(url, json=list_payload, headers=headers)

    except Exception as e:
        print(f"[Webhook Error]: {e}")

    return {"status": "ok"}

# 4. Static & Data Directory Mounts
if (FRONTEND_DIR / "css").exists():
    app.mount("/css", StaticFiles(directory=str(FRONTEND_DIR / "css")), name="css")

if (FRONTEND_DIR / "js").exists():
    app.mount("/js", StaticFiles(directory=str(FRONTEND_DIR / "js")), name="js")

if DATA_DIR.exists():
    app.mount("/data", StaticFiles(directory=str(DATA_DIR)), name="data")

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

# 5. HTML Page Handler
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