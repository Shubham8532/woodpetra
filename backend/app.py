# import os
# import asyncio
# import httpx
# from pathlib import Path
# from fastapi import FastAPI, Request, Response, BackgroundTasks
# from fastapi.middleware.cors import CORSMiddleware
# from fastapi.staticfiles import StaticFiles
# from fastapi.responses import FileResponse, PlainTextResponse
# from pydantic import BaseModel
# from backend.graph import workflow

# app = FastAPI(title="Shubham Fashion Assistant - Azure Production")

# # WhatsApp Credentials (Fetched directly from Azure App Service Configuration)
# VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "woodpetra_secret_token_123")
# ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")
# PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# BASE_DIR = Path(__file__).resolve().parent.parent
# FRONTEND_DIR = BASE_DIR / "frontend"
# TEMPLATE_DIR = FRONTEND_DIR / "template"
# DATA_DIR = BASE_DIR / "data"

# class ChatRequest(BaseModel):
#     query: str
#     thread_id: str

# NO_CACHE_HEADERS = {
#     "Cache-Control": "no-cache, no-store, must-revalidate",
#     "Pragma": "no-cache",
#     "Expires": "0"
# }

# # 1. Primary Root & Health Check Routes
# @app.get("/")
# async def read_root():
#     index_file = TEMPLATE_DIR / "index.html"
#     if index_file.exists():
#         return FileResponse(str(index_file), headers=NO_CACHE_HEADERS)
#     return {"status": "error", "message": f"Looking for {index_file} but not found."}

# @app.get("/health")
# def health_check():
#     return {"status": "ok", "message": "Shubham Fashion Assistant API is running"}


# GREETING_WORDS = {
#     "hi", "hii", "hiii", "hello", "hey", "helo", "hlo", "hola",
#     "good morning", "good afternoon", "good evening", "goodnight",
#     "gud morning", "gud mrng", "greetings", "namaste", "namaskar"
# }

# # 2. Chat API Endpoint
# @app.post("/api/chat")
# async def chat_endpoint(request: ChatRequest):
#     user_query = request.query.strip()
#     clean_text = "".join(ch for ch in user_query.lower() if ch.isalnum() or ch == " ")

#     # ── FAST-PATH: Standalone Greetings (0.00s Instant Response) ──
#     if clean_text in GREETING_WORDS:
#         return {
#             "response": "Hello! Welcome to Shubham Fashion. What apparel or style are you looking for today?",
#             "displayed_products": [],
#             "similar_products": []
#         }

#     # ── LangGraph Workflow Execution ──
#     config = {
#         "configurable": {
#             "thread_id": request.thread_id
#         }
#     }
#     result = workflow.invoke(
#         {"query": request.query},
#         config=config
#     )
#     return {
#         "response": result.get("response", "Sorry, something went wrong."),
#         "displayed_products": result.get("displayed_products", []),
#         "similar_products": result.get("similar_products", [])
#     }
# # --- 3. WHATSAPP WEBHOOK WORKER & ENDPOINTS ---

# async def process_whatsapp_message(user_text: str, from_number: str):
#     """Background task to process workflow and send WhatsApp response asynchronously."""
#     try:
#         url = f"https://graph.facebook.com/v26.0/{PHONE_NUMBER_ID}/messages"
#         headers = {
#             "Authorization": f"Bearer {ACCESS_TOKEN}",
#             "Content-Type": "application/json"
#         }

#         # FAST-PATH EXIT FOR STANDALONE GREETINGS ONLY
#         clean_text = "".join(ch for ch in user_text.lower().strip() if ch.isalnum() or ch == " ")
        

#         if clean_text in GREETING_WORDS:
#             greet_payload = {
#                 "messaging_product": "whatsapp",
#                 "recipient_type": "individual",
#                 "to": from_number,
#                 "type": "text",
#                 "text": {"body": "Hello! Welcome to Shubham Fashion. What apparel or style are you looking for today?"}
#             }
#             async with httpx.AsyncClient(timeout=5.0) as client:
#                 await client.post(url, json=greet_payload, headers=headers)
#             return

#         # Execute LangGraph workflow in background
#         config = {"configurable": {"thread_id": f"wa_{from_number}"}}
#         result = workflow.invoke({"query": user_text}, config=config)

#         bot_reply = result.get("response", "Sorry, I couldn't process that.")
#         displayed_products = result.get("displayed_products", [])

#         async with httpx.AsyncClient(timeout=10.0) as client:
#             # 1. Send main text response
#             text_payload = {
#                 "messaging_product": "whatsapp",
#                 "recipient_type": "individual",
#                 "to": from_number,
#                 "type": "text",
#                 "text": {"body": bot_reply}
#             }
#             await client.post(url, json=text_payload, headers=headers)

