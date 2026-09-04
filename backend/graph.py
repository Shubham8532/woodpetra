import os
from unittest import result
import razorpay
from typing import List, Optional
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver
from langchain_core.runnables import RunnableConfig
from langchain_core.output_parsers import PydanticOutputParser
from langsmith import traceable
from backend.config import llm_20B, llm_120B, supabase
from enum import Enum
# from langgraph.checkpoint.serde.types import ERROR_ON_UNHANDLED
import warnings
warnings.filterwarnings("ignore", message=".*Deserializing unregistered type.*")

from backend.models import(
    ShoppingState,
    RouterModel,
    RouteType,
    ContextRoute,
    ShoppingIntentModel,
    IntentType,
    TurnSlots
)
from backend.prompt import (
    ROUTER_PROMPT,
    GENERAL_CHAT_PROMPT,
    INTENT_PROMPT,
    RESPONSE_PROMPT
)

razorpay_client = razorpay.Client(
    auth=(os.environ.get("RAZORPAY_KEY_ID"), os.environ.get("RAZORPAY_KEY_SECRET"))
)

# def invoke_with_fallback(messages, schema=None):
#     """
#     Executes primary 70B model with instant failover to 120B on rate limit or error.
#     Supports both text generation and structured Pydantic schema extraction.
#     """
#     # Bind schema if passed, otherwise use raw LLM
#     model_70b = llm_70B.with_structured_output(schema) if schema else llm_70B
#     model_120b = llm_120B.with_structured_output(schema) if schema else llm_120B

#     try:
#         return model_70b.invoke(messages)
#     except Exception as e:
#         print(f"⚠️ Primary 70B error ({e}). Failing over to GPT-OSS 120B...")
#         return model_120b.invoke(messages)

# def invoke_with_fallback(messages, schema=None):
#     """
#     Executes primary 70B model with failover to 120B.
#     Falls back gracefully to string Pydantic parsing if function calling fails on backup model.
#     """
    # if not schema:
    #     try:
    #         return llm_70B.invoke(messages)
    #     except Exception as e:
    #         print(f"⚠️ Primary 70B error ({e}). Failing over to 120B...")
    #         return llm_120B.invoke(messages)

    # model_70b = llm_70B.with_structured_output(schema)

    # try:
    #     return model_70b.invoke(messages)
    # except Exception as e:
    #     print(f"⚠️ Primary 70B error ({e}). Failing over to 120B...")
        
    #     # Try native structured output on 120B
    #     try:
    #         model_120b = llm_120B.with_structured_output(schema)
    #         return model_120b.invoke(messages)
    #     except Exception as fallback_err:
    #         print(f"⚠️ 120B native tool-call failed ({fallback_err}). Retrying with Pydantic parser fallback...")
            
    #         parser = PydanticOutputParser(pydantic_object=schema)
    #         format_instructions = parser.get_format_instructions()
            
    #         augmented_messages = list(messages)
    #         augmented_messages.append((
    #             "human", 
    #             f"\n\nIMPORTANT: Return ONLY a raw valid JSON object matching this schema:\n{format_instructions}"
    #         ))
            
    #         raw_response = llm_120B.invoke(augmented_messages)
            
    #         # Clean markdown code blocks or literal '"null"' strings
    #         clean_text = (
    #             raw_response.content
    #             .replace("```json", "")
    #             .replace("```", "")
    #             .replace('"null"', "null")
    #             .strip()
    #         )
    #         return parser.parse(clean_text)
    
def invoke_with_fallback(messages, parser=None):
    """
    1. Primary: 20B Model (Fast & Cheap)
    2. Fallback: 120B Model (High Resilience Backup)
    """
    # ── TRY PRIMARY MODEL (20B) ──
    try:
        raw_res = llm_20B.invoke(messages)
        content = raw_res.content if hasattr(raw_res, 'content') else str(raw_res)

        if parser:
            clean = content.replace("```json", "").replace("```", "").strip()
            return parser.parse(clean)
        return content

    except Exception as e1:
        print(f"[Primary 20B Failed: {e1}] -> Falling back to 120B...")

    # ── TRY FALLBACK (120B) ──
    try:
        raw_res = llm_120B.invoke(messages)
        content = raw_res.content if hasattr(raw_res, 'content') else str(raw_res)

        if parser:
            clean = content.replace("```json", "").replace("```", "").strip()
            return parser.parse(clean)
        return content

    except Exception as e2:
        print(f"[ALL Fallback Models Failed]: {e2}")
        raise e2


# har naya question aane par pichle turn ke temporary search data ko clear karna
# taaki pichle turn ka out-of-stock ya irrelevant topic next turn mein bleed na kare
@traceable(name="Reset Turn Slots", description="Wipe per-turn ephemeral slots before each new user turn.")
def reset_turn_slots(state: ShoppingState) -> ShoppingState:
    """
    Clears per-turn search filters and product lists before processing 
    the current query to prevent stale data leakage.
    """
    return {
        "products": [],
        "similar_products": [],
        "displayed_products": [],
        "turn_slots": {
            "product_name": None,
            "category": None,
            "keyword": None,
            "color": None,
            "size": None,
            "price_min": None,
            "price_max": None,
        },
    }


# BEFORE: router used .with_structured_output() which triggers Groq HTTP 400
# ('attempted to call tool json which was not in request.tools') on llama-3.1-8b.
# The exception was silently swallowed and the route defaulted to 'general',
# causing affirmatives like 'ha'/'yes' to always hit general_chat.
#
# AFTER: router uses PydanticOutputParser + explicit JSON format instructions
# embedded in the system prompt. The LLM returns a raw JSON string that the
# parser validates — zero Groq tool-call machinery involved.
_router_parser = PydanticOutputParser(pydantic_object=RouterModel)



@traceable(name="Router", description="Route the user query to the appropriate workflow path.")
def router(state: ShoppingState):
    """
                    USER QUERY
                        │
                        ▼
              ┌──────────────────┐
              │      router      │
              │                  │
              │ query            │
              │       +          │
              │ last_bot_action  |
              | (What bot did on |
              |  previous turn)  |
              |  none --> if not │
              └────────┬─────────┘
                       │
                LLM + RouterModel
                       │
                 RouteType result
                       │
              ┌────────┴────────┐
              ▼                 ▼
          SHOPPING            GENERAL
    (RouteType.SHOPPING)    (RouteType.GENERAL)
              │                 │
              ▼                 ▼
      shopping workflow    general workflow
    """
    query = state["query"]
    last_bot_action = state.get("last_bot_action") or "none"
    context_hint = f"Previous assistant action: {last_bot_action}"

    format_instructions = _router_parser.get_format_instructions()
    system_with_schema = f"{ROUTER_PROMPT}\n\nOUTPUT FORMAT:\nReturn ONLY a raw JSON object (no markdown, no extra text).\n{format_instructions}"

    try:
        result = invoke_with_fallback(
            [
                ("system", system_with_schema),
                ("human", f"{context_hint}\nUser: {query}")
            ],
            parser=_router_parser  # LLM --> JSON --> RouterModel --> RouteType
        )
    except Exception as e:
        print(f"[Router Parse/LLM Error: {e}] -> Applying Smart Fallback")
        from backend.models import RouteType, RouterModel
        # Smart Fallback: Agar bot ne pehle alternatives offer kiye the, toh 'shopping' assume karo
        if last_bot_action in ("offered_alternatives", "denied_oos"):
            result = RouterModel(route=RouteType.SHOPPING)
        else:
            result = RouterModel(route=RouteType.GENERAL)

    print(f"[Router] last_bot_action={last_bot_action!r} | route={result.route!r}")

    ######################## Logging for debugging ##############

    def log_router_state(query, last_bot_action, result):
        route = result.route.value

        print("\n" + "=" * 80)
        print("ROUTER")
        print("=" * 80)

        print("\nINPUT")
        print("-" * 80)
        print(f"| {'Field':<20} | {'Value':<52} |")
        print(f"|{'-' * 22}|{'-' * 54}|")
        print(f"| {'query':<20} | {str(query):<52} |")
        print(f"| {'last_bot_action':<20} | {str(last_bot_action):<52} |")

        print("\nFLOW")
        print("-" * 80)

        print(
            f"""
            ┌──────────────────────────────────────────────┐
            │ USER QUERY                                   │
            │ {str(query):<44} │
            └──────────────────────┬───────────────────────┘
                                │
                                ▼
            ┌──────────────────────────────────────────────┐
            │ ROUTER                                       │
            │ query + last_bot_action                      │
            └──────────────────────┬───────────────────────┘
                                │
                            route = {route}
                                │
                                ▼
            ┌──────────────────────────────────────────────┐
            │ {route.upper() + " WORKFLOW":<44} │
            └──────────────────────────────────────────────┘
            """
        )

        print("=" * 80)


    log_router_state(
        query=query,
        last_bot_action=last_bot_action,
        result=result,
    )

    ###########################

    return {
        "route": result.route
    }

@traceable(name="Decide Route", description="Decide the next workflow path based on the router's output.")
def decide_route(state: ShoppingState):
    """
    Read the route selected by the router and return it to the graph
    so the workflow can continue through the corresponding branch.

    INPUT:
        - state["route"]

    OUTPUT:
        - "shopping" → shopping workflow
        - "general"  → general workflow
    """
    return state['route']


######################## Logging for debugging (load_history()) ########################

