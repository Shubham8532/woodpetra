import os
import csv
import io
import asyncio
import httpx
from pathlib import Path
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
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

# --- META COMMERCE CATALOG CSV ENDPOINT ---
@app.get("/api/catalog-feed.csv")
async def get_meta_catalog_feed(secret: str = ""):
    if secret != VERIFY_TOKEN:
        return Response(content="Unauthorized", status_code=401)

    try:
        # Fetch initial state or graph memory to pull all catalog products
        # (Calls graph retriever to get complete dataset directly from Supabase DB)
        from backend.db import get_all_products
        products = get_all_products()

        output = io.StringIO()
        writer = csv.writer(output)
        
        # Meta Commerce Required CSV Headers
        writer.writerow(["id", "title", "description", "availability", "condition", "price", "link", "image_link", "brand"])

        for prod in products:
            prod_id = str(prod.get("id", ""))
            title = prod.get("name") or prod.get("title", "")
            desc = prod.get("description", "Quality apparel product")
            price = f"{prod.get('price', 0)} INR"
            image_url = prod.get("image_url", "https://placehold.co/600x600")
            product_link = f"https://woodpetra-assistant-bcdmawbgh3g6bvcu.southeastasia-01.azurewebsites.net/?product={prod_id}"

            writer.writerow([
                prod_id,
                title,
                desc,
                "in stock",
                "new",
                price,
                product_link,
                image_url,
                "Shubham Fashion"
            ])

        output.seek(0)
        return StreamingResponse(
            io.BytesIO(output.getvalue().encode('utf-8')),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=catalog.csv"}
        )

    except Exception as e:
        print(f"[Catalog Feed Error]: {e}")
        return Response(content=f"Error generating feed: {str(e)}", status_code=500)

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

            url = f"https://graph.facebook.com/v26.0/{PHONE_NUMBER_ID}/messages"
            headers = {
                "Authorization": f"Bearer {ACCESS_TOKEN}",
                "Content-Type": "application/json"
            }

            # FAST-PATH: Fuzzy Intent Greeting Check (Bypasses 6s LLM Router Overhead)
            greetings = [
                "hi", "hello", "hey", "hii", "helo", "hlo", "hola", 
                "greetings", "good morning", "goodafternoon", 
                "good evening", "goodnight", "gud morning", "gud mrng"
            ]

            clean_text = "".join(ch for ch in user_text.lower().strip() if ch.isalnum() or ch == " ")
            is_simple_greeting = any(clean_text.startswith(g) for g in greetings)

            if is_simple_greeting and len(clean_text) <= 20:
                greet_payload = {
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": from_number,
                    "type": "text",
                    "text": {"body": "Hello! Welcome to Shubham Fashion. What apparel or style are you looking for today?"}
                }
                async with httpx.AsyncClient(timeout=10.0) as client:
                    await client.post(url, json=greet_payload, headers=headers)
                return {"status": "ok"}
            # Execute LangGraph workflow for complex queries
            config = {"configurable": {"thread_id": f"wa_{from_number}"}}
            result = workflow.invoke({"query": user_text}, config=config)
            
            bot_reply = result.get("response", "Sorry, I couldn't process that.")
            displayed_products = result.get("displayed_products", [])

            # Non-blocking async client for Meta Cloud API calls
            async with httpx.AsyncClient(timeout=10.0) as client:
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
                    for prod in displayed_products[:5]:
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
                            image_tasks.append(client.post(url, json=img_payload, headers=headers))

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
    if page_name.startswith(("data", "static", "css", "js", "api", "webhook", "robots")):
        return Response(status_code=404)

    if not page_name.endswith(".html"):
        page_name = f"{page_name}.html"
        
    page_file = TEMPLATE_DIR / page_name
    if page_file.exists():
        return FileResponse(str(page_file), headers=NO_CACHE_HEADERS)
    return FileResponse(str(TEMPLATE_DIR / "index.html"), headers=NO_CACHE_HEADERS)