#             # 2. Send Interactive List Drawer with Rich Attributes
#             if displayed_products:
#                 rows = []
#                 for idx, prod in enumerate(displayed_products[:10]):
#                     prod_id = str(prod.get("id", idx))
#                     title = (prod.get("name") or prod.get("title") or f"Item {idx+1}")[:24]

#                     price_val = prod.get("price")
#                     price = f"₹{price_val}" if price_val is not None and str(price_val).strip() != "" else ""
#                     color = prod.get("color") or prod.get("colour") or ""
#                     size = prod.get("size") or ""

#                     desc_parts = []
#                     if color:
#                         desc_parts.append(str(color).title())
#                     if size:
#                         desc_parts.append(f"Size: {size}")
#                     if price:
#                         desc_parts.append(price)

#                     row_desc = " | ".join(desc_parts) if desc_parts else "In Stock"

#                     rows.append({
#                         "id": f"prod_{prod_id}",
#                         "title": title,
#                         "description": row_desc[:72]
#                     })

#                 list_payload = {
#                     "messaging_product": "whatsapp",
#                     "recipient_type": "individual",
#                     "to": from_number,
#                     "type": "interactive",
#                     "interactive": {
#                         "type": "list",
#                         "header": {"type": "text", "text": "Matching Items"},
#                         "body": {"text": "Tap below to view item details:"},
#                         "footer": {"text": "Shubham Fashion Assistant"},
#                         "action": {
#                             "button": "View Products",
#                             "sections": [{"title": "Search Results", "rows": rows}]
#                         }
#                     }
#                 }
#                 await client.post(url, json=list_payload, headers=headers)

#     except Exception as e:
#         print(f"[Webhook Background Error]: {e}")


# # Verification Handshake Endpoint (GET)
# @app.get("/webhook/whatsapp")
# async def verify_webhook(request: Request):
#     params = dict(request.query_params)
#     mode = params.get("hub.mode")
#     token = params.get("hub.verify_token")
#     challenge = params.get("hub.challenge")

#     print(f"\n[Meta Verification] Mode: {mode} | Token: {token} | Challenge: {challenge}")

#     if mode == "subscribe" and token == VERIFY_TOKEN:
#         return PlainTextResponse(content=challenge, status_code=200)
#     return PlainTextResponse(content="Verification failed", status_code=403)


# # Message Listener Endpoint (POST - Instant 200 OK + Async Worker)
# @app.post("/webhook/whatsapp")
# async def whatsapp_webhook(request: Request, background_tasks: BackgroundTasks):
#     data = await request.json()
#     try:
#         entry = data.get("entry", [])[0]
#         changes = entry.get("changes", [])[0]
#         value = changes.get("value", {})
#         messages = value.get("messages", [])

#         if messages:
#             msg = messages[0]
#             from_number = msg["from"]
#             msg_type = msg.get("type", "text")

#             user_text = ""
#             if msg_type == "text":
#                 user_text = msg.get("text", {}).get("body", "")
#             elif msg_type == "interactive":
#                 interactive = msg.get("interactive", {})
#                 if interactive.get("type") == "button_reply":
#                     user_text = interactive.get("button_reply", {}).get("title", "")
#                 elif interactive.get("type") == "list_reply":
#                     user_text = interactive.get("list_reply", {}).get("title", "")
#             else:
#                 user_text = "Hello"

#             if user_text.strip():
#                 print(f"\n[WhatsApp Incoming] From: {from_number} | Message: {user_text}")
#                 # Pass message handling to background worker thread
#                 background_tasks.add_task(process_whatsapp_message, user_text, from_number)

#     except Exception as e:
#         print(f"[Webhook Error]: {e}")

#     # Return HTTP 200 OK to Meta immediately (< 5ms) to prevent UI delays
#     return {"status": "ok"}


# # 4. Static & Data Directory Mounts
# if (FRONTEND_DIR / "css").exists():
#     app.mount("/css", StaticFiles(directory=str(FRONTEND_DIR / "css")), name="css")

# if (FRONTEND_DIR / "js").exists():
#     app.mount("/js", StaticFiles(directory=str(FRONTEND_DIR / "js")), name="js")

# if DATA_DIR.exists():
#     app.mount("/data", StaticFiles(directory=str(DATA_DIR)), name="data")

# if FRONTEND_DIR.exists():
#     app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


# # 5. HTML Page Handler
# @app.get("/{page_name}")
# async def read_page(page_name: str):
#     if page_name.startswith(("data", "static", "css", "js", "api", "webhook", "robots")):
#         return Response(status_code=404)

