import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from backend.graph import workflow

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Resolve absolute path to the root working directory (/app)
BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"

# Mount static files dynamically using absolute paths
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

class ChatRequest(BaseModel):
    query: str
    thread_id: str

@app.get("/")
async def read_root():
    index_file = FRONTEND_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return {"status": "ok", "message": "Shubham Fashion Assistant API is running (frontend folder missing in container build context)"}

@app.get("/health")
def health_check():
    return {"status": "ok", "message": "Shubham Fashion Assistant API is running"}

@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
    config = {
        "configurable": {
            "thread_id": request.thread_id
        }
    }
    result = workflow.invoke(
        {
            "query": request.query
        },
        config=config
    )
    return {
        "response": result.get("response", "Sorry, something went wrong."),
        "displayed_products": result.get("displayed_products", []),
        "similar_products": result.get("similar_products", [])
    }