import os
os.environ["LANGGRAPH_STRICT_MSGPACK"] = "false"
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from supabase import create_client


load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
# Faster model
PRIMARY_MODEL = os.getenv("MODEL_NAME", "llama-3.1-8b-instant")
# Stronger model (Fallback)
# FALLBACK_MODEL = os.getenv("FALLBACK_MODEL_NAME", "llama-3.3-70b-versatile")
FALLBACK_MODEL = os.getenv("FALLBACK_MODEL_NAME", "openai/gpt-oss-120b")

# Inititalize
llm_fast = ChatGroq(model_name=PRIMARY_MODEL, temperature=0)
llm_strong = ChatGroq(model_name=FALLBACK_MODEL, temperature=0)


supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_KEY")
)