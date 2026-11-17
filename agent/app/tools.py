import os
import httpx

STORE_API_URL = os.environ.get("STORE_API_URL", "http://store-api:8000")
SEARCH_LIMIT = 10
ORDER_STATUSES = ["pending", "processing", "shipped", "delivered", "cancelled"]

TOOLS = [
    {
        "name": "list_orders",
        "description": "List the current customer's orders, newest first. Each order has its order number, "
                       "date, status, total and item names. Use this when the customer asks about their orders "
                       "in general or doesn't give an order number. Optionally filter by status.",
        "input_schema":
            {
                "type": "object", "properties": {"status": {"type": "string", "enum": ORDER_STATUSES}},
            }
    },

    {
        "name": "get_order",
        "description": "Get the full details of one of the current customer's orders: items, total, payment "
                       "status, shipping address, and shipment (carrier, tracking number, estimated or actual "
                       "delivery date). Use it for any question about a specific order, including where it is. "
                       "If it returns not found, the order does not exist for this customer; say so and don't guess ",
        "input_schema":
            {
                "type": "object",
                "properties": {"order_id": {"type": "integer", "description": "The order number, e.g. 1005" }},
                "required": ["order_id"]
            }
    },

    {
        "name":"search_products",
        "description": f"Search the store catalog. Return a list of up to {SEARCH_LIMIT} products with id, name, "
                        "category, price, rating, and whether it is in stock. Use it for product questions and "
                        "recommendations. Only mention products this tool returned; never invent products or "
                        "prices. If the search term is not found, return an empty list.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search term to match in the product name or brand, e.g. 'coffee mugs'"},
                "category": {"type": "string", "description": "The exact category name, e.g. 'Small Appliances'"},
                "max_price": {"type": "number", "description": "The maximum price in Canadian dollars (CAD)"},

                "in_stock": {"type": "boolean", "description": "Whether the product is in stock"},
            },
        }
    },

    {
        "name": "get_product",
        "description": "Get the full details of one product by its id: description, brand, color, material, "
                       "dimensions, price, rating and stock. Use it when the customer asks about a specific "
                       "product's features or size. Get the id from search_products or from an order.",
        "input_schema": {
            "type": "object",
            "properties": {"product_id": {"type": "integer", "description": "The product id, e.g. 1005" }},
            "required": ["product_id"]
        }
    }
]


class ToolError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.message = message
        self.code = code


def _get(path, params=None, not_found="Not Found!"):
    try:
        response = httpx.get(f"{STORE_API_URL}{path}", params=params, timeout=10)
    except httpx.HTTPError:
        raise ToolError("service_error", "The store system is not reachable right now.")
    if response.status_code == 404:
        raise ToolError("not_found", not_found)
    if response.status_code == 422:
        raise ToolError("invalid_input", "The store rejected these arguments.")
    if response.status_code != 200:
        raise ToolError("service_error", "The store system returned an error.")
    return response.json()


def _item(item):
    return {
        "product_id": item["product"]["id"],
        "name": item["product"]["name"],
        "quantity": item["quantity"],
        "unit_price": item["unit_price"]
    }


def list_orders(customer_id, status=None):
    orders = _get(f"/customers/{customer_id}/orders", {"status": status} if status else None)
    Os = []
    for o in orders:
        Os.append({
            "order_id": o["order_id"],
            "date": o["order_date"][:10],
            "status": o["status"],
            "total": o["total_amount"],
            "items": [f"{i['quantity']} X {i['product']['name']}" for i in o["items"]]
        })
    return Os

def get_order(customer_id, order_id):
    order_id = _whole_number(order_id, "order_id")
    order = _get(f"/customers/{customer_id}/orders/{order_id}",
             not_found=f"No order {order_id} was found for this customer.")
    payment, shipment = order["payment"], order["shipment"]
    return {
        "order_id": order["order_id"],
        "date": order["order_date"][:10],
        "status": order["status"],
        "total": order["total_amount"],
        "shipping_address": order["shipping_address"],
        "items": [_item(i) for i in order["items"]],
        "payment": payment and {"method": payment["payment_method"], "status": payment["status"]},
        "shipment": shipment and {k: shipment[k] for k in
                                  ("carrier", "status", "tracking_number", "shipped_at",
                                   "estimated_delivery", "delivered_at")},
    }

def search_products(customer_id, query=None, category=None, max_price=None, in_stock=None):
    params = {
        "limit": SEARCH_LIMIT,
        "q": query,
        "category": category,
        "max_price": max_price,
    }
    products = _get("/products", {k: v for k, v in params.items() if v is not None})
    if in_stock:
        products = [p for p in products if p["stock_quantity"] > 0]
    Ps = []
    for p in products:
        Ps.append({
            "product_id": p["id"],
            "name": p["name"],
            "category": p["category"],
            "price": p["price"],
            "rating": p["rating"],
            "in_stock": p["stock_quantity"] > 0
        })
    return Ps

def get_product(customer_id, product_id):
    product_id = _whole_number(product_id, "product_id")
    p = _get(f"/products/{product_id}", not_found=f"No product {product_id} was found.")
    return {
        "product_id": p["id"],
        "name": p["name"],
        "brand": p["brand"],
        "category": p["category"],
        "price": p["price"],
        "rating": p["rating"],
        "rating_count": p["rating_count"],
        "in_stock": p["stock_quantity"] > 0,
        "color": p["color"],
        "material": p["material"],
        "dimensions_cm": {"width": p["width_cm"], "depth": p["depth_cm"], "height": p["height_cm"]},
        "description": (p["description"] or "")[:1500],
    }


HANDLERS = {"list_orders": list_orders, "get_order": get_order, "search_products": search_products, "get_product": get_product}
def _whole_number(value, name):
    # the schema asks for an integer, but the model's output is untrusted: enforce it here
    if not isinstance(value, int) or isinstance(value, bool):
        raise ToolError("invalid_input", f"{name} must be a whole number.")
    return value

def run_tool(tool_name, customer_id, args):
    """Run one tool call from Claude. Returns (result, is_error) and never raises."""
    handler = HANDLERS.get(tool_name)
    if handler is None:
        return {"error": "invalid_input", "message": f"Tool {tool_name} is not supported."}, True
    try:
        return handler(customer_id, **args), False
    except ToolError as e:
        return {"error": e.code, "message": e.message}, True
    except TypeError:
        # unexpected arguments, e.g. the model trying to pass its own customer_id
        return {"error": "invalid_input", "message": "Wrong arguments for this tool."}, True

