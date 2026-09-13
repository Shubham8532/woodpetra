import os
os.environ["LANGGRAPH_STRICT_MSGPACK"] = "false"
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from supabase import create_client

####TEMPORARY: for local testing of lightning model######
# from langchain_openai import ChatOpenAI

# LIGHTNING_BASE_URL = "https://11434-01m287kwp46hzpa0pdz066jw7m.cloudspaces.litng.ai/v1"

# llm_lightning = ChatOpenAI(
#     base_url=LIGHTNING_BASE_URL,
#     api_key="anything",
#     model="llama3.1:8b",
#     temperature=0,
#     max_tokens=2048,
# )

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
# Faster model
# FAST_MODEL = os.getenv("MODEL_NAME", "llama-3.1-8b-instant")
# Primary model
PRIMARY_MODEL = os.getenv("PRIMARY_MODEL", "openai/gpt-oss-20b")
# Stronger model (Fallback)
# FALLBACK_MODEL_70B = os.getenv("FALLBACK_MODEL_NAME", "llama-3.3-70b-versatile")
FALLBACK_MODEL_120B = os.getenv("FALLBACK_MODEL_NAME", "openai/gpt-oss-120b")

# Inititalize
# llm_fast = ChatGroq(model_name=FAST_MODEL, temperature=0)
llm_20B = ChatGroq(
    model=PRIMARY_MODEL,
    temperature=0,
    max_tokens=2048
)
# llm_70B= ChatGroq(model_name=FALLBACK_MODEL_70B, temperature=0)
llm_120B = ChatGroq(model_name=FALLBACK_MODEL_120B, temperature=0)


supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_KEY")
)