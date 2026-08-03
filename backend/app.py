from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from backend.graph import workflow

app = FastAPI()

# Enable CORS so your HTML frontend can make requests to your API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files (CSS, JS, images, index.html) from the frontend directory
app.mount("/static", StaticFiles(directory="frontend"), name="static")

class ChatRequest(BaseModel):
    query: str
    thread_id: str

# Serve index.html on root route instead of raw JSON
@app.get("/")
async def read_root():
    return FileResponse("frontend/index.html")

# Health check route for Azure probes
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