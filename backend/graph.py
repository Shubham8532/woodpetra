import os
import razorpay
from typing import List, Optional
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver
from langchain_core.runnables import RunnableConfig
# from langchain_core.output_parsers import PydanticOutputParser
from langsmith import traceable
from backend.config import llm_fast, llm_strong, supabase
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

@traceable(name="Router", description="Route the user query to the appropriate workflow path.")
def router(state: ShoppingState):

    query = state["query"]
    structured_llm = llm_fast.with_structured_output(RouterModel)

    result = structured_llm.invoke(
        [
            ("system", ROUTER_PROMPT),
            ("human", query)
        ]
    )
    return {
        "route": result.route    
    }


@traceable(name="Decide Route", description="Decide the next workflow path based on the router's output.")
def decide_route(state: ShoppingState):
    return state['route']


@traceable(name="Load History", description="Load conversation history from the workflow's state history.")
def load_history(config: RunnableConfig):
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

    history = []
    seen = set()
    for snapshot in snapshots:
        # print(snapshot.values)      # temporary
        values = snapshot.values

    #     if values.get("query") and values.get("response"):
    #         history.append(values)

    # # print("History:", len(history))
    # return history
        if not values.get("query"):
            continue

        if not values.get("response"):
            continue

        key = (values["query"], values["response"])

        if key in seen:
            continue

        seen.add(key)
        history.append(values)
    return history



# later update
@traceable(name="General Chat", description="Handle general chat queries using conversation history.")
def general_chat(state: ShoppingState, config: RunnableConfig):
    # print("Workflow id:", id(workflow))
    # print("Memory id:", id(memory))
    # print(type(config))
    # print(config)
    # print(config["configurable"])

    history = load_history(config)

    history_text = build_conversation(history)

    prompt = f"""
    Below is the conversation history.

    Use it to answer the current user's question directly and naturally.

    If the user asks something like:
    - What is my name?
    - Which product did I ask about?
    - What's its price?
    - What color did I choose?
    - Follow-up questions about sizes, colors, or options (e.g., "Sizes?", "Colors?")

    You MUST answer using the conversation history if the answer exists there.

    CRITICAL INSTRUCTIONS:
    - Answer directly without meta-commentary.
    - DO NOT apologize, critique, or mention previous assistant mistakes or past responses (never say "I made a mistake in my previous response" or "You asked about X, not Y").
    - Keep responses clean, concise, and helpful (1-2 sentences).

    Conversation History:
    {history_text}

    Current User Query:
    {state["query"]}
    """

    # print("=" * 80)
    # print(prompt)
    # print("=" * 80)
    
    history = load_history(config)

    # print(history)

    history_text = build_conversation(history)

    # print(history_text)

    # print(config)

    # print("history =", history)
    from pprint import pprint

    print("=" * 80)
    print("HISTORY")
    pprint(history)
    print("=" * 80)
    response = llm_fast.invoke(
    [
        (
            "system",
            GENERAL_CHAT_PROMPT,
            ),
        (
            "human",
            prompt
        )
    ]
)

    return {
        "response": response.content,
        "products": state.get("products", []),
        "displayed_products": [],
        "similar_products": []
    }


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

        response = item.get('response', '')

        conversation.append(
            f"User: {query}\n"
            f"Assistant: {response}"
        )

    # Limit to the last `max_turns`
    conversation = conversation[:max_turns]
    conversation.reverse()  # Reverse to get Oldest -> Newest

    history_text = "\n\n".join(conversation)   # join() simply combines all strings with two newlines between them.
    return history_text, active_category  