from datetime import datetime
def log_load_history_state(
    thread_id,
    snapshots_found,
    recent_snapshots,
    history
):
    log_file = "history_ongoing.txt"

    with open(log_file, "a", encoding="utf-8") as f:

        f.write("\n" + "=" * 80 + "\n")
        f.write("LOAD HISTORY\n")
        f.write("=" * 80 + "\n")

        f.write(f"\nTIME: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

        f.write("\nINPUT\n")
        f.write("-" * 80 + "\n")
        f.write(f"| {'Field':<25} | {'Value':<47} |\n")
        f.write(f"|{'-' * 27}|{'-' * 49}|\n")
        f.write(f"| {'thread_id':<25} | {str(thread_id):<47} |\n")
        f.write(f"| {'snapshots_found':<25} | {str(snapshots_found):<47} |\n")
        f.write(f"| {'snapshots_checked':<25} | {str(len(recent_snapshots)):<47} |\n")
        f.write(f"| {'history_returned':<25} | {str(len(history)):<47} |\n")

        f.write("\nHISTORY RETURNED\n")
        f.write("-" * 80 + "\n")

        if not history:
            f.write("No conversation history found.\n")

        else:
            for i, values in enumerate(history, 1):

                f.write(f"\nTURN {i}\n")
                f.write("-" * 80 + "\n")

                f.write("USER:\n")
                f.write(f"  {values.get('query', '')}\n")

                f.write("\nBOT:\n")
                f.write(f"  {values.get('response', '')}\n")

                f.write("\nOTHER STATE:\n")

                for key, value in values.items():
                    if key not in ("query", "response"):
                        f.write(f"  {key}: {value}\n")

        f.write("\n" + "=" * 80 + "\n")

########################################################################

@traceable(name="Load History", description="Load conversation history from the workflow's state history.")
def load_history(config: RunnableConfig):
    """
    workflow.get_state_history(...)
            ↓
    saare checkpoints/snapshots milte hain
            ↓
    sirf latest 12 snapshots
            ↓
    jinme query + response nahi → skip
            ↓
    duplicate (same query + response) → skip
            ↓
    history return
    """
    # print("here load_history")

    # print(config["configurable"])

    # Build a clean config
    clean_config = {
        "configurable": {
            "thread_id": config["configurable"]["thread_id"]
        }
    }

    # print("Original:", config["configurable"].keys())
    # print("Clean:", clean_config)

    snapshots = list(workflow.get_state_history(clean_config))
    # print("Snapshots found:", len(snapshots))

    # Slice only the most recent 12 snapshots (~3-4 turns) to avoid state duplication
    recent_snapshots = snapshots[:12]

    history = []
    seen = set()
    for snapshot in recent_snapshots:
        values = snapshot.values

        # query + response dono hone chahiye
        # Matlab incomplete state ignore.
        if not values.get("query") or not values.get("response"):
            continue

        # duplicate query/response hataata hai
        key = (values["query"], values["response"])

        if key in seen:
            continue

        seen.add(key)
        history.append(values)

##################### Logging Call ##################
    log_load_history_state(
        thread_id=config["configurable"]["thread_id"],
        snapshots_found=len(snapshots),
        recent_snapshots=recent_snapshots,
        history=history
    )

    ########################################################

    return history


##############  LOGGING (general_chat)  ##############
def log_general_chat_llm_context(
    query,
    history,
    history_text,
    prompt,
    system_prompt
):
    print("\n" + "=" * 80)
    print("GENERAL CHAT — LLM CONTEXT")
    print("=" * 80)

    print("\nCURRENT QUERY")
    print("-" * 80)
    print(query)

    print("\nHISTORY RECORDS")
    print("-" * 80)
    print(f"Records from load_history : {len(history)}")

    print("\nCOMPACT HISTORY")
    print("-" * 80)
    print(history_text if history_text else "No conversation history.")

    print("\nFINAL HUMAN PROMPT")
    print("-" * 80)
    print(prompt)

    print("\nSYSTEM PROMPT")
    print("-" * 80)
    print(system_prompt)

    print("\nPROMPT SIZE")
    print("-" * 80)
    print(f"History characters : {len(history_text)}")
    print(f"Human prompt chars : {len(prompt)}")
    print(f"System prompt chars: {len(system_prompt)}")

    print("=" * 80)

###########################

# later update
@traceable(name="General Chat", description="Handle general chat queries using conversation history.")
def general_chat(state: ShoppingState, config: RunnableConfig):

    history = load_history(config)
    # yaha par first return value history_text, second return value active_category
    history_text, active_category = build_conversation(history)

    prompt = f"""Use conversation history to directly answer the user query.

Rules:
1. Memory Retrieval: For follow-ups or queries about user info, past products, prices, colors, sizes, or options (e.g., "What is my name?", "Which product did I ask about?", "Sizes?"), extract details directly from Conversation History.
2. Direct & Concise: Answer in 1-2 clean, helpful sentences without meta-commentary.
3. No Apology/Critique: NEVER apologize, mention past assistant mistakes, or reference previous response errors.

Conversation History:
{history_text}

Current User Query:
{state["query"]}"""

    # print("=" * 80)
    # print(prompt)
    # print("=" * 80)
    
    # history = load_history(config)

    # print(history)

    # history_text = build_conversation(history)

    # print(history_text)

    # print(config)

    # print("history =", history)
    from pprint import pprint

    print("=" * 80)
    print("HISTORY")
    pprint(history)
    print("=" * 80)

    print ("above is in json format..and below is in structured format")
    ################## LOGGING CALL ##################
    log_general_chat_llm_context(
        query=state["query"],
        history=history,
        history_text=history_text,
        prompt=prompt,
        system_prompt=GENERAL_CHAT_PROMPT,
    )
###########################################
#     response = llm_fast.invoke(
#     [
#         (
#             "system",
#             GENERAL_CHAT_PROMPT,
#             ),
#         (
#             "human",
#             prompt
#         )
#     ]
# )

    # 20B Primary with Fallback (No parser passed -> returns clean response string)
    try:
        response_text = invoke_with_fallback([
            ("system", GENERAL_CHAT_PROMPT),
            ("human", prompt)
        ])
    except Exception as e:
        print(f"[general_chat Error]: {e}")
        response_text = "I'm here to help! What style or clothing item are you looking for today?"

    # BEFORE: general_chat always wrote last_bot_action='offered_alternatives',
    # even for pure greetings ("hi", "hello"). This poisoned the next turn:
    # a food query like "samosa hai kya" after a greeting would find
    # last_bot_action='offered_alternatives' and incorrectly hit fetch_featured.
    #
    # AFTER: only set 'offered_alternatives' when the query is a genuine denial
    # (non-apparel / food / out-of-catalog). Pure greetings preserve the
    # existing last_bot_action (or leave it as None) so they don't create a
    # false denial signal.
    # _PURE_GREETING_WORDS = frozenset({
    #     "hi", "hii", "hiii", "hello", "hey", "helo", "hlo", "hola",
    #     "good morning", "good afternoon", "good evening", "goodnight",
    #     "gud morning", "gud mrng", "greetings", "namaste", "namaskar",
    #     "thanks", "thank you", "shukriya", "bye", "goodbye",
    # })
    # query_lower = state.get("query", "").lower().strip()
    # is_pure_greeting = query_lower in _PURE_GREETING_WORDS

    # if is_pure_greeting:
    #     # Greeting: preserve whatever last_bot_action was (don't overwrite)
    #     next_last_bot_action = state.get("last_bot_action")
    # else:
    #     # Genuine denial / out-of-catalog / food query: signal for next-turn routing
    #     next_last_bot_action = "offered_alternatives"

    # print(f"[general_chat] is_pure_greeting={is_pure_greeting}  next_last_bot_action={next_last_bot_action!r}")

    # Pure AI-Intent Signal Tracking (No Manual Hardcoded Word Sets!)
    # Re-uses the intent already extracted by the parallel `extract_intent` node.
    intent_obj = state.get("intent")
    intent_type = getattr(intent_obj, "intent", intent_obj)
    intent_str = str(getattr(intent_type, "value", intent_type) or "").lower()

    if intent_str == "greeting":
        # Pure greeting (e.g., "hi", "yo", "namaste"): preserve existing signal
        next_last_bot_action = state.get("last_bot_action")

    else:
       # Out-of-catalog / non-apparel query (e.g., "samosa", "curtains"): 
        # Set signal so the next-turn affirmative ("ha"/"yes") triggers product cards
        next_last_bot_action = "offered_alternatives" 

    print(f"[general_chat] intent={intent_str!r}  next_last_bot_action={next_last_bot_action!r}")

    return {
        "response": response_text,
        "products": [],
        "displayed_products": [],
        "similar_products": [],
        "selected_product": state.get("selected_product"),  # Memory intact for Turn 4 checkout!
        "last_bot_action": next_last_bot_action,
    }


############# LOGGING (build_conversation) ########################
def log_build_conversation_state(
    history,
    max_turns,
    history_text,
    active_category
):
    print("\n" + "=" * 80)
    print("BUILD CONVERSATION")
    print("=" * 80)

    print("\nINPUT")
    print("-" * 80)
    print(f"History records received : {len(history)}")
    print(f"Max turns                : {max_turns}")

    print("\nPROCESSING")
    print("-" * 80)
    print("• Reads history newest → oldest")
    print("• Finds latest non-null category")
    print("• Removes repeated queries")
    print("• Cleans UI text from responses")
    print("• Truncates responses to 120 characters")
    print(f"• Keeps maximum {max_turns} turns")
    print("• Reverses final order to oldest → newest")

    print("\nOUTPUT")
    print("-" * 80)
    print(f"Active category: {active_category}")

    print("\nHISTORY TEXT GIVEN TO LLM")
    print("-" * 80)

    if history_text:
        print(history_text)
    else:
        print("No conversation history.")

    print("=" * 80)

########################################

@traceable(name="Build Conversation", description="Convert LangGraph checkpoints into a clean conversation history.")
def build_conversation(history, max_turns=3):
    """
    Converts recent LangGraph checkpoints into a clean conversation history
    and extracts the active category from previous turns.
    """

    conversation = []
    seen_queries = set()
    active_category = None

    # Iterate through history to find queries and the last active category
    for item in history:   # Newest -> Oldest
        query = item['query']

        # Capture the most recent non-null category from past state checkpointers
        past_intent = item.get('intent')
        if not active_category and past_intent and getattr(past_intent, 'category', None):
            active_category = past_intent.category

        if not query or query in seen_queries:
            continue
        seen_queries.add(query)

        raw_response = item.get('response', '')
        
        # Clean out UI kachra text before sending to history prompt
        clean_response = (
            raw_response.split("Matching Items")[0]
            .split("Tap below")[0]
            .replace("\n", " ")
            .strip()
        )
        
        # Truncate response to 120 chars to keep context light & crisp
        short_response = (clean_response[:120] + "...") if len(clean_response) > 120 else clean_response

        conversation.append(
            f"User: {query}\n"
            f"Assistant: {short_response}"
        )

    # Limit strictly to the last `max_turns`
    conversation = conversation[:max_turns]
    conversation.reverse()  # Reverse to get Oldest -> Newest

    history_text = "\n\n".join(conversation)

    ############# LOGGING CALL ##############
    log_build_conversation_state(
        history=history,
        max_turns=max_turns,
        history_text=history_text,
        active_category=active_category
    )
    ##################
    return history_text, active_category


# ========================================== 
# For 7B model compatibility
# Output parser instance for standard text parsing fallback
intent_parser = PydanticOutputParser(pydantic_object=ShoppingIntentModel)


#==========================================
@traceable(name="Extract Intent", description="Extract shopping intent from the user's query using the ShoppingIntentModel.")
def extract_intent(
        state: ShoppingState,
        config: RunnableConfig
    ) -> ShoppingState:
    """
    Extract shopping intent from the user's query using the ShoppingIntentModel.
    """

    history = load_history(config)
    # Increased max_turns to 8 so product context survives 3-4 intervening queries
    history_text, active_category = build_conversation(history, max_turns=8)

    query = state['query']

    # Can comment out for 70 model
    # structured_output = llm.with_structured_output(ShoppingIntentModel)

    system_prompt = INTENT_PROMPT + f"""
Active Category: {active_category if active_category else "None"}
History (Last 8 turns):
{history_text}

MAPPING & INFERENCE:
- Typos/Slang: "hoofie/sweatshirt" -> Hoodie | "shrt/formal shirt" -> Shirt | "tshirt/tee" -> T-Shirt | "pant/trouser/slacks" -> Trouser | "jean/denim" -> Jeans.
- Relatives (Hindi/Hinglish/English):
  * Older male (father/papa/uncle/chacha): Set category="Shirt"/"Trouser", gender="Men".
  * Younger male (brother/bhai/friend): Set category="T-Shirt"/"Hoodie"/"Joggers", gender="Men".
  * Female (mother/mummy/sister/behan/wife): For traditional/women wear (saree/kurti/dress), set category=None. For general gifts, set gender="Women", category=None (or infer unisex Hoodie/Cap).
- Occasion/Vibe: Map style terms ("office", "gym", "party") to logical categories ("Shirt"/"Trouser" for formal, "T-Shirt"/"Hoodie" for casual) and store term in `keyword`. Prioritize category inference over null.

CONTEXT & ATTRIBUTES:
1. Attribute queries ("Sizes?", "Colors?", "Price?", "Options?") MUST be intent='search'.
2. CATEGORY PERSISTENCE: Maintain previous category ({active_category}) if no new catalog category is explicitly mentioned in current query.
3. Greetings ("Hi", "Hello") with active category ({active_category}) MUST set intent='search' and category='{active_category}'.
4. General queries ("which colors available", "show more") MUST NOT set `product_name`.
5. Reset `price_max` to null unless budget is explicitly requested in current message.
6. Requests for "other products", "different categories", or "what else do u have" MUST set category=None.
7. Infer `product_name` from history when query refers to "it", "this", "that", "the product", or buying expressions ("buy it", "khareedna hai").
8. SINGLE-TURN FILTERS: `color`, `size`, `price_min`, `price_max`, and `keyword` are strictly single-turn filters. NEVER carry them over from previous turns unless explicitly stated in current message.
9. ATTRIBUTE INQUIRIES: When the query asks about available colors, sizes, or options for active category ({active_category}), set `color=None`, `size=None`, `price_min=None`, and `price_max=None` while maintaining `category='{active_category}'`.
"""
    # print("=" * 80)
    # print("SYSTEM PROMPT")
    # print(system_prompt)
    # print("=" * 80)

    # print("USER QUERY")
    # print(query)
    # print("=" * 80)

    # ### for trying 7B model(faster response)
    # # Step 1: FAST 8B MODEL (with PydanticOutputParser + String Null Cleaning)
    # try:
    #     format_instructions = intent_parser.get_format_instructions()
    #     parser_system_prompt = f"{system_prompt}\n\n{format_instructions}"

    #     raw_response = llm_fast.invoke(
    #         [
    #             ("system", parser_system_prompt),
    #             ("human", query)
    #         ]
    #     )
    #     # Sanitize literal string '"null"' artifacts emitted by 8B model into proper JSON null
    #     clean_content = raw_response.content.replace('"null"', "null")
    #     result = intent_parser.parse(clean_content)
    #     return {"intent": result}

    # except Exception as e:
    #     print(f"[8B Model Failed -> Cascading to 70B Model]: {e}")



    # STEP 2: STRONG 70B MODEL (Fallback with Native Structured Output)
    # structured_output = llm_strong.with_structured_output(ShoppingIntentModel)

    # result = structured_output.invoke(
    #     [
    #         ("system", system_prompt),
    #         ("human", query)
    #     ]
    # )
    format_instructions = intent_parser.get_format_instructions()
    system_with_schema = (
        system_prompt + f"\n\nOUTPUT FORMAT:\nReturn ONLY a raw JSON object matching the schema below (no markdown, no backticks).\n{format_instructions}"
    )

    
    try:
        result = invoke_with_fallback(
            [
                ("system", system_with_schema),
                ("human", query)
            ],
            parser=intent_parser
        )
    except Exception as e:
        print(f"[extract_intent Error] All fallback models failed ({e}) -> Using default neutral intent.")
        result = ShoppingIntentModel(intent=IntentType.GENERAL)

    # # Smart Fallback: Iff no category or produvt_name was matched, assign raw query to keyword
    # if not result.category and not result.product_name and result.intent in ["search", "recommend"]:
    #     clean_kw = query.lower().replace("show me", "").replace("do you have", "").strip()
    #     result.keyword = clean_kw

    # Reset stale single-turn filters on attribute inquiry queries
    # raw_query = query.lower()
    # if any(w in raw_query for w in ["color", "colour", "size", "rang", "available", "options"]):
    #     result.color = None
    #     result.size = None
    #     result.price_max = None
    #     result.price_min = None

    # Directly map clean intent to ephemeral turn_slots (Zero Manual Pronoun Filtering)
    turn_slots_dict = {
        "product_name": result.product_name,
        "category": result.category,
        "keyword": result.keyword,
        "color": result.color,
        "size": result.size.value if result.size else None,
        "price_min": result.price_min,
        "price_max": result.price_max,
    }


        ######################## Logging for debugging ##############

    def log_intent_state(
        query,
        active_category,
        result,
        turn_slots_dict,
        previous_turn_slots
    ):
        print("\n" + "=" * 80)
        print("EXTRACT INTENT")
        print("=" * 80)

        # ======================== INPUT ========================

        print("\nINPUT")
        print("-" * 80)
        print(f"| {'Field':<20} | {'Value':<52} |")
        print(f"|{'-' * 22}|{'-' * 54}|")

        print(f"| {'query':<20} | {str(query):<52} |")
        print(f"| {'active_category':<20} | {str(active_category):<52} |")

        # ======================== OUTPUT ========================

        print("\nSHOPPING INTENT")
        print("-" * 80)

        fields = [
            "intent",
            "keyword",
            "category",
            "product_name",
            "color",
            "material",
            "size",
            "fit",
            "brands",
            "gender",
            "price_min",
            "price_max",
            "sort",
            "occasion",
        ]

        turn_slot_fields = {
            "product_name",
            "category",
            "keyword",
            "color",
            "size",
            "price_min",
            "price_max",
        }

        # First extraction:
        # Only show what ShoppingIntentModel produced.
        if previous_turn_slots is None:

            print(
                f"| {'Field':<20} | "
                f"{'ShoppingIntentModel':<52} |"
            )
            print(
                f"|{'-' * 22}|"
                f"{'-' * 54}|"
            )

            for field in fields:

                value = getattr(result, field)

                if isinstance(value, Enum):
                    value = value.value

                print(
                    f"| {field:<20} | "
                    f"{str(value):<52} |"
                )

        # Later extraction:
        # Show model output + what state had before + new turn_slots.
        else:

            print(
                f"| {'Field':<20} | "
                f"{'ShoppingIntentModel':<25} | "
                f"{'Previous':<20} | "
                f"{'Current turn_slots':<20} |"
            )

            print(
                f"|{'-' * 22}|"
                f"{'-' * 27}|"
                f"{'-' * 22}|"
                f"{'-' * 22}|"
            )

            for field in fields:

                model_value = getattr(result, field)

                if isinstance(model_value, Enum):
                    model_value = model_value.value

                if field in turn_slot_fields:
                    previous_value = previous_turn_slots.get(field)
                    current_value = turn_slots_dict.get(field)
                else:
                    previous_value = "—"
                    current_value = "—"

                print(
                    f"| {field:<20} | "
                    f"{str(model_value):<25} | "
                    f"{str(previous_value):<20} | "
                    f"{str(current_value):<20} |"
                )

        # ======================== STATE OUT ========================

        print("\nSTATE OUT")
        print("-" * 80)
        print("| intent      → ShoppingIntentModel")
        print("| turn_slots  → turn_slots_dict")
        print("=" * 80)


    # Logger only READS the existing state.
    log_intent_state(
        query=query,
        active_category=active_category,
        result=result,
        turn_slots_dict=turn_slots_dict,
        previous_turn_slots=state.get("turn_slots"),
    )
    ###########################

    return {
        "intent": result,
        "turn_slots": turn_slots_dict,
    }

######### Debugging: Context Decision Logging ########

def log_context_decision_state(intent, context_route):

    route = context_route.value

    if route == "search":
        next_branch = "EXTRACT INTENT"
    else:
        next_branch = "CONTEXT BRANCH"

    print("\n" + "=" * 80)
    print("CONTEXT DECISION")
    print("=" * 80)

    print("\nINPUT")
    print("-" * 80)
    print(f"| {'Field':<20} | {'Value':<52} |")
    print(f"|{'-' * 22}|{'-' * 54}|")
    print(f"| {'intent':<20} | {str(intent):<52} |")

    print("\nFLOW")
    print("-" * 80)

    print(
        f"""
        ┌──────────────────────────────────────────────┐
        │ SHOPPING WORKFLOW                            │
        └──────────────────────┬───────────────────────┘
                               │
                               ▼
        ┌──────────────────────────────────────────────┐
        │ CONTEXT DECISION                             │
        │                                              │
        │ intent = {str(intent):<32} │
        └──────────────────────┬───────────────────────┘
                               │
                               ▼
        ┌──────────────────────────────────────────────┐
        │ CONTEXT ROUTE                                │
        │                                              │
        │ route = {route:<35} │
        ⚠️ CURRENT ARCHITECTURE — context_route may be invalid
        └──────────────────────┬───────────────────────┘
                               │
                               ▼
        ┌──────────────────────────────────────────────┐
        │ NEXT STEP                                    │
        │                                              │
        │ {next_branch:<44} │
        └──────────────────────────────────────────────┘
        """
    )

    print("\nOUTPUT")
    print("-" * 80)
    print(f"| {'Field':<20} | {'Value':<52} |")
    print(f"|{'-' * 22}|{'-' * 54}|")
    print(f"| {'context_route':<20} | {route:<52} |")

    print("=" * 80)

##############################


@traceable(name="Context Decision", description="Decide whether to search the database or answer using conversation context.")
def context_decision(state: ShoppingState):
    """
    DEcide whether o seacrh the database or answer using conversation context

                        SHOPPING WORKFLOW
                               │
                               ▼
                    ┌──────────────────────┐
                    │   CONTEXT DECISION   │
                    │                      │
                    │   state["intent"]    │
                    └──────────┬───────────┘
                               │
                         Check intent
                               │
                 ┌─────────────┴─────────────┐
                 │                           │
                 ▼                           ▼
          SEARCH-type intent          Other intent
      SEARCH / DETAILS /            GENERAL / other
      COMPARE / RECOMMEND                 │
                 │                        │
                 ▼                        ▼
       context_route=SEARCH      context_route=CONTEXT
                 │                        │
                 ▼                        ▼
          Search database          Use conversation
                                     context
    """
    # print(state)
    raw_intent = state.get("intent")
    
    if raw_intent is not None:
        intent = getattr(raw_intent, "intent", raw_intent)
        if intent in (
            IntentType.SEARCH,
            IntentType.DETAILS,
            IntentType.COMPARE,
            IntentType.RECOMMEND
        ):
            ######################### Logging for debugging ##############
            context_route = ContextRoute.SEARCH
            log_context_decision_state(
                intent=intent,
                context_route=context_route
            )
            return {
                "context_route": context_route
            }
            
            # Temporarily disabled for logging otherwise use this
            # return {
            #     "context_route": ContextRoute.SEARCH
            # }

    context_route = ContextRoute.CONTEXT

    # Debugging only
    log_context_decision_state(
        intent=raw_intent,
        context_route=context_route
    )

    return {
        "context_route": context_route
    }

    # Temporarily disabled for logging otherwise use this
    # return {
    #     "context_route": ContextRoute.CONTEXT
    # }


    # # imporve later
    # if (
    #     intent.category is None
    #     and intent.product_name is None
    #     and intent.color is None
    #     and intent.material is None
    #     and intent.size is None
    # ):
    #     return {
    #         "context_route": ContextRoute.CONTEXT
    #     }
    # return {
    #     "context_route": ContextRoute.SEARCH
    # }


@traceable(name="Decide Context", description="Decide the next workflow path based on the context decision's output.")
def decide_context(state: ShoppingState):
    """
    context_decision
       │
       │ produces
       ▼
    context_route
       │
       ▼
    decide_context
       │
       ├──────── SEARCH ───────→ Search branch
       │
       └──────── CONTEXT ──────→ Context branch

    Read the context route selected by context_decision
    and return it to the graph for branching.

    INPUT:
        - state["context_route"]

    OUTPUT:
        - "search"  → search workflow
        - "context" → conversation context workflow
    """

    return state['context_route']

########################## LOGGING (search_product) ##########################

import time
from datetime import datetime
from pathlib import Path


RETRIEVED_PRODUCTS_LOG = Path("retrieved_products.txt")


def log_search(message="", *, handle=None):
    """
    Write one log message to retrieved_products.txt.

    Logging must NEVER affect search_product().
    Any logging-related error is silently ignored.
    """

    try:

        if handle is not None:
            handle.write(message + "\n")
            handle.flush()
            return

        with RETRIEVED_PRODUCTS_LOG.open("a", encoding="utf-8") as f:
            f.write(message + "\n")

    except Exception:
        pass


def _log_timestamp():
    try:
        return datetime.now().strftime("%H:%M:%S.%f")[:-3]
    except Exception:
        return "UNKNOWN-TIME"


def _log_elapsed(start_time):
    try:
        return f"{(time.perf_counter() - start_time) * 1000:.1f} ms"
    except Exception:
        return "UNKNOWN"


def log_search_step(
    handle,
    step,
    description,
    start_time,
    result_count=None
):
    """
    Log one investigation step.

    Logging failures are ignored so the actual search logic
    can never be affected.
    """

    try:

        elapsed = _log_elapsed(start_time)

        if result_count is None:

            log_search(
                f"[{_log_timestamp()}] {step} | "
                f"{description} | "
                f"elapsed={elapsed}",
                handle=handle
            )

        else:

            log_search(
                f"[{_log_timestamp()}] {step} | "
                f"{description} | "
                f"results={result_count} | "
                f"elapsed={elapsed}",
                handle=handle
            )

    except Exception:
        pass


def log_product_table(
    products,
    handle,
    title,
    limit=None
):
    """
    Write retrieved products in a compact table.

    Does NOT dump the complete product JSON.
    """

    try:

        log_search("", handle=handle)
        log_search(title, handle=handle)
        log_search("-" * 100, handle=handle)

        if not products:

            log_search(
                "Count: 0",
                handle=handle
            )

            return

        log_search(
            f"Count: {len(products)}",
            handle=handle
        )

        rows = products if limit is None else products[:limit]

        log_search(
            f"{'SKU':<14}"
            f"{'NAME':<30}"
            f"{'CATEGORY':<16}"
            f"{'COLOR':<14}"
            f"{'SIZE':<8}"
            f"{'PRICE':>10}",
            handle=handle
        )

        log_search("-" * 92, handle=handle)

        for product in rows:

            sku = str(
                product.get("sku", "")
            )[:13]

            name = str(
                product.get("name", "")
            )[:29]

            category = str(
                product.get("category", "")
            )[:15]

            color = str(
                product.get("color", "")
            )[:13]

            size = str(
                product.get("size", "")
            )[:7]

            price = str(
                product.get("price", "")
            )

            log_search(
                f"{sku:<14}"
                f"{name:<30}"
                f"{category:<16}"
                f"{color:<14}"
                f"{size:<8}"
                f"{price:>10}",
                handle=handle
            )

        if limit is not None and len(products) > limit:

            log_search(
                f"... {len(products) - limit} more products "
                f"not displayed",
                handle=handle
            )

    except Exception:
        pass


def log_search_query(
    handle,
    step,
    query_description,
    products,
    start_time
):
    """
    Convenience logger for a database query.
    """

    try:

        log_search_step(
            handle,
            step,
            query_description,
            start_time,
            len(products)
        )

        log_product_table(
            products,
            handle,
            f"{step} RESULTS",
            limit=20
        )

    except Exception:
        pass

#######################################################

@traceable(name="Search Product", description="Query Supabase using the extracted shopping intent with a 2-Tier strategy and smart fallbacks.")
def search_product(state: ShoppingState) -> ShoppingState:
    """
    Query Supabase using the extracted shopping intent.
    Uses a 2-Tier strategy (Specific Product Name Search vs. General Category/Keyword Filtering)
    with smart fallbacks, plus a recommendation query for similar products.
    """

    ############### LOGGING CALL ##############
    search_start = time.perf_counter()

    # Open ONE log block for this search invocation.
    # Everything related to this search goes inside it.
    try:
        search_log_handle = RETRIEVED_PRODUCTS_LOG.open(
            "a",
            encoding="utf-8"
        )

    except Exception:
        search_log_handle = None

    log_search("", handle=search_log_handle)

    log_search(
        "=" * 100,
        handle=search_log_handle
    )

    log_search(
        f"SEARCH PRODUCT | "
        f"started={datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}",
        handle=search_log_handle
    )

    log_search(
        "=" * 100,
        handle=search_log_handle
    )

    ################################


    # Extract the structured intent object from LangGraph state
    intent = state['intent']
    raw_query = state.get('query', '').lower()

#################### AGAIN LOGGING CALL --> ####################
    log_search(
        "RAW USER QUERY",
        handle=search_log_handle
    )

    log_search(
        f"Query: {raw_query}",
        handle=search_log_handle
    )

    log_search(
        "",
        handle=search_log_handle
    )

    log_search(
        "SEARCH FILTERS",
        handle=search_log_handle
    )

    log_search(
        "-" * 80,
        handle=search_log_handle
    )

    log_search(
        f"Product Name   : {intent.product_name}",
        handle=search_log_handle
    )

    log_search(
        f"Category       : {intent.category}",
        handle=search_log_handle
    )

    log_search(
        f"Keyword        : {intent.keyword}",
        handle=search_log_handle
    )

    log_search(
        f"Color          : {intent.color}",
        handle=search_log_handle
    )

    log_search(
        f"Size           : {intent.size}",
        handle=search_log_handle
    )

    log_search(
        f"Price Min      : {intent.price_min}",
        handle=search_log_handle
    )

    log_search(
        f"Price Max      : {intent.price_max}",
        handle=search_log_handle
    )

    log_search(
        f"Sort           : {getattr(intent, 'sort', None)}",
        handle=search_log_handle
    )

    log_search(
        f"Intent Type    : {getattr(intent, 'intent', None)}",
        handle=search_log_handle
    )

    log_search(
        "-" * 80,
        handle=search_log_handle
    )

    ###################################################################

    # # STEP 0: KEYWORD TO CATEGORY NORMALIZATION
    # # Converts plural/synonym keywords ("tshirts", "tees", "pants") to exact DB categories if category is missing
    # if not intent.category and intent.keyword:
    #     kw_clean = intent.keyword.lower().replace("tshirts", "t-shirt").replace("tshirt", "t-shirt").rstrip('s')
    #     cat_map = {
    #         "t-shirt": "T-Shirt", "tee": "T-Shirt",
    #         "shirt": "Shirt",
    #         "hoodie": "Hoodie", "sweatshirt": "Hoodie",
    #         "jean": "Jeans", "denim": "Jeans",
    #         "jogger": "Joggers", "pant": "Joggers", "trouser": "Joggers",
    #         "short": "Shorts",
    #         "jacket": "Jacket",
    #         "shoe": "Shoes", "sneaker": "Shoes",
    #         "cap": "Cap", "hat": "Cap"
    #     }
    #     for k, v in cat_map.items():
    #         if k in kw_clean:
    #             intent.category = v
    #             break

    # # STEP 1: SAFETY CHECK
    # # Check if ANY usable search filter was extracted from the user's query.
    has_filter = any([
        intent.product_name,
        intent.category,
        intent.keyword,
        intent.color,
        intent.size,
        intent.price_min is not None,
        intent.price_max is not None,
        getattr(intent, 'brands', None) or getattr(intent, 'brand', None)
    ]) or getattr(intent, 'intent', None) in ["search", "browse", "recommend", "general"]


    ###################### AGAIN LOGGING CALL --> log safety check ##############
    log_search_step(
        search_log_handle,
        "SAFETY CHECK",
        f"Usable search filter detected: {has_filter}",
        search_start
    )
    log_search(
        f"Investigation: product_name={bool(intent.product_name)}",
        handle=search_log_handle
    )

    log_search(
        f"Investigation: category={bool(intent.category)}",
        handle=search_log_handle
    )

    log_search(
        f"Investigation: keyword={bool(intent.keyword)}",
        handle=search_log_handle
    )

    log_search(
        f"Investigation: color={bool(intent.color)}",
        handle=search_log_handle
    )

    log_search(
        f"Investigation: size={bool(intent.size)}",
        handle=search_log_handle
    )

    log_search(
        f"Investigation: price_min={intent.price_min is not None}",
        handle=search_log_handle
    )

    log_search(
        f"Investigation: price_max={intent.price_max is not None}",
        handle=search_log_handle
    )
    #######################################
    
    # If NO filter was extracted, stop immediately to prevent pulling all rows from DB
    if not has_filter:

        #################### AGAIN LOGGING CALL ################
        log_search_step(
            search_log_handle,
            "SAFETY CHECK",
            "No usable filters detected",
            search_start,
            0
        )
        #########################################

        print("Extracted Intent:", intent)
        print("Product Name:", intent.product_name)
        print("Category:", intent.category)
        print("Color:", intent.color)
        print("Size:", intent.size)
        print("Price Max:", intent.price_max)
        print("Products Found in DB: 0 (No Filters Extracted)")
        return {"products": [] , "similar_products": []}
    
    products = []

    ######################### AGAIN LOGGING CALL ###############
    log_search(
        "Investigation: safety check passed → database search is allowed.",
        handle=search_log_handle
    )
    ##############################

    # TIER 1: THE USER ASKED FOR A SPECIFIC PRODUCT BY NAME
    # Example: "Do you have CloudWarm Hoodie in Navy size XL?"
    if intent.product_name:

        ################ LOGGING CALL #################
        log_search_step(
            search_log_handle,
            "TIER 1",
            f"Specific product search selected | product_name='{intent.product_name}'",
            search_start
        )

        log_search(
            "Investigation: product_name exists → entering strict product-name search.",
            handle=search_log_handle
        )
        #############################################
        strict_query = (
            supabase.table("products")
            .select("*")
            .ilike("name", f"%{intent.product_name}%")
        )

        #################### LOGGING CALL ###############
        log_search(
            "Investigation: base query created.",
            handle=search_log_handle
        )

        log_search(
            f"Investigation: table=products",
            handle=search_log_handle
        )

        log_search(
            f"Investigation: SELECT=*",
            handle=search_log_handle
        )

        log_search(
            f"Investigation: name ILIKE '%{intent.product_name}%'",
            handle=search_log_handle
        )

        log_search_step(
            search_log_handle,
            "TIER 1 → BUILD STRICT QUERY",
            (
                f"name contains '{intent.product_name}'"
                f" | color={intent.color}"
                f" | size={intent.size}"
            ),
            search_start
        )
        #######################################

        if intent.color:
            ################### LOGGING CALL ###############
            log_search(
                f"Investigation: COLOR filter detected → applying color='{intent.color}'",
                handle=search_log_handle
            )
            #############################################
            strict_query = strict_query.ilike("color", intent.color.capitalize())  
            ################# AGAIN LOGGING CALL ############
            log_search(
                f"Investigation: query now contains color ILIKE '{intent.color.capitalize()}'",
                handle=search_log_handle
            )
            ########################################

        if intent.size:
            size_val = (
                intent.size.value
                if hasattr(intent.size, "value")
                else intent.size
            )
            ############# LOGGING CALL #################
            log_search(
                f"Investigation: SIZE filter detected → resolved size='{size_val}'",
                handle=search_log_handle
            )
            ##########################################
            strict_query = strict_query.eq("size", size_val)
        ###################### AGAIN LOGGING CALL ###########
            log_search(
                f"Investigation: query now contains size='{size_val}'",
                handle=search_log_handle
            )


        log_search(
            "Investigation: executing TIER 1 strict database query NOW.",
            handle=search_log_handle
        )
        ##############################################
        products = strict_query.execute().data
        #################### AGAIN LOGGING CALL ############
        log_search(
            "Investigation: TIER 1 strict database query completed.",
            handle=search_log_handle
        )

        log_search_query(
            search_log_handle,
            "TIER 1 → STRICT QUERY",
            (
                f"Product name='{intent.product_name}'"
                f" | color={intent.color}"
                f" | size={intent.size}"
            ),
            products,
            search_start
        )
        #############################################

        # --- FALLBACK 1: PRODUCT EXISTS, BUT NOT IN THAT COLOR OR SIZE ---
        
        if not products:
            ###################### LOGGING CALL ##################
            log_search_step(
                search_log_handle,
                "TIER 1 → FALLBACK 1",
                "Strict product search returned 0 results → removing color/size restrictions",
                search_start,
                0
            )
            log_search(
                "Investigation: product-name search produced ZERO results.",
                handle=search_log_handle
            )

            log_search(
                "Investigation: removing color and size restrictions.",
                handle=search_log_handle
            )
            ##################################################
            products = (
                supabase
                .table("products")
                .select("*")
                .ilike("name", f"%{intent.product_name}%")
                .execute()
                .data
            )

            ################## LOG CALL ####################
            ################ FALLBACK 1 RESULT ################

            log_search_query(
                search_log_handle,
                "TIER 1 → FALLBACK 1",
                (
                    f"Searching product name='{intent.product_name}'"
                    " without requested color/size"
                ),
                products,
                search_start
            )
            ##################################
            
        # --- FALLBACK 2: SEARCH OTHER PRODUCTS IN THE SAME CATEGORY OR KEYWORD ---
        if not products and (intent.category or intent.keyword):
            ################### AGAIN LOGGING CALL ################
            log_search_step(
                search_log_handle,
                "TIER 1 → FALLBACK 2",
                (
                    "Product-name fallback still returned 0"
                    f" | category={intent.category}"
                    f" | keyword={intent.keyword}"
                    " → searching alternatives"
                ),
                search_start,
                0
            )
            ###################################
            alt_query = supabase.table("products").select("*")

            ################## AGAIN LOGGING CALL ############
            log_search(
                "Investigation: alternative query created.",
                handle=search_log_handle
            )
            ############################################

            if intent.category:
                ################ LOGGING CALL ############
                log_search(
                    f"Investigation: FALLBACK 2 using CATEGORY = {intent.category}",
                    handle=search_log_handle
                )
                ########################################
                alt_query = alt_query.eq("category", intent.category)

            elif intent.keyword:
                kw_term = intent.keyword.strip()
                #################### LOGGING CALL ################
                log_search(
                    f"Investigation: FALLBACK 2 using KEYWORD = {kw_term}",
                    handle=search_log_handle
                )
                ##################################################
                alt_query = alt_query.or_(f"name.ilike.%{kw_term}%,description.ilike.%{kw_term}%,category.ilike.%{kw_term}%")

            if intent.color:
                ##################### LOGGING CALL #############
                log_search(
                    f"Investigation: FALLBACK 2 applying COLOR = {intent.color}",
                    handle=search_log_handle
                )
                ################################
                alt_query = alt_query.ilike("color", intent.color.capitalize())

            if intent.size:
                size_val = intent.size.value if hasattr(intent.size, "value") else intent.size
                #################### LOGGING CALL ################
                log_search(
                    f"Investigation: FALLBACK 2 applying SIZE = {size_val}",
                    handle=search_log_handle
                )
                ##########################################
                alt_query = alt_query.eq("size", size_val)
            #################### AGAIN LOGGING CALL ##########
            log_search(
                "Investigation: executing TIER 1 FALLBACK 2 database query NOW.",
                handle=search_log_handle
            )
            #######################################
            products = alt_query.execute().data

            ######################### AGAIN LOGGING CALL ###########
            log_search(
                "Investigation: TIER 1 FALLBACK 2 database query completed.",
                handle=search_log_handle
            )
            ######################################

            #################### LOGGING CALL ###############
            ################ FALLBACK 2 RESULT ################

            log_search_query(
                search_log_handle,
                "TIER 1 → FALLBACK 2",
                (
                    f"Alternative search"
                    f" | category={intent.category}"
                    f" | keyword={intent.keyword}"
                    f" | color={intent.color}"
                    f" | size={intent.size}"
                ),
                products,
                search_start
            )
            #####################################################

    # TIER 2: GENERAL CATEGORY & ATTRIBUTE FILTERING
    # Used when user asks for general items like: "Show me black hoodies under 1500"
    else:
        ############## LOGGING CALL ####################
        log_search_step(
            search_log_handle,
            "TIER 2",
            "No specific product_name → entering general category/attribute search",
            search_start
        )
        #################################################
        query = supabase.table("products").select("*")
        clean_kw = intent.keyword.strip() if intent.keyword else ""

        ############### AGAIN LOGGING CALL ###########
        log_search(
            f"Investigation: clean keyword = '{clean_kw}'",
            handle=search_log_handle
        )
        #########################################

        if intent.category:
            ######################## LOGGING CALL ###########
            log_search(
                f"Investigation: applying CATEGORY filter = {intent.category}",
                handle=search_log_handle
            )
            ##################################################
            query = query.eq("category", intent.category)

        elif intent.keyword:
            ####################### AGAIN LOGGING CALL ##########
            log_search(
                f"Investigation: applying KEYWORD filter = {clean_kw}",
                handle=search_log_handle
            )
            ##########################################
            
            query = query.or_(f"name.ilike.%{clean_kw}%,description.ilike.%{clean_kw}%,category.ilike.%{clean_kw}%")

        if intent.color:
            ##################### LOGGING CALL ################
            log_search(
                f"Investigation: applying COLOR filter = {intent.color}",
                handle=search_log_handle
            )
            ###############################
            query = query.ilike("color", intent.color.capitalize())

        if intent.size:
            size_val = intent.size.value if hasattr(intent.size, "value") else intent.size
            ################ LOGGING CALL ##################
            log_search(
                f"Investigation: applying SIZE filter = {size_val}",
                handle=search_log_handle
            )
            ############################################
            query = query.eq("size", size_val)

        if intent.price_min is not None:
            ################ LOGGING CALL ##################
            log_search(
                f"Investigation: applying PRICE MIN = {intent.price_min}",
                handle=search_log_handle
            )
            ###########################################
            query = query.gte("price", intent.price_min)

        if intent.price_max is not None:
            ################ LOGGING CALL ##################
            log_search(
                f"Investigation: applying PRICE MAX = {intent.price_max}",
                handle=search_log_handle
            )
            ###########################################
            query = query.lte("price", intent.price_max)

        query = query.order("price", desc=False)

        ################ LOGGING CALL ##################
        log_search_step(
            search_log_handle,
            "TIER 2 → PRIMARY QUERY",
            (
                f"category={intent.category}"
                f" | keyword={clean_kw}"
                f" | color={intent.color}"
                f" | size={intent.size}"
                f" | price_min={intent.price_min}"
                f" | price_max={intent.price_max}"
                " | order=price ASC"
            ),
            search_start
        )

        log_search(
            "Investigation: executing TIER 2 PRIMARY database query NOW.",
            handle=search_log_handle
        )
        ###########################################
        products = query.execute().data

        ####################### AGAIN LOGGING CALL ############
        log_search(
            "Investigation: TIER 2 PRIMARY database query completed.",
            handle=search_log_handle
        )
        #######################################

        ############### CALL LOG ##############
        ################ TIER 2 PRIMARY RESULT ################

        log_search_query(
            search_log_handle,
            "TIER 2 → PRIMARY QUERY",
            (
                f"General filtered search"
                f" | category={intent.category}"
                f" | keyword={clean_kw}"
                f" | color={intent.color}"
                f" | size={intent.size}"
                f" | price_min={intent.price_min}"
                f" | price_max={intent.price_max}"
            ),
            products,
            search_start
        )
        ##############################

        # --- FALLBACK 1: STRICT CATEGORY PRESERVATION ---
        # If requested color/size/budget yielded 0 items, keep category STRICT!
        # Fetch ALL items in that category so user sees alternative colors/sizes (e.g., non-orange T-Shirts)
        if not products and intent.category:

            ################ AGAIN LOGGING CALL #############
            log_search_step(
                search_log_handle,
                "TIER 2 → FALLBACK 1",
                (
                    f"Primary query returned 0"
                    f" | preserving category='{intent.category}'"
                    " | removing other restrictions"
                ),
                search_start,
                0
            )

            log_search(
                "Investigation: executing category-preservation fallback.",
                handle=search_log_handle
            )
            ###################################
            products = (
                supabase.table("products")
                .select("*")
                .eq("category", intent.category)
                .order("price", desc=False)
                .execute()
                .data
            )
            ################### AGAIN LOGGING CALL ###########
            log_search_query(
                search_log_handle,
                "TIER 2 → FALLBACK 1",
                f"Category-only search | category={intent.category}",
                products,
                search_start
            )
            #################################

        # --- FALLBACK 2: COLOR MATCH (WHEN NO CATEGORY SPECIFIED) ---
        # If user asked for a color with no specific category match, fetch items matching requested color
        if not products and intent.color:

            ################# AGAIN LOGGING CALL ############
            log_search_step(
                search_log_handle,
                "TIER 2 → FALLBACK 2",
                (
                    "No products from previous search"
                    f" | category={intent.category}"
                    f" | searching color='{intent.color}'"
                ),
                search_start,
                0
            )

            log_search(
                "Investigation: executing color-only fallback.",
                handle=search_log_handle
            )
            #########################################

            products = (
                supabase.table("products")
                .select("*")
                .ilike("color", intent.color.capitalize())
                .order("price", desc=False)
                .execute()
                .data
            )
            ################ AGAIN LOGGING CALL ##########
            log_search_query(
                search_log_handle,
                "TIER 2 → FALLBACK 2",
                f"Color-only search | color={intent.color}",
                products,
                search_start
            )
            #####################################

        # --- FALLBACK 3: KEYWORD SEARCH ---
        if not products and intent.keyword:
            ################### AGAIN LOGGING CALL ############
            log_search_step(
                search_log_handle,
                "TIER 2 → FALLBACK 3",
                (
                    "No products from previous search"
                    f" | keyword='{clean_kw}'"
                    " → executing keyword fallback"
                ),
                search_start,
                0
            )

            log_search(
                f"Investigation: executing keyword fallback | keyword={clean_kw}",
                handle=search_log_handle
            )
            #################################################

            products = (
                supabase.table("products")
                .select("*")
                .or_(f"name.ilike.%{clean_kw}%,description.ilike.%{clean_kw}%,category.ilike.%{clean_kw}%")
                .order("price", desc=False)
                .limit(10)
                .execute()
                .data
            )
            ################### AGAIN LOGGING CALL ############
            log_search_query(
                search_log_handle,
                "TIER 2 → FALLBACK 3",
                f"Keyword search | keyword={clean_kw}",
                products,
                search_start
            )
            ###################################

        # --- FALLBACK 4: MULTI-CATEGORY STORE BALANCER (LAST RESORT ONLY) ---
        # Triggers ONLY if the query has no valid category, color, or keyword match anywhere in DB
        if not products:

            ################# LOGGING CALL ##############
            log_search_step(
                search_log_handle,
                "TIER 2 → FALLBACK 4",
                "All previous searches returned 0 → entering multi-category store balancer",
                search_start,
                0
            )

            log_search(
                "Investigation: fetching available categories.",
                handle=search_log_handle
            )
            ########################################

            all_cats = supabase.table("products").select("category").execute().data
            ################### AGAIN LOGGING CALL ###############
            log_search(
                f"Investigation: category rows retrieved = {len(all_cats)}",
                handle=search_log_handle
            )
            ####################################################
            
            distinct_categories = list(set(p.get("category") for p in all_cats if p.get("category")))
            ################### AGAIN LOGGING CALL ###############
            log_search(
                f"Investigation: distinct categories = {distinct_categories}",
                handle=search_log_handle
            )
            ####################################################

            balanced_products = []
            for cat in distinct_categories:
                ################### AGAIN LOGGING CALL ###############
                log_search(
                    f"Investigation: FALLBACK 4 querying category='{cat}' | limit=5",
                    handle=search_log_handle
                )
                ####################################################
                cat_items = (
                    supabase.table("products")
                    .select("*")
                    .eq("category", cat)
                    .order("price", desc=False)
                    .limit(5)
                    .execute()
                    .data
                )
                ################### AGAIN LOGGING CALL ###############
                log_search(
                    f"Investigation: category='{cat}' returned {len(cat_items)} products",
                    handle=search_log_handle
                )
                ####################################################

                balanced_products.extend(cat_items)
            products = balanced_products if balanced_products else supabase.table("products").select("*").order("price", desc=False).limit(15).execute().data

            ################ AGAIN LOGGING CALL ########
            log_search_query(
                search_log_handle,
                "TIER 2 → FALLBACK 4",
                "Final multi-category balanced result",
                products,
                search_start
            )
            ###########################################

    # DYNAMIC SORTING HANDLER
    sort_pref = getattr(intent, 'sorting_preference', None) or getattr(intent, 'sort', None)
    sort_val = str(sort_pref if sort_pref else '').lower()

    ############## AGAIN LOGGING CALL ###########
    log_search(
        "",
        handle=search_log_handle
    )

    log_search(
        "SORTING INVESTIGATION",
        handle=search_log_handle
    )

    log_search(
        f"Sorting preference detected: {sort_pref}",
        handle=search_log_handle
    )

    log_search(
        f"Normalized sorting value: {sort_val}",
        handle=search_log_handle
    )
    ############################################

    if ("price_desc" in sort_val or "desc" in sort_val) and products:
        ##################### AGAIN LOGGING CALL ##############
        log_search(
            "Investigation: descending price sort selected.",
            handle=search_log_handle
        )
        ##################################################
        products.sort(key=lambda x: float(x.get("price", 0)), reverse=True)
        ##################### AGAIN LOGGING CALL ##############
        log_search(
            "Investigation: products sorted by price DESC.",
            handle=search_log_handle
        )
        ##################################################

    elif products:
        ##################### AGAIN LOGGING CALL ##############
        log_search(
            "Investigation: no descending sort requested → default price ASC.",
            handle=search_log_handle
        )
        ##################################################
        # Default: ALWAYS sort price ascending so index 0 is guaranteed to be the lowest priced item!
        products.sort(key=lambda x: float(x.get("price", float("inf"))))
        ##################### AGAIN LOGGING CALL ##############
        log_search(
            "Investigation: products sorted by price ASC.",
            handle=search_log_handle
        )
        ##################################################

    ################### AGAIN LOGGING CALL ###########
    else:
        log_search(
            "Investigation: no products available for sorting.",
            handle=search_log_handle
        )

    log_product_table(
        products,
        search_log_handle,
        "FINAL PRIMARY PRODUCTS AFTER SORTING",
        limit=20
    )
    ##########################################

    # SIMILAR PRODUCTS / RECOMMENDATION
    similar_products = []
    category_to_recommend = intent.category

    ################ AGAIN LOGGING CALL ##########
    log_search(
        "",
        handle=search_log_handle
    )

    log_search(
        "SIMILAR PRODUCTS INVESTIGATION",
        handle=search_log_handle
    )

    log_search(
        f"Initial recommendation category: {category_to_recommend}",
        handle=search_log_handle
    )
    ##########################

    # If category wasn't in intent, infer it from the first primary product found
    if not category_to_recommend and products:
        ############## AGAIN LOGGING CALL ###############
        log_search(
            "Investigation: category not present in intent.",
            handle=search_log_handle
        )

        log_search(
            "Investigation: inferring category from first primary product.",
            handle=search_log_handle
        )
        #############################################
        category_to_recommend = products[0].get("category")
        ############## AGAIN LOGGING CALL ###############
        log_search(
            f"Investigation: inferred recommendation category = {category_to_recommend}",
            handle=search_log_handle
        )
        #############################################

    if category_to_recommend:
        primary_skus = [p.get("sku") for p in products if p.get("sku")]

        ############## AGAIN LOGGING CALL ###############
        log_search(
            f"Investigation: recommendation category = {category_to_recommend}",
            handle=search_log_handle
        )

        log_search(
            f"Investigation: primary SKUs excluded = {primary_skus}",
            handle=search_log_handle
        )
        ################################################
        rec_query = (
            supabase.table("products")
            .select("*")
            .eq("category", category_to_recommend)
            .order("price", desc=False)
        )
        ############### AGAIN LOGGING CALL ################
        log_search(
            "Investigation: recommendation query created.",
            handle=search_log_handle
        )

        log_search(
            f"Investigation: recommendation category filter = {category_to_recommend}",
            handle=search_log_handle
        )
        #####################################################

        # Exclude primary product SKUs from recommendations
        if primary_skus:
            ############### AGAIN LOGGING CALL ################
            log_search(
                "Investigation: excluding primary product SKUs from recommendations.",
                handle=search_log_handle
            )
            ####################################################
            rec_query = rec_query.not_.in_("sku", primary_skus)

        # Try matching color if provided
        if intent.color:
            ############### AGAIN LOGGING CALL ################
            log_search(
                f"Investigation: recommendation COLOR filter = {intent.color}",
                handle=search_log_handle
            )
            ###################################################
            rec_query = rec_query.ilike("color", intent.color.capitalize()) 

        ############### AGAIN LOGGING CALL ################
        log_search(
            "Investigation: executing recommendation query | limit=5",
            handle=search_log_handle
        )
        ###################################################
        similar_products = rec_query.limit(5).execute().data

        ############### AGAIN LOGGING CALL ################
        log_search_query(
            search_log_handle,
            "SIMILAR PRODUCTS → PRIMARY",
            (
                f"category={category_to_recommend}"
                f" | color={intent.color}"
                f" | excluded_skus={len(primary_skus)}"
            ),
            similar_products,
            search_start
        )
        ############################################
        # Fallback for similar products
        if not similar_products and primary_skus:
            ############### AGAIN LOGGING CALL ################
            log_search_step(
                search_log_handle,
                "SIMILAR PRODUCTS → FALLBACK",
                "Recommendation query returned 0 → removing color restriction",
                search_start,
                0
            )
            ############################################

            similar_products = (
                supabase.table("products")
                .select("*")
                .eq("category", category_to_recommend)
                .not_.in_("sku", primary_skus)
                .order("price", desc=False)
                .limit(5)
                .execute()
                .data
            )
            ################### AGAIN LOGGING CALL ################
            log_search_query(
                search_log_handle,
                "SIMILAR PRODUCTS → FALLBACK",
                (
                    f"category={category_to_recommend}"
                    f" | excluded_skus={len(primary_skus)}"
                ),
                similar_products,
                search_start
            )
    else:

        log_search(
            "Investigation: no recommendation category available → similar-product search skipped.",
            handle=search_log_handle
        )
    log_product_table(
        similar_products,
        search_log_handle,
        "FINAL SIMILAR PRODUCTS",
        limit=20
    )


    log_search(
        "",
        handle=search_log_handle
    )

    log_search(
        "SEARCH FINAL VERDICT",
        handle=search_log_handle
    )

    log_search(
        f"Final primary product count  : {len(products)}",
        handle=search_log_handle
    )

    log_search(
        f"Final similar product count  : {len(similar_products)}",
        handle=search_log_handle
    )

    log_search(
        f"Final recommendation category: {category_to_recommend}",
        handle=search_log_handle
    )

    log_search_step(
        search_log_handle,
        "SEARCH COMPLETE",
        "search_product execution finished",
        search_start,
        len(products)
    )
        #####################################     

    print("Extracted Intent:", intent)
    print("Product Name:", intent.product_name)
    print("Category:", intent.category)
    print("Color:", intent.color)
    print("Size:", intent.size)
    print("Price Max:", intent.price_max)
    print(f"Products Found in DB: {len(products)}")
    print(f"Similar Products Found in DB: {len(similar_products)}")

    return {
        "products": products,
        "similar_products": similar_products
    }


##################### LOGGING --> generate_response ####################
def log_generate_response(
    state,
    products,
    similar_products,
    intent_str,
    route_val,
    is_general,
    payment_url,
    sort_val,
    eval_products,
    selected_product,
    api_displayed_products,
    api_similar_products,
    response_text,
    next_bot_action,
    next_focus
):
    print("\n" + "=" * 100)
    print("GENERATE RESPONSE")
    print("=" * 100)

    print("RESPONSE INPUTS")
    print("-" * 80)
    print(f"Query                  : {state.get('query')}")
    print(f"Intent                 : {intent_str}")
    print(f"Route                  : {route_val or 'None'}")
    print(f"General request        : {is_general}")
    print(f"Products received      : {len(products)}")
    print(f"Similar products       : {len(similar_products)}")
    print(f"Sorting                : {sort_val or 'None'}")
    print(f"Payment URL            : {'Yes' if payment_url else 'No'}")
    print(f"Selected product       : {selected_product.get('name') if selected_product else 'None'}")
    print(f"Evaluation products    : {len(eval_products)}")

    print("\nRESPONSE DECISION")
    print("-" * 80)

    if is_general:
        print("Context                : General / non-shopping")
    else:
        print("Context                : Shopping")

    if payment_url:
        print("Response branch        : Checkout")
    else:
        print("Response branch        : LLM response")

    print(f"Products displayed     : {len(api_displayed_products)}")
    print(f"Similar displayed      : {len(api_similar_products)}")

    print("\nRESPONSE OUTPUT")
    print("-" * 80)
    print(f"Response length        : {len(response_text)} characters")
    print(f"Next bot action        : {next_bot_action}")
    print(
        f"Active focus product   : "
        f"{next_focus.get('name') if next_focus else 'None'}"
    )

    print("\nGENERATE RESPONSE COMPLETE")
    print("=" * 100)
##########################

@traceable(name="Generate Response", description="Convert structured product data into a natural language reply.")
def generate_response(state: ShoppingState) -> ShoppingState:
    """Convert structured product data into a natural language reply."""

    # 1. RETRIEVE PRODUCTS & INTENT DATA FIRST
    products = state.get("products") or []
    similar_products = state.get("similar_products") or []

    # Safe extraction of intent string from state
    raw_intent = state.get("intent")
    if hasattr(raw_intent, "intent"):
        intent_val = getattr(raw_intent.intent, "value", raw_intent.intent)
    else:
        intent_val = getattr(raw_intent, "value", raw_intent)
    intent_str = str(intent_val if intent_val is not None else "").lower()

    # Safe extraction of route string from state
    route_raw = state.get("route")
    route_val = str(getattr(route_raw, "value", route_raw) if route_raw is not None else "").lower()

    # General turn check
    is_general = intent_str in ["general", "greeting", "out_of_scope"] or route_val in ["general", "general_chat"]

    # 2. PAYMENT URL CHECK
    payment_url = state.get("payment_url") if intent_str == "checkout" else None

    # 3. DYNAMIC ARRAY SORTING
    sort_val = str(getattr(raw_intent, 'sorting_preference', '') or getattr(raw_intent, 'sort', '') or '').lower()
    is_cheapest = "price_asc" in sort_val or "asc" in sort_val
    is_expensive = "price_desc" in sort_val or "desc" in sort_val

    active_cat = getattr(raw_intent, "category", None) if hasattr(raw_intent, "category") else None
    if active_cat and products:
        filtered_by_cat = [p for p in products if str(p.get("category", "")).lower() == str(active_cat).lower()]
        if filtered_by_cat:
            products = filtered_by_cat

    if is_cheapest and products:
        eval_products = sorted(products, key=lambda x: float(x.get("price", float("inf"))))[:1]
    elif is_expensive and products:
        eval_products = sorted(products, key=lambda x: float(x.get("price", 0)), reverse=True)[:5]
    else:
        eval_products = products[:5]

    selected_product = state.get("selected_product") or (products[0] if products else None)

    # 4. CHECKOUT RESPONSE BRANCH
    if intent_str == "checkout" and payment_url:
        item_name = selected_product.get("name", "your selected item") if selected_product else "your selected item"
        price = selected_product.get("price", "") if selected_product else ""

        response_text = (
            f"Great choice! Here is your secure checkout link for **{item_name}**"
            f"{f' (₹{price})' if price else ''}:\n\n"
            f"👉 [Click Here to Pay & Complete Order]({payment_url})"
        )

        return {
            "response": response_text,
            "displayed_products": [selected_product] if selected_product else (products[:1] if products else []),
            "similar_products": [],
            "products": products,
            "payment_url": payment_url,
            "selected_product": selected_product
        }

    # 5. GENERAL VS SHOPPING CONTEXT EVALUATION
    if is_general:
        api_displayed_products = []
        api_similar_products = []
        prompt_eval_products = eval_products[:3] if eval_products else []
    else:
        api_displayed_products = products
        api_similar_products = similar_products[:5]
        prompt_eval_products = eval_products

    prompt_products = []
    for p in prompt_eval_products:
        prompt_products.append({
            "category": p.get("category"),
            "name": p.get("name"),
            "price": f"₹{p.get('price')}",
            "color": p.get("color"),
            "size": p.get("size")
        })

    # METADATA SUMMARIES
    if prompt_eval_products:
        distinct_categories = sorted(list(set(str(p.get("category")) for p in products if p.get("category"))))
        categories_str = ", ".join(distinct_categories) if distinct_categories else "our collection"

        distinct_colors = sorted(list(set(p.get("color").title() for p in products if p.get("color"))))
        colors_summary = ", ".join(distinct_colors) if distinct_colors else "Various colors available"

        distinct_sizes = sorted(list(set(str(p.get("size")) for p in products if p.get("size"))))
        sizes_summary = ", ".join(distinct_sizes) if distinct_sizes else "Various sizes available"
    else:
        categories_str = "our collection"
        colors_summary = "None"
        sizes_summary = "None"

    prompt = f"""Query: {state["query"]}
Intent: {intent_str}
Store Categories: {categories_str}
Stock Colors: {colors_summary}
Stock Sizes: {sizes_summary}
Top Products: {prompt_products if prompt_products else "None"}

INSTRUCTIONS:
- LANGUAGE MATCHING (STRICT): Always respond in the EXACT SAME language and script as the user query:
  * English query -> Respond ONLY in pure, natural English.
  * Hinglish (Roman Hindi) query -> Respond in friendly Hinglish.
  * Devanagari Hindi query -> Respond ONLY in pure Hindi script.
- Answer directly and concisely in 1-2 friendly sentences.
- If query is non-shopping (general/greeting/unsupported items), state clearly that we don't carry that item, mention our store apparel categories, and optionally recommend top alternatives from Top Products.
- If query is strictly about COLORS, state ONLY the colors listed in Stock Colors ({colors_summary}).
- If query is strictly about SIZES, state ONLY the sizes listed in Stock Sizes ({sizes_summary})."""

    try:
        response_text = invoke_with_fallback([
            ("system", RESPONSE_PROMPT),
            ("human", prompt)
        ])
    except Exception as e:
        print(f"[generate_response Error]: {e}")
        response_text = "Here are top clothing choices based on your request!"

    # ── PERSISTENT TURN SIGNALS ──────────────────────────────────────────────
    if intent_str not in ("general", "greeting", "out_of_scope"):
        next_bot_action = "showed_products" if products else "offered_alternatives"
    else:
        next_bot_action = state.get("last_bot_action")

    next_focus = state.get("active_focus_product")
    if products and intent_str not in ("general", "greeting", "out_of_scope"):
        intent_product_name = getattr(raw_intent, "product_name", None)
        if intent_product_name:
            named_match = next(
                (p for p in products if intent_product_name.lower() in p.get("name", "").lower()),
                None
            )
            next_focus = named_match if named_match else products[0]
        else:
            next_focus = state.get("active_focus_product") or products[0]

    ############ LOGGING CALL ############
    log_generate_response(
    state=state,
    products=products,
    similar_products=similar_products,
    intent_str=intent_str,
    route_val=route_val,
    is_general=is_general,
    payment_url=payment_url,
    sort_val=sort_val,
    eval_products=eval_products,
    selected_product=selected_product,
    api_displayed_products=api_displayed_products,
    api_similar_products=api_similar_products,
    response_text=response_text,
    next_bot_action=next_bot_action,
    next_focus=next_focus
    )
    ###################################

    return {
        "response": response_text,  # Clean string variable (No .content crash)
        "displayed_products": api_displayed_products,
        "similar_products": api_similar_products,
        "products": products,
        "payment_url": payment_url,
        "selected_product": selected_product,
        "last_bot_action": next_bot_action,
        "active_focus_product": next_focus
    }


##################### LOGGING --> get_table_primary_key #####################
def log_get_table_primary_key(
    table_name,
    schema_url,
    status_code,
    definitions_found,
    table_found,
    primary_key_found,
    result,
    error=None
):
    print("\n" + "=" * 80)
    print("GET TABLE PRIMARY KEY")
    print("=" * 80)

    print("INPUT")
    print("-" * 80)
    print(f"Table name             : {table_name}")

    print("\nSCHEMA INSPECTION")
    print("-" * 80)
    print(f"Schema endpoint        : {schema_url}")
    print(f"HTTP status            : {status_code}")
    print(f"Definitions found      : {definitions_found}")
    print(f"Table definition found : {table_found}")

    print("\nPRIMARY KEY")
    print("-" * 80)
    print(f"Primary key detected   : {primary_key_found or 'None'}")
    print(f"Final result           : {result}")
    
    if error:
        print(f"Warning / error        : {error}")

    print("\nGET TABLE PRIMARY KEY COMPLETE")
    print("=" * 80)
##########################

def get_table_primary_key(table_name: str = "products") -> str:
    """Inspects table schema directly via Supabase API to find the primary key column."""
    try:
        # Fetch OpenAPI schema definition from Supabase
        schema_url = f"{supabase.supabase_url}/rest/v1/"
        headers = {"apikey": supabase.supabase_key, "Authorization": f"Bearer {supabase.supabase_key}"}
        
        import requests
        response = requests.get(schema_url, headers=headers)
        if response.status_code == 200:
            definitions = response.json().get("definitions", {})
            table_def = definitions.get(table_name, {})
            
            # PostgREST schema lists primary keys in description or properties
            properties = table_def.get("properties", {})
            for col, details in properties.items():
                if "Primary Key" in details.get("description", ""):
                    ################ LOGGING CALL ##############
                    log_get_table_primary_key(
                        table_name,
                        schema_url,
                        response.status_code,
                        len(definitions),
                        bool(table_def),
                        col,
                        col
                    )
                    ###########################################
                    return col
                
    except Exception as e:
        print(f"[Schema Fetch Warning]: {e}")
        ################ LOG CALL #############
    log_get_table_primary_key(
        table_name,
        f"{supabase.supabase_url}/rest/v1/",
        None,
        0,
        False,
        None,
        "sku"
    )
        ########################################
        
    return "sku"  # manual fallback if schema inspection fails


##################### LOGGING --> create_checkout_session #####################
def log_create_checkout_session(
    state,
    products,
    req_name,
    target_product,
    priority,
    pk_col=None,
    pk_val=None,
    db_product=None,
    stock_count=None,
    actual_price=None,
    payment_url=None,
    error=None
):
    print("\n" + "=" * 100)
    print("CREATE CHECKOUT SESSION")
    print("=" * 100)

    print("CHECKOUT INPUT")
    print("-" * 80)
    print(f"Query                  : {state.get('query')}")
    print(f"Requested product      : {req_name or 'None'}")
    print(f"Products in memory     : {len(products)}")

    print("\nPRODUCT SELECTION")
    print("-" * 80)
    print(f"Priority               : {priority}")
    print(
        f"Target product         : "
        f"{target_product.get('name') if target_product else 'None'}"
    )

    print("\nDATABASE")
    print("-" * 80)
    print(f"Primary key column     : {pk_col or 'None'}")
    print(f"Primary key value      : {pk_val or 'None'}")
    print(
        f"DB product             : "
        f"{db_product.get('name') if db_product else 'None'}"
    )

    print("\nSTOCK / PAYMENT")
    print("-" * 80)
    print(f"Stock                  : {stock_count if stock_count is not None else 'None'}")
    print(
        f"Price                  : "
        f"₹{actual_price if actual_price is not None else 'None'}"
    )
    print(f"Payment URL            : {payment_url or 'None'}")

    if error:
        print(f"\nERROR / WARNING")
        print("-" * 80)
        print(f"{error}")

    print("\nCREATE CHECKOUT SESSION COMPLETE")
    print("=" * 100)
##########################


@traceable(name="Create Checkout Session", description="Deterministic checkout node with history scanning and Razorpay payment link creation.")
def create_checkout_session(state: ShoppingState, config: RunnableConfig) -> ShoppingState:
    """
    DETERMINISTIC CHECKOUT NODE:
    1. Checks extracted intent for newly requested product_name (highest priority).
    2. Scans recent conversation history for the last explicitly mentioned product
       name and fetches it from DB (handles 'ha kharidna hai' generic confirmations).
    3. Falls back to active_focus_product -> selected_product -> products[0].
    4. Verifies stock and calls Razorpay to generate a payment link.
    """
    products = state.get("products") or []
    intent = state.get("intent")

    # Extract requested product name from the newly extracted intent
    req_name = getattr(intent, "product_name", None) if intent else None
    target_product = None

    # ── PRIORITY 1: Explicit product_name in current intent ──────────────────
    if req_name:
        try:
            db_res = supabase.table("products").select("*").ilike("name", f"%{req_name}%").limit(1).execute()
            if db_res and db_res.data:
                target_product = db_res.data[0]
                print(f"[Checkout P1] Found via intent product_name: {target_product.get('name')}")
                ################## LOGGING CALL ####################
                log_create_checkout_session(
                    state=state,
                    products=products,
                    req_name=req_name,
                    target_product=target_product,
                    priority="P1 - Current intent product_name"
                )
                #####################################
        except Exception as e:
            print(f"[Checkout Intent Name Search Error]: {e}")

    # Check current products memory for req_name match
    if not target_product and req_name and products:
        for p in products:
            if req_name.lower() in p.get("name", "").lower():
                target_product = p
                print(f"[Checkout P1b] Found in products memory: {target_product.get('name')}")
                ################## LOGGING CALL ##############
                log_create_checkout_session(
                    state=state,
                    products=products,
                    req_name=req_name,
                    target_product=target_product,
                    priority="P1b - Current products memory"
                )
                ##################################
                break

    # ── PRIORITY 2: Scan conversation history for last named product ──────────
    # Handles generic confirmations ("ha kharidna hai", "buy it") where intent.product_name is None
    if not target_product:
        try:
            history_snapshots = load_history(config)
            for snap in history_snapshots:  # newest -> oldest
                past_intent = snap.get("intent")
                past_name = getattr(past_intent, "product_name", None) if past_intent else None
                if past_name:
                    db_res = supabase.table("products").select("*").ilike("name", f"%{past_name}%").limit(1).execute()
                    if db_res and db_res.data:
                        target_product = db_res.data[0]
                        print(f"[Checkout P2] Found via history product_name='{past_name}': {target_product.get('name')}")
                        ################## LOGGING CALL ##############
                        log_create_checkout_session(
                            state=state,
                            products=products,
                            req_name=req_name,
                            target_product=target_product,
                            priority="P2 - Conversation history"
                        )
                        ##################################
                        break
        except Exception as hist_err:
            print(f"[Checkout History Scan Error]: {hist_err}")

    # ── PRIORITY 3: active_focus_product -> selected_product -> products[0] ────
    if not target_product:
        afp = state.get("active_focus_product")
        sel = state.get("selected_product")
        p0 = products[0] if products else None

        afp_name = (afp or {}).get("name", "")
        raw_query = state.get("query", "").lower()

        if afp and (req_name is None or req_name.lower() in afp_name.lower()):
            target_product = afp
            print(f"[Checkout P3a] Using active_focus_product: {afp_name}")
            ################# LOGGING CALL #####################
            log_create_checkout_session(
                state=state,
                products=products,
                req_name=req_name,
                target_product=target_product,
                priority="P3a - active_focus_product"
            )
            ############################

        elif sel:
            target_product = sel
            print(f"[Checkout P3b] Using selected_product: {sel.get('name')}")
            ################# LOGGING CALL #####################
            log_create_checkout_session(
                state=state,
                products=products,
                req_name=req_name,
                target_product=target_product,
                priority="P3b - selected_product"
            )
            ###########################

        elif p0:
            # Last resort: Name-coherence check before using products[0]
            p0_name = p0.get("name", "").lower()
            focus_name = afp_name.lower() if afp else ""
            if any(w in p0_name for w in raw_query.split() if len(w) > 3) or (focus_name and focus_name in p0_name):
                target_product = p0
                print(f"[Checkout P3c] Using products[0] (name-coherent): {p0.get('name')}")
                ################# LOGGING CALL #####################
                log_create_checkout_session(
                    state=state,
                    products=products,
                    req_name=req_name,
                    target_product=target_product,
                    priority="P3c - products[0] name-coherent"
                )
                ###########################
            else:
                print(f"[Checkout P3c] Skipped products[0] ('{p0.get('name')}') — not coherent with query '{raw_query}'")

    if not target_product:
        #################### LOGGING CALL ###############
        response_text = (
            "Sorry, I couldn't find an item in our conversation "
            "to checkout. Which item would you like to buy?"
        )

        log_create_checkout_session(
            state=state,
            products=products,
            req_name=req_name,
            target_product=None,
            priority="NONE - No product found",
            error="All checkout product-selection priorities failed."
        )

        return {
            "response": response_text,
            "payment_url": None,
            "products": products
        }

        # Temporary commented-out fallback response for debugging purposes
        # return {
        #     "response": "Sorry, I couldn't find an item in our conversation to checkout. Which item would you like to buy?",
        #     "payment_url": None,
        #     "products": products
        # }
    ###########################################


    # 1. Dynamically retrieve primary key column name
    pk_col = get_table_primary_key("products")
    pk_val = target_product.get(pk_col)

    # 2. Direct DB Ground-Truth Check using the dynamic primary key
    try:
        if pk_val:
            db_res = supabase.table("products").select("*").eq(pk_col, pk_val).execute()
        else:
            p_name = target_product.get("name", "")
            db_res = supabase.table("products").select("*").ilike("name", f"%{p_name}%").limit(1).execute()

        db_product = db_res.data[0] if (db_res and db_res.data) else target_product
    except Exception as db_err:
        print(f"[Supabase Lookup Error]: {db_err}")
        db_product = target_product

    # Safe stock check
    raw_stock = db_product.get("stock", 0)
    try:
        stock_count = int(raw_stock) if raw_stock is not None else 0
    except (ValueError, TypeError):
        stock_count = 0

    if not db_product or stock_count <= 0:
        #################### LOGGING CALL ###############
        response_text = (
            f"Sorry, **{target_product.get('name', 'this item')}** "
            f"is currently out of stock."
        )

        log_create_checkout_session(
            state=state,
            products=products,
            req_name=req_name,
            target_product=target_product,
            priority="PRODUCT SELECTED - OUT OF STOCK",
            pk_col=pk_col,
            pk_val=pk_val,
            db_product=db_product,
            stock_count=stock_count,
            actual_price=None,
            payment_url=None,
            error="Product found but stock_count <= 0."
        )

        return {
            "response": response_text,
            "payment_url": None,
            "products": products
        }

        # Temporary commented-out fallback response for debugging purposes
        # return {
        #     "response": f"Sorry, **{target_product.get('name', 'this item')}** is currently out of stock.",
        #     "payment_url": None,
        #     "products": products
        # }
    ##############################################

    actual_price = float(db_product.get("price", 0))
    p_name = db_product.get("name", "Product")
    p_identifier = db_product.get(pk_col, pk_val or "ITEM")

    # 3. Call Razorpay API to generate a real Payment Link
    try:
        payment_link = razorpay_client.payment_link.create({
            "amount": int(actual_price * 100),  # Amount in paise
            "currency": "INR",
            "accept_partial": False,
            "description": f"Purchase of {p_name} ({pk_col.upper()}: {p_identifier})",
            "customer": {
                "name": "Customer",
                "email": "customer@example.com",
                "contact": "+919876543210"
            },
            "notify": {"sms": False, "email": False},
            "reminder_enable": False,
            "notes": {pk_col: str(p_identifier)}
        })

        payment_url = payment_link.get("short_url")

        #################### LOGGING CALL ###############
        log_create_checkout_session(
            state=state,
            products=products,
            req_name=req_name,
            target_product=target_product,
            priority="CHECKOUT SUCCESS",
            pk_col=pk_col,
            pk_val=pk_val,
            db_product=db_product,
            stock_count=stock_count,
            actual_price=actual_price,
            payment_url=payment_url
        )
        ######################################

        return {
            "payment_url": payment_url,
            "selected_product": db_product,
            "products": products
        }

    except Exception as e:
        print(f"Razorpay API Error: {e}")
        fallback_url = db_product.get("payment_link") or "#"

        #################### LOGGING CALL ###############
        payment_url = (
            fallback_url
            if fallback_url != "#"
            else None
        )

        log_create_checkout_session(
            state=state,
            products=products,
            req_name=req_name,
            target_product=target_product,
            priority="CHECKOUT FALLBACK - Razorpay failed",
            pk_col=pk_col,
            pk_val=pk_val,
            db_product=db_product,
            stock_count=stock_count,
            actual_price=actual_price,
            payment_url=payment_url,
            error=str(e)
        )

        return {
            "payment_url": payment_url,
            "selected_product": db_product,
            "products": products
        }
        # Temporary commented-out fallback response for debugging purposes
        # return {
        #     "payment_url": fallback_url if fallback_url != "#" else None,
        #     "selected_product": db_product,
        #     "products": products
        # }
    #################################
    

##################### LOGGING --> route_after_intent #####################
def log_route_after_intent(
    intent_val,
    next_node
):
    print("\n" + "=" * 80)
    print("ROUTE AFTER INTENT")
    print("=" * 80)

    print("INPUT")
    print("-" * 80)
    print(f"Intent                 : {intent_val or 'None'}")

    print("\nROUTING DECISION")
    print("-" * 80)
    print(f"Next node              : {next_node}")

    print("\nROUTE AFTER INTENT COMPLETE")
    print("=" * 80)
##########################


def route_after_intent(state: ShoppingState) -> str:
    """
    Check if intent extracted by LLM is CHECKOUT.
    If yes -> Branch directly to create_checkout_session.
    If no  -> Continue normal flow to context_decision.
    """
    raw_intent = state.get("intent")
    
    # Extract intent string safely whether raw_intent is a Pydantic model, Enum, or raw string
    if hasattr(raw_intent, "intent"):
        intent_val = getattr(raw_intent.intent, "value", raw_intent.intent)
    else:
        intent_val = getattr(raw_intent, "value", raw_intent)

    if str(intent_val).lower() == "checkout":
        ################### LOGGING CALL ################
        log_route_after_intent(
            intent_val=intent_val,
            next_node="create_checkout_session"
        )
        ###############################################
        return "create_checkout_session"

    ############### LOGGING CALL ################
    log_route_after_intent(
        intent_val=intent_val,
        next_node="search_products"
    )
    ###########################################
    return "search_products"


################## LOGGING --> fetch_featured #####################
##################### LOGGING --> fetch_featured #####################
def log_fetch_featured(
    distinct_categories,
    featured_count,
    fallback_used,
    error=None
):
    print("\n" + "=" * 80)
    print("FETCH FEATURED")
    print("=" * 80)

    print("FETCH")
    print("-" * 80)
    print(f"Categories found      : {len(distinct_categories)}")
    print(f"Featured products     : {featured_count}")
    print(f"Fallback query used   : {fallback_used}")

    if error:
        print(f"Error                 : {error}")

    print("\nFETCH FEATURED COMPLETE")
    print("=" * 80)
##########################

@traceable(name="Fetch Featured", description="Fetch top products per category after an out-of-stock denial / alternative offer.")
def fetch_featured(state: ShoppingState) -> ShoppingState:
    """
    Surfaces real product cards when the user affirms after a denial.
    Fetches top 3 products per catalog category from Supabase.
    """
    try:
        # Get distinct categories available in DB
        all_cats_res = supabase.table("products").select("category").execute()
        distinct_categories = list(set(
            p.get("category") for p in (all_cats_res.data or []) if p.get("category")
        ))

        featured: list = []
        for cat in distinct_categories:
            cat_items = (
                supabase.table("products")
                .select("*")
                .eq("category", cat)
                .order("price", desc=False)
                .limit(3)
                .execute()
                .data
            )
            if cat_items:
                featured.extend(cat_items)

        # Fallback: raw limit query if category enumeration fails or returns empty
        if not featured:
            featured = (
                supabase.table("products")
                .select("*")
                .order("price", desc=False)
                .limit(12)
                .execute()
                .data
            )
            ############### LOGGING CALL ################
            log_fetch_featured(
                distinct_categories=distinct_categories,
                featured_count=len(featured),
                fallback_used=True
            )
        else:
            log_fetch_featured(
                distinct_categories=distinct_categories,
                featured_count=len(featured),
                fallback_used=False
            )
        #############################################
    except Exception as e:
        print(f"[fetch_featured error]: {e}")
        featured = []

        ################ LOGGING CALL ################
        log_fetch_featured(
            distinct_categories=[],
            featured_count=0,
            fallback_used=False,
            error=str(e)
        )
        #########################################

    # # Inject a RECOMMEND intent so generate_response produces a showcase reply
    # featured_intent = ShoppingIntentModel(intent=IntentType.RECOMMEND)

    #Instant response without making a second heavy 9s LLM call
    text_reply = (
        "Sure! Here are some of our top trending fashion picks for you across our catalog. "
        "Tap any item to explore details!"
    )

    return {
        "response": text_reply,
        "products": featured,
        "displayed_products": featured,
        "similar_products": [],
        "intent": "showed_products"
    }



######################### LOGGING & DEBUGGING #########################

# 1. route_post_sync logging
def log_route_post_sync_state(route, next_node):

    route = getattr(route, "value", route)

    print("\n" + "=" * 80)
    print("ROUTE POST SYNC")
    print("=" * 80)

    print("\nINPUT")
    print("-" * 80)
    print(f"| {'Field':<20} | {'Value':<52} |")
    print(f"|{'-' * 22}|{'-' * 54}|")
    print(f"| {'route':<20} | {str(route):<52} |")

    print("\nFLOW")
    print("-" * 80)

    print(
        f"""
        ┌──────────────────────────────────────────────┐
        │ ROUTER                                       │
        │                                              │
        │ route = {str(route):<34} │
        └──────────────────────┬───────────────────────┘
                               │
                               ▼
        ┌──────────────────────────────────────────────┐
        │ ROUTE POST SYNC                              │
        │                                              │
        │ Check router route                           │
        └──────────────────────┬───────────────────────┘
                               │
                               ▼
        ┌──────────────────────────────────────────────┐
        │ NEXT NODE                                    │
        │                                              │
        │ {next_node:<44} │
        └──────────────────────────────────────────────┘
        """
    )

    print("\nOUTPUT")
    print("-" * 80)
    print(f"| {'next_node':<20} | {next_node:<52} |")

    print("=" * 80)

# 2. route_after_intent logging
def log_route_after_intent_state(
    intent,
    last_action,
    has_specific_filters,
    next_node
):
    intent_str = str(
        getattr(getattr(intent, "intent", intent), "value",
                getattr(intent, "intent", intent))
        or ""
    ).lower()

    print("\n" + "=" * 80)
    print("ROUTE AFTER INTENT")
    print("=" * 80)

    print("\nINPUT")
    print("-" * 80)
    print(f"| {'Field':<25} | {'Value':<47} |")
    print(f"|{'-' * 27}|{'-' * 49}|")
    print(f"| {'intent':<25} | {intent_str:<47} |")
    print(f"| {'last_bot_action':<25} | {str(last_action):<47} |")
    print(f"| {'has_specific_filters':<25} | {str(has_specific_filters):<47} |")

    print("\nFLOW")
    print("-" * 80)

    print(
        f"""
        ┌──────────────────────────────────────────────┐
        │ EXTRACT INTENT                               │
        │                                              │
        │ intent = {intent_str:<32} │
        └──────────────────────┬───────────────────────┘
                               │
                               ▼
        ┌──────────────────────────────────────────────┐
        │ ROUTE AFTER INTENT                            │
        │                                              │
        │ Check intent + filters + last action         │
        └──────────────────────┬───────────────────────┘
                               │
                               ▼
        ┌──────────────────────────────────────────────┐
        │ NEXT NODE                                    │
        │                                              │
        │ {next_node:<44} │
        └──────────────────────────────────────────────┘
        """
    )

    print("\nOUTPUT")
    print("-" * 80)
    print(f"| {'Field':<25} | {'Value':<47} |")
    print(f"|{'-' * 27}|{'-' * 49}|")
    print(f"| {'next_node':<25} | {next_node:<47} |")

    print("=" * 80)

#################################################


# ── GRAPH INITIALIZATION ──────────────────────────────────────────────────────
graph = StateGraph(ShoppingState)

# 1. NODES
graph.add_node("reset_turn_slots", reset_turn_slots)      # Ephemeral slot reset pre-step
graph.add_node("router", router)
graph.add_node("general_chat", general_chat)
graph.add_node("extract_intent", extract_intent)
graph.add_node("context_decision", context_decision)
graph.add_node("search_products", search_product)
graph.add_node("create_checkout_session", create_checkout_session)
graph.add_node("generate_response", generate_response)
graph.add_node("fetch_featured", fetch_featured)          # Affirmative follow-up showcase node

# 2. Edges
graph.add_edge(START, "reset_turn_slots")

# # STEP 2: PARALLEL FAN-OUT (Preserves speed & concurrency)
# graph.add_edge("reset_turn_slots", "router")
# graph.add_edge("reset_turn_slots", "extract_intent")

graph.add_edge("reset_turn_slots", "router")
graph.add_edge("router", "context_decision")

# ── 1. ROUTER GATE FUNCTION (Gate 1) ──────────────────────────────────────────
def route_post_sync(state: ShoppingState) -> str:
    """
    Rely strictly on Router LLM output.
    General chatter goes to general_chat.
    All shopping queries go to extract_intent.
    """
    route = state.get("route")
    route_str = str(getattr(route, "value", route) or "").lower()

    ###################### logging call ######################
    #1. Temporarily commments out for logging...
    # if route_str == "general":
    #     return "general_chat"

    # return "extract_intent"

    if route_str == "general":
        next_node = "general_chat"
    else:
        next_node = "extract_intent"

    log_route_post_sync_state(route, next_node)

    return next_node
    #############################################


# ── 2. INTENT GATE FUNCTION (Gate 2) ──────────────────────────────────────────
def route_after_intent(state: ShoppingState) -> str:
    """
    Evaluates extracted intent and extracted slots:
    - Checkout -> create_checkout_session
    - Affirmation ('yes'/'sure' without product filters) -> fetch_featured
    - Product Search (with color/size/category filters) -> search_products
    """
    raw_intent = state.get("intent")
    intent_val = getattr(raw_intent, "intent", raw_intent)
    intent_str = str(getattr(intent_val, "value", intent_val) or "").lower()
    last_action = state.get("last_bot_action")

################ Logging call ######################

    # 2. Check if user provided actual shopping filters
    has_specific_filters = any([
        getattr(raw_intent, "category", None),
        getattr(raw_intent, "product_name", None),
        getattr(raw_intent, "color", None),
        getattr(raw_intent, "size", None),
        getattr(raw_intent, "price_max", None)
    ])


    #### Temporarily commented out for logging
    # # 1. Checkout link generation
    #     if intent_str == "checkout":
    #         return "create_checkout_session"

    # # 3. If previous turn offered alternatives and current query has NO specific filters (e.g. 'yes', 'sure', 'ha')
    # if last_action in ("offered_alternatives", "denied_oos") and not has_specific_filters:
    #     print("[route_after_intent] Affirmation follow-up -> Branching to fetch_featured")
    #     return "fetch_featured"

    # if intent_str == "recommend" and not has_specific_filters:
    #     return "fetch_featured"

    # # 4. Default: Search DB for the requested product
    # return "search_products"

    if intent_str == "checkout":
            next_step = "create_checkout_session"

    elif (
        last_action in ("offered_alternatives", "denied_oos")
        and not has_specific_filters
    ):
        next_step = "fetch_featured"

    elif intent_str == "recommend" and not has_specific_filters:
        next_step = "fetch_featured"

    else:
        next_step = "search_products"

    log_route_after_intent_state(
        intent=intent_str,
        last_action=last_action,
        has_specific_filters=has_specific_filters,
        next_node=next_step
    )

    return next_step
##############################################


# ── 3. GRAPH INITIALIZATION & CONDITIONAL EDGES ──────────────────────────────
# Gate 1: After Router & Context Decision
graph.add_conditional_edges(
    "context_decision",
    route_post_sync,
    {
        "general_chat": "general_chat",
        "extract_intent": "extract_intent",
    }
)

# Gate 2: After Intent Extraction
graph.add_conditional_edges(
    "extract_intent",
    route_after_intent,
    {
        "create_checkout_session": "create_checkout_session",
        "search_products": "search_products",
        "fetch_featured": "fetch_featured",
    }
)

# 4. TERMINAL EDGES
graph.add_edge("search_products", "generate_response")
graph.add_edge("create_checkout_session", "generate_response")
graph.add_edge("fetch_featured", "generate_response")
graph.add_edge("general_chat", END)
graph.add_edge("generate_response", END)

# 5. COMPILE GRAPH
memory = InMemorySaver()
workflow = graph.compile(checkpointer=memory)

# # ── PURE AI ROUTER GATE FUNCTION (ZERO MANUAL STRING MATCHING) ────────────────
# def route_post_sync(state: ShoppingState) -> str:
#     """
#     Pure AI Gate Function:
#     Rely strictly on Router LLM output, Intent extraction, and Bot Action Signals.
#     No hardcoded frozensets, regex, or manual word matching!
#     """
#     route = state.get("route")
#     route_str = str(getattr(route, "value", route) or "").lower()

#     last_action = state.get("last_bot_action")

#     # Safe extraction of extracted intent
#     intent = state.get("intent")
#     intent_type = getattr(intent, "intent", intent)
#     intent_str = str(getattr(intent_type, "value", intent_type) or "").lower()

#     print(f"[route_post_sync] route={route_str!r} | intent={intent_str!r} | last_action={last_action!r}")

#     # 1. EVALUATE CHECKOUT INTENT (Highest Priority)
#     if intent_str == "checkout":
#         return "create_checkout_session"

#     # 2. PURE AI AFFIRMATIVE FOLLOW-UP (No manual frozensets!)
#     # If bot previously offered alternatives/denied AND the AI Router classified current turn as 'shopping'
#     if last_action == "offered_alternatives" and route_str == "shopping":
#         print("[route_post_sync] Pure AI Signal -> Branching to fetch_featured")
#         return "fetch_featured"

#     # 3. EVALUATE GENERAL / BANTER ROUTE
#     if route_str == "general":
#         return "general_chat"

#     # 4. EVALUATE CONTEXT DECISION ROUTE
#     context_route = state.get("context_route")
#     context_str = str(getattr(context_route, "value", context_route) or "").lower()

#     if context_str == "context":
#         return "generate_response"

#     # 5. DEFAULT SHOPPING FLOW
#     return "search_products"


# # 3. CONDITIONAL BRANCHING
# graph.add_conditional_edges(
#     "context_decision",
#     route_post_sync,
#     {
#         "general_chat": "general_chat",
#         "create_checkout_session": "create_checkout_session",
#         "search_products": "search_products",
#         "generate_response": "generate_response",
#         "fetch_featured": "fetch_featured",
#     }
# )

# # 4. TERMINAL EDGES
# graph.add_edge("search_products", "generate_response")
# graph.add_edge("create_checkout_session", "generate_response")
# graph.add_edge("fetch_featured", "generate_response")
# graph.add_edge("general_chat", END)
# graph.add_edge("generate_response", END)

# # 5. COMPILE GRAPH
# memory = InMemorySaver()
# workflow = graph.compile(checkpointer=memory)



# # Graph
# graph = StateGraph(ShoppingState)

# graph.add_node("router", router)
# graph.add_node("general_chat", general_chat)
# graph.add_node("extract_intent", extract_intent)
# graph.add_node("context_decision", context_decision)
# graph.add_node("search_products", search_product)
# graph.add_node("create_checkout_session", create_checkout_session)
# graph.add_node("generate_response", generate_response)

# # Parallel Fan-Out from START
# graph.add_edge(START, "router")
# graph.add_edge(START, "extract_intent")

# # Parallel Fan-In into context_decision
# graph.add_edge("router", "context_decision")
# graph.add_edge("extract_intent", "context_decision")

# # Router Gate Function
# def route_post_sync(state: ShoppingState) -> str:
#     route = state.get("route")
#     route_str = str(route.value if hasattr(route, "value") else route).lower()

#     # If general greeting/banter
#     if route_str == "general":
#         return "general_chat"

#     # Evaluate checkout intent
#     intent = state.get("intent")
#     intent_type = getattr(intent, "intent", intent)
#     intent_str = str(intent_type.value if hasattr(intent_type, "value") else intent_type).lower()

#     if intent_str == "checkout":
#         return "create_checkout_session"

#     # Evaluate context route
#     context_route = state.get("context_route")
#     context_str = str(getattr(context_route, "value", context_route)).lower()

#     if context_str == "context":
#         return "generate_response"

#     return "search_products"


# # Conditional Branching
# graph.add_conditional_edges(
#     "context_decision",
#     route_post_sync,
#     {
#         "general_chat": "general_chat",
#         "create_checkout_session": "create_checkout_session",
#         "search_products": "search_products",
#         "generate_response": "generate_response",
#     }
# )

# # Terminal Edges
# graph.add_edge("search_products", "generate_response")
# graph.add_edge("create_checkout_session", "generate_response")
# graph.add_edge("general_chat", END)
# graph.add_edge("generate_response", END)

# memory = InMemorySaver()
# workflow = graph.compile(checkpointer=memory)

# # Context Decision Edge
# graph.add_conditional_edges(
#     "context_decision",
#     decide_context,
#     {
#         ContextRoute.SEARCH: "search_products",
#         ContextRoute.CONTEXT: "generate_response",
#     },
# )


# graph.add_edge("search_products", "generate_response")
# graph.add_edge("create_checkout_session", "generate_response")
# graph.add_edge("general_chat", END)
# graph.add_edge("generate_response", END)


# memory = InMemorySaver()
# workflow = graph.compile(checkpointer=memory)
# # workflow
# workflow.get_graph().draw_mermaid()
