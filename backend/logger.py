from enum import Enum
import time
from functools import wraps
from datetime import datetime
from pathlib import Path

############# HELPER COLOR for LOGGING #####################
# terminal colors
RESET = "\033[0m"

HEADER_COLOR = "\033[96m"       # Cyan
FLOW_COLOR = "\033[93m"       # Yellow

def log_header(title):
    print(HEADER_COLOR)
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80 + RESET)


def log_flow(text):
    print(FLOW_COLOR + text + RESET)
################################################

##################### Decorator for timing graph nodes #####################
def timed_node(name=None):
    """
    Measure execution time of a graph node.
    Logging failures must never affect node execution.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start = time.perf_counter()

            try:
                return func(*args, **kwargs)

            finally:
                elapsed = time.perf_counter() - start
                node_name = name or func.__name__

                try:
                    print(FLOW_COLOR + f"[NODE TIMER] {node_name:<25} {elapsed:.2f}s" + RESET)
                except Exception:
                    pass

        return wrapper

    return decorator
################################################

######################## Logging for debugging ##############

def log_router_state(query, last_bot_action, result):
    route = result.route.value

    # print(ROUTER_COLOR)

    # print("\n" + "=" * 80)
    # print("ROUTER")
    # print("=" * 80)
    log_header("ROUTER")

    print("\nINPUT")
    print("-" * 80)
    print(f"| {'Field':<20} | {'Value':<52} |")
    print(f"|{'-' * 22}|{'-' * 54}|")
    print(f"| {'query':<20} | {str(query):<52} |")
    print(f"| {'last_bot_action':<20} | {str(last_bot_action):<52} |")

    print("\nFLOW")
    print("-" * 80)

    # log_flow(
    #     f"""
    #         ┌──────────────────────────────────────────────┐
    #         │ USER QUERY                                   │
    #         │ {str(query):<44} │
    #         └──────────────────────┬───────────────────────┘
    #                             │
    #                             ▼
    #         ┌──────────────────────────────────────────────┐
    #         │ ROUTER                                       │
    #         │ query + last_bot_action                      │
    #         └──────────────────────┬───────────────────────┘
    #                             │
    #                         route = {route}
    #                             │
    #                             ▼
    #         ┌──────────────────────────────────────────────┐
    #         │ {route.upper() + " WORKFLOW":<44} │
    #         └──────────────────────────────────────────────┘
    #         """
    # )

    print("=" * 80)

    print(RESET)


##############################################


######################## Logging for debugging (load_history()) ########################


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

        # -------------------------------------------------
        f.write("\nRECENT SNAPSHOTS RAW\n")
        f.write("-" * 80 + "\n")

        for i, snapshot in enumerate(recent_snapshots, 1):
            values = snapshot.values

            f.write(f"\nSNAPSHOT {i}\n")
            f.write(f"  query: {values.get('query')}\n")
            f.write(f"  response: {values.get('response')}\n")

            # Useful for identifying which node/checkpoint created this snapshot
            f.write(f"  config: {getattr(snapshot, 'config', None)}\n")
            f.write(f"  metadata: {getattr(snapshot, 'metadata', None)}\n")

        #-----------------------------------------
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


##############  LOGGING (general_chat)  ##############
def log_general_chat_llm_context(
    query,
    history,
    history_text,
    prompt,
    system_prompt
):
    # print("\n" + "=" * 80)
    # print("GENERAL CHAT — LLM CONTEXT")
    # print("=" * 80)
    log_header("GENERAL CHAT — LLM CONTEXT")

    print("\nCURRENT QUERY")
    print("-" * 80)
    print(query)

    print("\nHISTORY RECORDS")
    print("-" * 80)
    print(f"Records from load_history : {len(history)}")

    print("\nCOMPACT HISTORY")
    print("-" * 80)
    print(history_text if history_text else "No conversation history.")

    # print("\nFINAL HUMAN PROMPT")
    # print("-" * 80)
    # print(prompt)

    # print("\nSYSTEM PROMPT")
    # print("-" * 80)
    # print(system_prompt)

    print("\nPROMPT SIZE")
    print("-" * 80)
    print(f"History characters : {len(history_text)}")
    print(f"Human prompt chars : {len(prompt)}")
    print(f"System prompt chars: {len(system_prompt)}")

    print("=" * 80)