# ========================================== 
# For 7B model compatibility
# Output parser instance for standard text parsing fallback
# intent_parser = PydanticOutputParser(pydantic_object=ShoppingIntentModel)


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
    history_text, active_category = build_conversation(history, max_turns=5)

    query = state['query']

    # Can comment out for 70 model
    # structured_output = llm.with_structured_output(ShoppingIntentModel)

    system_prompt = INTENT_PROMPT + f"""
    Active Session Category: {active_category if active_category else "None"}

    Previous conversation (Last 5 turns):
    {history_text}

    FUZZY TYPO & PHONETIC CATEGORY MAPPING:
    - Automatically infer and map typos, slang, or misspelled items to standard catalog categories:
      * Phonetic/spelling typos like "hoofie", "hoofies", "hoddie", "hoddies", "sweatshirt" -> category: "Hoodie"
      * "shrt", "shrts", "formal shirt", "casual shirt" -> category: "Shirt"
      * "tshirt", "t-shirt", "tee", "tees" -> category: "T-Shirt"
      * "pant", "pants", "trouser", "trousers", "slacks" -> category: "Trouser"
      * "jean", "jeans", "denim" -> category: "Jeans"

    OCCASION & STYLE INFERENCE:
    - If the user asks for an occasion, vibe, or style (e.g. "office", "work", "gym", "party", "formal", "casual"), infer the primary catalog category that best matches that occasion and assign it to `category` (e.g., "Shirt" or "Trouser" for office/formal; "T-Shirt" or "Hoodie" for casual/gym).
    - If a specific item is not mentioned, prioritize inferring the most logical category over leaving it null.
    - Also capture the style term in `keyword` if applicable.

    CONTEXT RETENTION & ATTRIBUTE RULES:
    1. Short attribute queries like "Sizes?", "Sizes available?", "Colors?", "Price?", or "Options?" MUST be classified as intent='search' (NOT general or greeting) so inventory context is fetched.
    2. Maintain the `category` from previous turns ({active_category}) if no new category is mentioned.
    3. If the user sends greetings like "Hello?", "Hi", or "Hey" while an active session category exists ({active_category}), classify intent as 'search' and retain category='{active_category}' to keep context active instead of resetting.
    4. If the user asks general questions like "which colors are available", "what sizes do you have", or "show me more", DO NOT set `product_name` to a specific item unless explicitly named.
    5. Reset `price_max` to null on new queries unless a budget is explicitly requested.

    If the current shopping question refers to a previous product using words like "it", "this", "that", or "the product", infer the product_name from the previous conversation.
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
    structured_output = llm_strong.with_structured_output(ShoppingIntentModel)

    result = structured_output.invoke(
        [
            ("system", system_prompt),
            ("human", query)
        ]
    )

    # # Smart Fallback: Iff no category or produvt_name was matched, assign raw query to keyword
    # if not result.category and not result.product_name and result.intent in ["search", "recommend"]:
    #     clean_kw = query.lower().replace("show me", "").replace("do you have", "").strip()
    #     result.keyword = clean_kw

    return{
        "intent": result
    }



@traceable(name="Context Decision", description="Decide whether to search the database or answer using conversation context.")
def context_decision(state: ShoppingState):
    """
    DEcide whether o seacrh the database or answer using conversation context
    """
    # print(state)
    intent = state['intent'].intent

    if intent in (
        IntentType.SEARCH,
        IntentType.DETAILS,
        IntentType.COMPARE,
        IntentType.RECOMMEND
    ):
        return {
            "context_route": ContextRoute.SEARCH
        }
    return {
        "context_route": ContextRoute.CONTEXT
    }
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
    return state['context_route']


@traceable(name="Search Product", description="Query Supabase using the extracted shopping intent with a 2-Tier strategy and smart fallbacks.")
def search_product(state: ShoppingState) -> ShoppingState:
    """
    Query Supabase using the extracted shopping intent.
    Uses a 2-Tier strategy (Specific Product Name Search vs. General Category/Keyword Filtering)
    with smart fallbacks, plus a recommendation query for similar products.
    """
    
    
    # Extract the structured intent object from LangGraph state
    intent = state['intent']
    raw_query = state.get('query', '').lower()

    # STEP 1: SAFETY CHECK
    # Check if ANY usable search filter was extracted from the user's query.
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

    # If NO filter was extracted (e.g., user asked for "watches" or "belts" which aren't in our catalog),
    # stop immediately and return an empty list. This prevents pulling all 100 rows from the database.
    if not has_filter:
        print("Extracted Intent:", intent)
        print("Product Name:", intent.product_name)
        print("Category:", intent.category)
        print("Color:", intent.color)
        print("Size:", intent.size)
        print("Price Max:", intent.price_max)
        print("Products Found in DB: 0 (No Filters Extracted)")
        return {"products": [] , "similar_products": []}
    
    products = []

    # TIER 1: THE USER ASKED FOR A SPECIFIC PRODUCT BY NAME
    # Example: "Do you have CloudWarm Hoodie in Navy size XL?"
    if intent.product_name:
        # Start building a strict query for this specific product name
        # .ilike("name", "%...") performs a case-insensitive fuzzy match on the product name
        strict_query = (
            supabase.table("products")
            .select("*")
            .ilike("name", f"%{intent.product_name}%")
        )

        # If the user also specified a color, add a strict color filter
        if intent.color:
            strict_query = strict_query.ilike("color", intent.color.capitalize())  

        # If the user also specified a size, extract the raw string value (e.g. 'M') and add a size filter
        if intent.size:
            size_val = (
                intent.size.value
                if hasattr(intent.size, "value")
                else intent.size
            )
            strict_query = strict_query.eq("size", size_val)

        # Execute the strict query against Supabase
        products = strict_query.execute().data


        # --- FALLBACK 1: PRODUCT EXISTS, BUT NOT IN THAT COLOR OR SIZE ---
        # If strict search returned nothing (e.g. user asked for CloudWarm Hoodie in Navy/XL, 
        # but it only exists in Black/M), drop the color/size filters and fetch by NAME ALONE!
        if not products:
            products = (
                supabase
                .table("products")
                .select("*")
                .ilike("name", f"%{intent.product_name}%")
                .execute()
                .data
            )


        # --- FALLBACK 2: SEARCH OTHER PRODUCTS IN THE SAME CATEGORY OR KEYWORD---
        # If product name search failed completely, try finding alternative items in the same Category
        # matching the user's requested Color and/or Size!
        if not products and (intent.category or intent.keyword):
            alt_query = (
                supabase.table("products")
                .select("*")
            )
            if intent.category:
                alt_query = alt_query.eq("category", intent.category)
            elif intent.keyword:
                alt_query = alt_query.or_(f"name.ilike.%{intent.keyword}%,description.ilike.%{intent.keyword}%")

            # Match requested color if provided
            if intent.color:
                alt_query = alt_query.ilike("color", intent.color.capitalize())

            # Match requested size if provided
            if intent.size:
                size_val = (
                    intent.size.value
                    if hasattr(intent.size, "value")
                    else intent.size
                )
                alt_query = alt_query.eq("size", size_val)

            products = alt_query.execute().data

        # print("Extracted Intent:", intent)
        # print("Product Name:", intent.product_name)
        # print("Category:", intent.category)
        # print("Color:", intent.color)
        # print("Size:", intent.size)
        # print("Price Max:", intent.price_max)
        # print(f"Products Found in DB: {len(products)}")
        # return {"products": products}

    # TIER 2: GENERAL CATEGORY & ATTRIBUTE FILTERING
    # Used when user asks for general items like: "Show me black hoodies under 1500"
    else:
        # Base query: select all columns from products table
        query = supabase.table("products").select("*")

        #Filter by Category (exact match, e.g. category = 'Hoodie')
        if intent.category:
            query = query.eq("category", intent.category)
        elif intent.keyword:
            query = query.or_(f"name.ilike.%{intent.keyword}%,description.ilike.%{intent.keyword}%")

        # Filter by Color (case-insensitive match, e.g. color = 'Black')
        if intent.color:
            query = query.ilike("color", intent.color.capitalize())

        # Filter by Size (exact match on enum string value, e.g. size = 'M')
        if intent.size:
            # Extract raw string value from Enum if needed
            size_val = intent.size.value if hasattr(intent.size, "value") else intent.size
            query = query.eq("size", size_val)

        # Filter by Minimum Price (.gte = Greater Than or Equal to)
        if intent.price_min is not None:
            query = query.gte("price", intent.price_min)

        # Filter by Maximum Price (.lte = Less Than or Equal to)
        if intent.price_max is not None:
            query = query.lte("price", intent.price_max)



        # Execute the general category query
        products = query.execute().data


        #=====================================================================
        # --- SMART FALLBACK FOR ZERO MATCHES (e.g., "office" yielded 0 rows) ---
        if not products:
            # Case A: Budget or attribute exceeded on a specific Category (e.g. Hoodies under 500)
            # Fetch the cheapest items in THAT specific category!
            if intent.category:
                products = (
                    supabase.table("products")
                    .select("*")
                    .eq("category", intent.category)
                    .order("price", desc=False)
                    .limit(5)
                    .execute()
                    .data
                )
            else:
                # 1. Fetch distinct categories dynamically present in Supabase
                all_cats = supabase.table("products").select("category").execute().data
                distinct_categories = list(set(p.get("category") for p in all_cats if p.get("category")))
                # products = supabase.table("products").select("*").limit(15).execute().data

                # 2. Fetch top 5 items for every category in the DB
                balanced_products = []
                for cat in distinct_categories:
                    cat_items = (
                        supabase.table("products")
                        .select("*")
                        .eq("category", cat)
                        .limit(2)
                        .execute()
                        .data
                    )
                    balanced_products.extend(cat_items)
                products = balanced_products if balanced_products else supabase.table("products").select("*").limit(15).execute().data

            # Case B: Style/Vibe Keyword like "office" returned 0 exact DB matches
            # Fall back to fetching popular/formal items (Shirts / Trousers / Store items) so cards render!
            # Fallback safety net if table categories are missing
            if not products:
                products = supabase.table("products").select("*").limit(15).execute().data
       # =================================================================================

        # # --- FALLBACK: IF NO ITEMS FOUND UNDER PRICE BUDGET ---
        # # Fetch the cheapest items in that category ordered by price ascending!
        # # --- UNIVERSAL FALLBACK: IF NO MATCHES FOUND IN DB ---
        # if not products:
        #     # Case A: Budget exceeded or specific filter yielded 0 items -> Fetch cheapest in category/keyword
        #     if intent.price_max is not None or intent.color or intent.size:
        #         fallback_query = supabase.table("products").select("*").order("price", desc=False).limit(5)
        #         if intent.category:
        #             fallback_query = fallback_query.eq("category", intent.category)
        #         products = fallback_query.execute().data

        #     # Case B: Unlisted keyword like "dresses" returned 0 rows -> Fetch 5 popular store items so UI cards still render!
        #     if not products:
        #         print(f"No DB rows matched keyword '{intent.keyword}'. Fetching store featured fallback products...")
        #         products = supabase.table("products").select("*").limit(5).execute().data

    # RECOMMENDED / SIMILAR PRODUCTS QUERY
    # Fetch up to 4 other items in the same category (matching color/size if possible)
    # excluding the primary product SKUs so the UI carousel has relevant items to show.

    # DYNAMIC SORTING HANDLER (Processes LLM intent.sort field)
    sort_val = str(getattr(intent, 'sort', '') or '').lower()
    if ("price_asc" in sort_val or "asc" in sort_val) and products:
        products.sort(key=lambda x: float(x.get("price", float("inf"))))
    elif ("price_desc" in sort_val or "desc" in sort_val) and products:
        products.sort(key=lambda x: float(x.get("price", 0)), reverse=True)

    similar_products = []
    category_to_recommend = intent.category

    # If category wasn't in intent, infer it from the first primary product found
    if not category_to_recommend and products:
        category_to_recommend = products[0].get("category")

    if category_to_recommend:
        primary_skus = [p.get("sku") for p in products if p.get("sku")]

        rec_query = (
            supabase.table("products")
            .select("*")
            .eq("category", category_to_recommend)
        )

        # Exclude primary product SKUs from recommendations
        if primary_skus:
            rec_query = rec_query.not_.in_("sku", primary_skus)

        # Try mactching color if provided
        if intent.color:
            rec_query = rec_query.ilike("color", intent.color.capitalize()) 

        similar_products = rec_query.limit(5).execute().data

        # Fallback for similar products: If color match produced 0 recommendations, 
        # fetch from category alone (excluding primary SKUs)
        if not similar_products and primary_skus:
            similar_products = (
                supabase.table("products")
                .select("*")
                .eq("category", category_to_recommend)
                .not_.in_("sku", primary_skus)
                .limit(5)
                .execute()
                .data
            )     

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

@traceable(name="Generate Response", description="Convert structured product data into a natural language reply.")
def generate_response(state: ShoppingState) -> ShoppingState:
    """Convert structured product data into a natural language reply."""

    raw_intent = state.get("intent")

    # Safely extract intent string whether raw_intent is a Pydantic object or raw string
    if hasattr(raw_intent, "intent"):
        intent_type = raw_intent.intent
    else:
        intent_type = str(raw_intent)

    # Convert IntentType enum to string if needed for razorpay
    intent_str = str(intent_type.value if hasattr(intent_type, "value") else intent_type).lower()

    # Retrieve current products in memory
    products = state.get("products") or []
    similar_products = state.get("similar_products") or []
    payment_url = state.get("payment_url")
    
    # Dynamic Array Sorting Safeguard (Applies to ALL products before slicing)
    sort_val = str(getattr(raw_intent, 'sort', '') or '').lower()
    raw_query = state.get("query", "").lower()
    if ("price_asc" in sort_val or "asc" in sort_val or "cheap" in raw_query or "lowest" in raw_query) and products:
        products = sorted(products, key=lambda x: float(x.get("price", float("inf"))))
    elif ("price_desc" in sort_val or "desc" in sort_val or "expensive" in raw_query or "highest" in raw_query) and products:
        products = sorted(products, key=lambda x: float(x.get("price", 0)), reverse=True)

    selected_product = state.get("selected_product") or (products[0] if products else None)

    # 1. SPECIAL CHECKOUT RESPONSE HANDLER
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
            "displayed_products": [selected_product] if selected_product else products[:1],
            "similar_products": [],
            "products": products,
            "payment_url": payment_url,
            "selected_product": selected_product
        }
    # 2. STANDARD SHOPPING / CONTEXT RESPONSE HANDLER
    # 1. Decide what to display in UI cards for THIS specific turn
    # If the user is just saying hi/hello, don't show UI cards on screen, but keep products in memory!
    if intent_type in ["greeting", "general", "out_of_scope"]:
        api_displayed_products = []
        api_similar_products = []
    else:
        # 1. Full data payload for Frontend / Popups / API response
        api_displayed_products = products
        api_similar_products = similar_products[:5]

    # --- ALL PRODUCTS INCLUDED (2-ITEM LIMIT REMOVED) ---
    prompt_products = []
    for p in products[:5]:   # Capped at 5 ...
        desc = p.get("description") or ""
        short_desc = (desc[:60] + "...") if len(desc) > 60 else desc

        prompt_products.append({
            "category": p.get("category"),
            "name": p.get("name"),
            "price": f"₹{p.get('price')}",
            "color": p.get("color"),
            "size": p.get("size"),
            "details": short_desc,
            "url": p.get("product_url")
        })

    # Global Metadata Summaries (Loops across ALL products in memory for 100% attribute accuracy)
    distinct_categories = sorted(list(set(str(p.get("category")) for p in products if p.get("category"))))
    categories_str = ", ".join(distinct_categories) if distinct_categories else "our collection"

    distinct_colors = sorted(list(set(p.get("color").title() for p in products if p.get("color"))))
    colors_summary = ", ".join(distinct_colors) if distinct_colors else "Various colors available"

    distinct_sizes = sorted(list(set(str(p.get("size")) for p in products if p.get("size"))))
    sizes_summary = ", ".join(distinct_sizes) if distinct_sizes else "Various sizes available"

    prompt = f"""
    Customer Query:
    {state["query"]}

    Shopping Intent:
    {intent_str}

    Available Product Categories in Store:
    {categories_str}

    All Available Colors for These Items in Stock:
    {colors_summary}

    All Available Sizes in Stock:
    {sizes_summary}

    Top Products in Context (Pre-Sorted):
    {prompt_products if prompt_products else "None"}

    RESPONSE INSTRUCTIONS:
    - Respond directly to the customer's query using the context provided above.
    - If the customer asks strictly about COLORS, state ONLY the available colors ({colors_summary}). DO NOT list sizes unless asked.
    - If the customer asks strictly about SIZES, state ONLY the available sizes ({sizes_summary}). DO NOT list colors unless asked.
    - If the customer asks for the cheapest or lowest priced item, quote the VERY FIRST product from 'Top Products in Context' (index 0).
    - Keep the text concise, friendly, and helpful (2-3 sentences max).
    """

    response = llm_strong.invoke(
        [
            ("system", RESPONSE_PROMPT),
            ("human", prompt)
        ]
    )

    return {
        "response": response.content,
        "displayed_products": api_displayed_products, # Sent to FastAPI for primary cards
        "similar_products": api_similar_products,     # Sent to FastAPI for "You might also like"
        "products": products,  
        "payment_url": payment_url,
        "selected_product": selected_product                        # Keeps primary products in LangGraph state
    }


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
                    return col
    except Exception as e:
        print(f"[Schema Fetch Warning]: {e}")
        
    return "sku"  # manual fallback if schema inspection fails

def create_checkout_session(state: ShoppingState) -> ShoppingState:
    """
    DETERMINISTIC CHECKOUT NODE:
    1. Checks extracted intent for newly requested product_name.
    2. Dynamically queries primary key via get_table_primary_key().
    3. Verifies actual price and stock directly from Supabase (ground truth).
    4. Calls Razorpay API to generate a real Payment Link.
    """
    products = state.get("products") or []
    intent = state.get("intent")

    # Extract requested product name from the newly extracted intent
    req_name = getattr(intent, "product_name", None) if intent else None
    target_product = None

    # 1. First priority: Search DB directly if a specific product_name was extracted in checkout intent
    if req_name:
        try:
            db_res = supabase.table("products").select("*").ilike("name", f"%{req_name}%").limit(1).execute()
            if db_res and db_res.data:
                target_product = db_res.data[0]
        except Exception as e:
            print(f"[Checkout Intent Name Search Error]: {e}")

    # 2. Second priority: Check if any item in current products memory matches req_name
    if not target_product and req_name and products:
        for p in products:
            if req_name.lower() in p.get("name", "").lower():
                target_product = p
                break

    # 3. Fallback: Use state's existing selected_product or first product in memory
    if not target_product:
        target_product = state.get("selected_product") or (products[0] if products else None)

    if not target_product:
        return {
            "response": "Sorry, I couldn't find an item in our conversation to checkout. Which item would you like to buy?",
            "payment_url": None,
            "products": products
        }

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

    # Safe stock check (handles string values from DB)
    raw_stock = db_product.get("stock", 0)
    try:
        stock_count = int(raw_stock) if raw_stock is not None else 0
    except (ValueError, TypeError):
        stock_count = 0

    if not db_product or stock_count <= 0:
        return {
            "response": f"Sorry, **{target_product.get('name', 'this item')}** is currently out of stock.",
            "payment_url": None,
            "products": products
        }

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

        return {
            "payment_url": payment_url,
            "selected_product": db_product,
            "products": products
        }

    except Exception as e:
        print(f"Razorpay API Error: {e}")
        fallback_url = db_product.get("payment_link") or "#"
        return {
            "payment_url": fallback_url if fallback_url != "#" else None,
            "selected_product": db_product,
            "products": products
        }

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
        return "create_checkout_session"
    
    return "search_products"

# Graph
graph = StateGraph(ShoppingState)

graph.add_node("router", router)
graph.add_node("general_chat", general_chat)
graph.add_node("extract_intent", extract_intent)
graph.add_node("context_decision", context_decision)
graph.add_node("search_products", search_product)
graph.add_node("create_checkout_session", create_checkout_session)
graph.add_node("generate_response", generate_response)

graph.add_edge(START, "router")

graph.add_conditional_edges(
    "router",
    decide_route,
    {
        RouteType.SHOPPING: "extract_intent",
        RouteType.GENERAL: "general_chat",
    },
)
# Extract Intent Edge -> Checkout vs Standard Flow
graph.add_conditional_edges(
    "extract_intent",
    route_after_intent,
    {
        "create_checkout_session": "create_checkout_session",
        "search_products": "context_decision",
    }
)

# Context Decision Edge
graph.add_conditional_edges(
    "context_decision",
    decide_context,
    {
        ContextRoute.SEARCH: "search_products",
        ContextRoute.CONTEXT: "generate_response",
    },
)


graph.add_edge("search_products", "generate_response")
graph.add_edge("create_checkout_session", "generate_response")
graph.add_edge("general_chat", END)
graph.add_edge("generate_response", END)


memory = InMemorySaver()
workflow = graph.compile(checkpointer=memory)
# workflow
workflow.get_graph().draw_mermaid()