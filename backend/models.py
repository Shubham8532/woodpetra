from typing import List, Optional, TypedDict
from enum import Enum
from pydantic import BaseModel, Field, field_validator

class RouteType(str, Enum):
    SHOPPING = "shopping"
    GENERAL = "general"


class ContextRoute(str, Enum):
    # Where should I get information from?
    SEARCH = "search"
    CONTEXT = "context"


class IntentType(str, Enum):
    SEARCH = "search"
    COMPARE = "compare"
    DETAILS = "details"
    RECOMMEND = "recommend"
    CHECKOUT = "checkout"


class SizeOption(str, Enum):
    XS = "XS"
    S = "S"
    M = "M"
    L = "L"
    XL = "XL"
    XXL = "XXL"


class GenderOption(str, Enum):
    MALE = "male"
    FEMALE = "female"
    UNISEX = "unisex"


class SortOption(str, Enum):
    PRICE_ASC = "price_asc"
    PRICE_DESC = "price_desc"
    NEWEST = "newest"
    POPULAR = "popular"


class RouterModel(BaseModel):
    """
    Decide whether the query is a shopping query or a general query.
    """
    route: RouteType = Field(..., description="The route type for the query")


class ShoppingIntentModel(BaseModel):

    intent: IntentType = Field(..., description="Intent type for the shopping query")
    keyword: Optional[str] = Field(None, description="Raw search keywords or category names when explicit category is unlisted or null (e.g. 'dresses', 'polo', 'skirts').")
    category: Optional[str] = Field(None, description="Category of the shopping item")
    product_name: Optional[str] = Field(None, description="Name of the product")
    color: Optional[str] = Field(None, description="Color of the product")
    material: Optional[str] = Field(None, description="Material of the product")
    size: Optional[SizeOption] = Field(None, description="Size of the product")
    fit: Optional[str] = Field(None,description="Fit of the clothing such as Slim Fit, Regular Fit, Oversized, Relaxed Fit") 
    brands: Optional[List[str]] = Field(None, description="List of preferred brands for the product")
    gender: Optional[GenderOption] = Field(None, description="Target gender of the product")
    # price_range: Optional[str] = Field(None, description="Price range of the product")
    price_min: Optional[int] = Field(None, description="Minimum price of the product")
    price_max: Optional[int] = Field(None, description="Maximum price of the product")
    sort: Optional[SortOption] = Field(None, description="Sorting preference for the product")
    occasion: Optional[str] = Field(None, description="Occasion for the product")

# ==========================================================
# ADDITION FOR 8B MODEL COMPATIBILITY:
# 8B models sometimes output string "null" / "None" instead of JSON null.
# This pre-validator converts string "null" into Python None before Pydantic checks types.
# Works seamlessly for both 8B and 70B models.

# @field_validator("*", mode="before")
# def sanitize_string_nulls(cls, value):
#     if isinstance(value, str) and value.strip().lower() in ["null", "none", ""]:
#         return None
#     return value

#==================================================================

class ShoppingState(TypedDict):
    query: str = Field(..., description="User's shopping query")
    route: RouteType | None = Field(None, description="ROUTER_PROMPT result")
    context_route: ContextRoute = Field(..., description="Where to get information from: search or context")
    intent: ShoppingIntentModel | None = Field(None, description="Extracted shopping intent from the query")
    products: List[dict] | None = Field(None, description="List of products matching the shopping intent")
    similar_products: List[dict] | None = Field(None, description="List of similar products for recommendations")
    selected_product: Optional[dict] = Field(None, description="The product selected by the user for details or checkout")
    payment_url: Optional[str] = Field(None, description="Payment URL for checkout if applicable")
    response: str | None = Field(None, description="Response to the user based on the shopping intent and products")
    displayed_products: List[dict] | None = Field(None, description="List of products to be displayed to the user in popup")