###########################


############# LOGGING (build_conversation) ########################
def log_build_conversation_state(
    history,
    max_turns,
    history_text,
    active_category
):
    # print("\n" + "=" * 80)
    # print("BUILD CONVERSATION")
    # print("=" * 80)
    log_header("BUILD CONVERSATION")

    print("\nINPUT")
    print("-" * 80)
    print(f"History records received : {len(history)}")
    print(f"Max turns                : {max_turns}")

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


######################## TEMPORARY --> build_conversation --> detail report ###############
def log_build_conversation_raw(history, conversation, history_text):
    with open("log_build_conversation.txt", "a", encoding="utf-8") as f:
        f.write("\n" + "=" * 100 + "\n")
        f.write("BUILD CONVERSATION - RAW DEBUG\n")
        f.write("=" * 100 + "\n")

        f.write("\nRAW HISTORY\n")
        f.write("-" * 100 + "\n")

        for i, item in enumerate(history, 1):
            f.write(f"\n--- HISTORY ITEM {i} ---\n")
            f.write(f"{item}\n")

        f.write("\nCONVERSATION ARRAY\n")
        f.write("-" * 100 + "\n")

        for i, item in enumerate(conversation, 1):
            f.write(f"\n--- CONVERSATION ITEM {i} ---\n")
            f.write(f"{item}\n")

        f.write("\nFINAL HISTORY TEXT\n")
        f.write("-" * 100 + "\n")
        f.write(history_text if history_text else "No conversation history.")

        f.write("\n" + "=" * 100 + "\n")
###########################################

######################## Logging for debugging ##############

def log_intent_state(
    query,
    active_category,
    result,
    turn_slots_dict,
    previous_turn_slots
):
    # print("\n" + "=" * 80)
    # print("EXTRACT INTENT")
    # print("=" * 80)
    log_header("EXTRACT INTENT")

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

######### Debugging: Context Decision Logging ########

def log_context_decision_state(intent, context_route):

    route = context_route.value

    if route == "search":
        next_branch = "EXTRACT INTENT"
    else:
        next_branch = "CONTEXT BRANCH"

    # print("\n" + "=" * 80)
    # print("CONTEXT DECISION")
    # print("=" * 80)
    log_header("CONTEXT DECISION")

    print("\nINPUT")
    print("-" * 80)
    print(f"| {'Field':<20} | {'Value':<52} |")
    print(f"|{'-' * 22}|{'-' * 54}|")
    print(f"| {'intent':<20} | {str(intent):<52} |")

    print("\nFLOW")
    print("-" * 80)

    # log_flow(
    #     f"""
    #     ┌──────────────────────────────────────────────┐
    #     │ SHOPPING WORKFLOW                            │
    #     └──────────────────────┬───────────────────────┘
    #                            │
    #                            ▼
    #     ┌──────────────────────────────────────────────┐
    #     │ CONTEXT DECISION                             │
    #     │                                              │
    #     │ intent = {str(intent):<32} │
    #     └──────────────────────┬───────────────────────┘
    #                            │
    #                            ▼
    #     ┌──────────────────────────────────────────────┐
    #     │ CONTEXT ROUTE                                │
    #     │                                              │
    #     │ route = {route:<35} │
    #     ⚠️ CURRENT ARCHITECTURE — context_route may be invalid
    #     └──────────────────────┬───────────────────────┘
    #                            │
    #                            ▼
    #     ┌──────────────────────────────────────────────┐
    #     │ NEXT STEP                                    │
    #     │                                              │
    #     │ {next_branch:<44} │
    #     └──────────────────────────────────────────────┘
    #     """
    # )

    print("\nOUTPUT")
    print("-" * 80)
    print(f"| {'Field':<20} | {'Value':<52} |")
    print(f"|{'-' * 22}|{'-' * 54}|")
    print(f"| {'context_route':<20} | {route:<52} |")

    print("=" * 80)

