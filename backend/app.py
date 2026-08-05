import os
import asyncio
import httpx
from pathlib import Path
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
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

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return Response(content=challenge, media_type="text/plain")
    return Response(content="Verification failed", status_code=403)

# Message Listener Endpoint (POST - Async Optimized)
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

            # Execute LangGraph workflow
            config = {"configurable": {"thread_id": f"wa_{from_number}"}}
            result = workflow.invoke({"query": user_text}, config=config)
            
            bot_reply = result.get("response", "Sorry, I couldn't process that.")
            displayed_products = result.get("displayed_products", [])

            # Meta Cloud API Details
            url = f"https://graph.facebook.com/v26.0/{PHONE_NUMBER_ID}/messages"
            headers = {
                "Authorization": f"Bearer {ACCESS_TOKEN}",
                "Content-Type": "application/json"
            }

            # Non-blocking async client for Meta Cloud API calls
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Send text response first
                text_payload = {
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": from_number,
                    "type": "text",
                    "text": {"body": bot_reply}
                }
                await client.post(url, json=text_payload, headers=headers)

                # Prepare image payload tasks for concurrent execution
                if displayed_products:
                    image_tasks = []
                    for prod in displayed_products[:3]:
                        img_url = prod.get("image_url") or prod.get("image") or prod.get("img")
                        title = prod.get("title") or prod.get("name") or "Product"
                        price = prod.get("price", "")
                        description = prod.get("description", "")

                        caption_text = f"*{title}*"
                        if price:
                            caption_text += f"\nPrice: {price}"
                        if description:
                            caption_text += f"\n{description}"

                        if img_url and img_url.startswith("http"):
                            img_payload = {
                                "messaging_product": "whatsapp",
                                "recipient_type": "individual",
                                "to": from_number,
                                "type": "image",
                                "image": {
                                    "link": img_url,
                                    "caption": caption_text
                                }
                            }
                            # Add POST request coroutine to task pool
                            image_tasks.append(client.post(url, json=img_payload, headers=headers))

                    # Dispatch all product image requests in parallel
                    if image_tasks:
                        responses = await asyncio.gather(*image_tasks, return_exceptions=True)
                        for resp in responses:
                            if isinstance(resp, httpx.Response):
                                print(f"[Product Image Sent]: {resp.status_code}")

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
    if page_name.startswith(("data", "static", "css", "js", "api", "webhook")):
        return {"status": "error", "message": "Not found"}

    if not page_name.endswith(".html"):
        page_name = f"{page_name}.html"
        
    page_file = TEMPLATE_DIR / page_name
    if page_file.exists():
        return FileResponse(str(page_file), headers=NO_CACHE_HEADERS)
    return FileResponse(str(TEMPLATE_DIR / "index.html"), headers=NO_CACHE_HEADERS)