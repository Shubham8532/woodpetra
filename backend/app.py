from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
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

class ChatRequest(BaseModel):
    query: str
    thread_id: str

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
        config = config
    )
    return {
        "response": result.get("response", "Sorry, something went wrong."),
        "displayed_products": result.get("displayed_products", []),
        "similar_products": result.get("similar_products", [])
    }




# config = {
#     "configurable": {
#         "thread_id": "customer_1"
#     }
# }

# result = workflow.invoke(
#     {        
#         "query": "Whats the price"
#     },
#     config=config
# )

# print(result)

# while True:
#     user_input = input("\nUser: ")
#     if user_input.strip().lower() in ["exit", "quit"]:
#         break
        
#     result = workflow.invoke(
#         {"query": user_input},
#         config=config
#     )
    
#     print("Assistant:", result.get("response"))