##############################


########################## LOGGING (search_product) ##########################


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

# ============================================================
# HUMAN-READABLE TERMINAL LOGGER
# ============================================================

def terminal_search_log(message=""):
    """
    Human-readable terminal logging only.

    This is intentionally separate from developer logging
    written to retrieved_products.txt.
    """
    try:
        print(message)
    except Exception:
        pass

def terminal_search_header(query):
    try:
        print()
        # print("═" * 80)
        # print("SEARCH PRODUCT")
        # print("═" * 80)
        log_header("SEARCH PRODUCT")

        print(f"Query : {query}")

    except Exception:
        pass


def terminal_search_intent(intent):
    try:
        intent_type = getattr(intent, "intent", None)
        category = getattr(intent, "category", None)

        filters = []

        if getattr(intent, "product_name", None):
            filters.append(f"product={intent.product_name}")

        if getattr(intent, "keyword", None):
            filters.append(f"keyword={intent.keyword}")

        if getattr(intent, "color", None):
            filters.append(f"color={intent.color}")

        if getattr(intent, "size", None):
            size = (
                intent.size.value
                if hasattr(intent.size, "value")
                else intent.size
            )
            filters.append(f"size={size}")

        if getattr(intent, "price_min", None) is not None:
            filters.append(f"min=₹{intent.price_min}")

        if getattr(intent, "price_max", None) is not None:
            filters.append(f"max=₹{intent.price_max}")

        print()
        print("INTENT")
        print(f"  Type     : {intent_type}")
        print(f"  Category : {category}")
        print(
            f"  Filters  : "
            f"{', '.join(filters) if filters else 'none'}"
        )

    except Exception:
        pass


def terminal_search_path_start():
    try:
        print()
        print("SEARCH PATH")
    except Exception:
        pass


def terminal_search_path(
    name,
    why,
    result_count=None,
    extra=None
):
    try:
        print()
        print(f"  → {name}")
        print(f"      Why    : {why}")

        if extra:
            print(f"      Detail : {extra}")

        if result_count is not None:
            print(f"      Result : {result_count}")

    except Exception:
        pass


def terminal_sort_log(sort_pref, products_count):
    try:
        print()
        print("SORT")

        if not products_count:
            print("  → No products available for sorting")
            return

        sort_val = str(sort_pref if sort_pref else "").lower()

        if "price_desc" in sort_val or "desc" in sort_val:
            print("  → Price descending")
        else:
            print("  → Price ascending (default)")

    except Exception:
        pass


def terminal_similar_start(category):
    try:
        print()
        print("SIMILAR PRODUCTS")

        if category:
            print(f"  Category : {category}")
        else:
            print("  Category : none")

    except Exception:
        pass


def terminal_similar_step(name, why, result_count):
    try:
        print(f"  → {name}")
        print(f"      Why    : {why}")
        print(f"      Result : {result_count}")
    except Exception:
        pass


def terminal_search_result(
    products_count,
    similar_count,
    elapsed_ms
):
    try:
        print()
        print("RESULT")
        print(f"  Products returned : {products_count}")
        print(f"  Similar products  : {similar_count}")

        print()
        print(
            f"✓ SEARCH COMPLETE | "
            f"{elapsed_ms:.1f} ms"
        )

        print("═" * 80)

    except Exception:
        pass