#     if not page_name.endswith(".html"):
#         page_name = f"{page_name}.html"

#     page_file = TEMPLATE_DIR / page_name
#     if page_file.exists():
#         return FileResponse(str(page_file), headers=NO_CACHE_HEADERS)
#     return FileResponse(str(TEMPLATE_DIR / "index.html"), headers=NO_CACHE_HEADERS)



import os
import asyncio
import httpx
from pathlib import Path
from fastapi import FastAPI, Request, Response, BackgroundTasks, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel
from backend.graph import workflow
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse

app = FastAPI(title="Shubham Fashion Assistant - Azure Production")

# WhatsApp Credentials (Fetched directly from Azure App Service Configuration)
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "woodpetra_secret_token_123")
ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")

# Twilio Credentials (Fetched from Azure Configuration)
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")

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


GREETING_WORDS = {
    "hi", "hii", "hiii", "hello", "hey", "helo", "hlo", "hola",
    "good morning", "good afternoon", "good evening", "goodnight",
    "gud morning", "gud mrng", "greetings", "namaste", "namaskar"
}

# 2. Chat API Endpoint
@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
    user_query = request.query.strip()
    clean_text = "".join(ch for ch in user_query.lower() if ch.isalnum() or ch == " ")

    # ── FAST-PATH: Standalone Greetings (0.00s Instant Response) ──
    if clean_text in GREETING_WORDS:
        return {
            "response": "Hello! Welcome to Shubham Fashion. What apparel or style are you looking for today?",
            "displayed_products": [],
            "similar_products": []
        }

    # ── LangGraph Workflow Execution ──
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

# --- 3. TWILIO WHATSAPP WEBHOOK (ACTIVE) ---

@app.post("/webhook/twilio")
async def twilio_webhook(
    From: str = Form(...),
    Body: str = Form(...)
):
    user_query = Body.strip()
    clean_text = "".join(ch for ch in user_query.lower() if ch.isalnum() or ch == " ")

    # Standalone greeting check
    if clean_text in GREETING_WORDS:
        bot_reply = "Hello! Welcome to Shubham Fashion. What apparel or style are you looking for today?"
        displayed_products = []
    else:
        thread_id = f"twilio_{From.replace(':', '_').replace('+', '')}"
        config = {"configurable": {"thread_id": thread_id}}
        result = workflow.invoke({"query": user_query}, config=config)

        bot_reply = result.get("response", "Sorry, I couldn't process that.")
        displayed_products = result.get("displayed_products", [])

    # Format text for WhatsApp
    reply_lines = [bot_reply]
    if displayed_products:
        reply_lines.append("\n🛍️ *Matching Items:*")
        for idx, prod in enumerate(displayed_products[:5], 1):
            title = prod.get("name") or prod.get("title") or f"Item {idx}"
            price_val = prod.get("price")
            price = f"₹{price_val}" if price_val is not None and str(price_val).strip() != "" else ""
            color = prod.get("color") or prod.get("colour") or ""
            size = prod.get("size") or ""

            details = [d for d in [str(color).title() if color else "", f"Size: {size}" if size else "", price] if d]
            detail_str = f" ({' | '.join(details)})" if details else ""
            reply_lines.append(f"{idx}. *{title}*{detail_str}")

    final_message = "\n".join(reply_lines)

    # Return pure TwiML (No REST API call, no ContentSid error)
    twiml_resp = MessagingResponse()
    twiml_resp.message(final_message)
    return Response(content=str(twiml_resp), media_type="application/xml")


# --- 3. META WHATSAPP WEBHOOK WORKER & ENDPOINTS (COMMENTED OUT) ---