#######################################################


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
    # print("\n" + "=" * 100)
    # print("GENERATE RESPONSE")
    # print("=" * 100)
    log_header("GENERATE RESPONSE")

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
    # print("\n" + "=" * 100)
    # print("CREATE CHECKOUT SESSION")
    # print("=" * 100)
    log_header("CREATE CHECKOUT SESSION")

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


##################### LOGGING --> route_after_intent #####################
def log_route_after_intent(
    intent_val,
    next_node
):
    # print("\n" + "=" * 80)
    # print("ROUTE AFTER INTENT")
    # print("=" * 80)
    log_header("ROUTE AFTER INTENT")

    print("INPUT")
    print("-" * 80)
    print(f"Intent                 : {intent_val or 'None'}")

    print("\nROUTING DECISION")
    print("-" * 80)
    print(f"Next node              : {next_node}")

    print("\nROUTE AFTER INTENT COMPLETE")
    print("=" * 80)
##########################


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


######################### LOGGING & DEBUGGING #########################

# 1. route_post_sync logging
def log_route_post_sync_state(route, next_node):

    route = getattr(route, "value", route)

    # print("\n" + "=" * 80)
    # print("ROUTE POST SYNC")
    # print("=" * 80)
    log_header("ROUTE POST SYNC")

    print("\nINPUT")
    print("-" * 80)
    print(f"| {'Field':<20} | {'Value':<52} |")
    print(f"|{'-' * 22}|{'-' * 54}|")
    print(f"| {'route':<20} | {str(route):<52} |")

    print("\nFLOW")
    print("-" * 80)

    # log_flow(
    #     f"""
    #     ┌──────────────────────────────────────────────┐
    #     │ ROUTER                                       │
    #     │                                              │
    #     │ route = {str(route):<34} │
    #     └──────────────────────┬───────────────────────┘
    #                            │
    #                            ▼
    #     ┌──────────────────────────────────────────────┐
    #     │ ROUTE POST SYNC                              │
    #     │                                              │
    #     │ Check router route                           │
    #     └──────────────────────┬───────────────────────┘
    #                            │
    #                            ▼
    #     ┌──────────────────────────────────────────────┐
    #     │ NEXT NODE                                    │
    #     │                                              │
    #     │ {next_node:<44} │
    #     └──────────────────────────────────────────────┘
    #     """
    # )

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

    # print("\n" + "=" * 80)
    # print("ROUTE AFTER INTENT")
    # print("=" * 80)
    log_header("ROUTE AFTER INTENT")

    print("\nINPUT")
    print("-" * 80)
    print(f"| {'Field':<25} | {'Value':<47} |")
    print(f"|{'-' * 27}|{'-' * 49}|")
    print(f"| {'intent':<25} | {intent_str:<47} |")
    print(f"| {'last_bot_action':<25} | {str(last_action):<47} |")
    print(f"| {'has_specific_filters':<25} | {str(has_specific_filters):<47} |")

    print("\nFLOW")
    print("-" * 80)

    # log_flow(
    #     f"""
    #     ┌──────────────────────────────────────────────┐
    #     │ EXTRACT INTENT                               │
    #     │                                              │
    #     │ intent = {intent_str:<32} │
    #     └──────────────────────┬───────────────────────┘
    #                            │
    #                            ▼
    #     ┌──────────────────────────────────────────────┐
    #     │ ROUTE AFTER INTENT                            │
    #     │                                              │
    #     │ Check intent + filters + last action         │
    #     └──────────────────────┬───────────────────────┘
    #                            │
    #                            ▼
    #     ┌──────────────────────────────────────────────┐
    #     │ NEXT NODE                                    │
    #     │                                              │
    #     │ {next_node:<44} │
    #     └──────────────────────────────────────────────┘
    #     """
    # )

    print("\nOUTPUT")
    print("-" * 80)
    print(f"| {'Field':<25} | {'Value':<47} |")
    print(f"|{'-' * 27}|{'-' * 49}|")
    print(f"| {'next_node':<25} | {next_node:<47} |")

    print("=" * 80)

#################################################