# async def process_whatsapp_message(user_text: str, from_number: str):
#     """Background task to process workflow and send WhatsApp response asynchronously."""
#     try:
#         url = f"https://graph.facebook.com/v26.0/{PHONE_NUMBER_ID}/messages"
#         headers = {
#             "Authorization": f"Bearer {ACCESS_TOKEN}",
#             "Content-Type": "application/json"
#         }
#
#         # FAST-PATH EXIT FOR STANDALONE GREETINGS ONLY
#         clean_text = "".join(ch for ch in user_text.lower().strip() if ch.isalnum() or ch == " ")
#
#         if clean_text in GREETING_WORDS:
#             greet_payload = {
#                 "messaging_product": "whatsapp",
#                 "recipient_type": "individual",
#                 "to": from_number,
#                 "type": "text",
#                 "text": {"body": "Hello! Welcome to Shubham Fashion. What apparel or style are you looking for today?"}
#             }
#             async with httpx.AsyncClient(timeout=5.0) as client:
#                 await client.post(url, json=greet_payload, headers=headers)
#             return
#
#         # Execute LangGraph workflow in background
#         config = {"configurable": {"thread_id": f"wa_{from_number}"}}
#         result = workflow.invoke({"query": user_text}, config=config)
#
#         bot_reply = result.get("response", "Sorry, I couldn't process that.")
#         displayed_products = result.get("displayed_products", [])
#
#         async with httpx.AsyncClient(timeout=10.0) as client:
#             # 1. Send main text response
#             text_payload = {
#                 "messaging_product": "whatsapp",
#                 "recipient_type": "individual",
#                 "to": from_number,
#                 "type": "text",
#                 "text": {"body": bot_reply}
#             }
#             await client.post(url, json=text_payload, headers=headers)
#
#             # 2. Send Interactive List Drawer with Rich Attributes
#             if displayed_products:
#                 rows = []
#                 for idx, prod in enumerate(displayed_products[:10]):
#                     prod_id = str(prod.get("id", idx))
#                     title = (prod.get("name") or prod.get("title") or f"Item {idx+1}")[:24]
#
#                     price_val = prod.get("price")
#                     price = f"₹{price_val}" if price_val is not None and str(price_val).strip() != "" else ""
#                     color = prod.get("color") or prod.get("colour") or ""
#                     size = prod.get("size") or ""
#
#                     desc_parts = []
#                     if color:
#                         desc_parts.append(str(color).title())
#                     if size:
#                         desc_parts.append(f"Size: {size}")
#                     if price:
#                         desc_parts.append(price)
#
#                     row_desc = " | ".join(desc_parts) if desc_parts else "In Stock"
#
#                     rows.append({
#                         "id": f"prod_{prod_id}",
#                         "title": title,
#                         "description": row_desc[:72]
#                     })
#
#                 list_payload = {
#                     "messaging_product": "whatsapp",
#                     "recipient_type": "individual",
#                     "to": from_number,
#                     "type": "interactive",
#                     "interactive": {
#                         "type": "list",
#                         "header": {"type": "text", "text": "Matching Items"},
#                         "body": {"text": "Tap below to view item details:"},
#                         "footer": {"text": "Shubham Fashion Assistant"},
#                         "action": {
#                             "button": "View Products",
#                             "sections": [{"title": "Search Results", "rows": rows}]
#                         }
#                     }
#                 }
#                 await client.post(url, json=list_payload, headers=headers)
#
#     except Exception as e:
#         print(f"[Webhook Background Error]: {e}")
#
#
# # Verification Handshake Endpoint (GET)
# @app.get("/webhook/whatsapp")
# async def verify_webhook(request: Request):
#     params = dict(request.query_params)
#     mode = params.get("hub.mode")
#     token = params.get("hub.verify_token")
#     challenge = params.get("hub.challenge")
#
#     print(f"\n[Meta Verification] Mode: {mode} | Token: {token} | Challenge: {challenge}")
#
#     if mode == "subscribe" and token == VERIFY_TOKEN:
#         return PlainTextResponse(content=challenge, status_code=200)
#     return PlainTextResponse(content="Verification failed", status_code=403)
#
#
# # Message Listener Endpoint (POST - Instant 200 OK + Async Worker)
# @app.post("/webhook/whatsapp")
# async def whatsapp_webhook(request: Request, background_tasks: BackgroundTasks):
#     data = await request.json()
#     try:
#         entry = data.get("entry", [])[0]
#         changes = entry.get("changes", [])[0]
#         value = changes.get("value", {})
#         messages = value.get("messages", [])
#
#         if messages:
#             msg = messages[0]
#             from_number = msg["from"]
#             msg_type = msg.get("type", "text")
#
#             user_text = ""
#             if msg_type == "text":
#                 user_text = msg.get("text", {}).get("body", "")
#             elif msg_type == "interactive":
#                 interactive = msg.get("interactive", {})
#                 if interactive.get("type") == "button_reply":
#                     user_text = interactive.get("button_reply", {}).get("title", "")
#                 elif interactive.get("type") == "list_reply":
#                     user_text = interactive.get("list_reply", {}).get("title", "")
#             else:
#                 user_text = "Hello"
#
#             if user_text.strip():
#                 print(f"\n[WhatsApp Incoming] From: {from_number} | Message: {user_text}")
#                 # Pass message handling to background worker thread
#                 background_tasks.add_task(process_whatsapp_message, user_text, from_number)
#
#     except Exception as e:
#         print(f"[Webhook Error]: {e}")
#
#     # Return HTTP 200 OK to Meta immediately (< 5ms) to prevent UI delays
#     return {"status": "ok"}


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