"""
Upwardor Portal API Client
API Base: http://195.35.8.196:6100
"""

import requests
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
import logging
import time

logger = logging.getLogger(__name__)


class UpwardorAPIError(Exception):
    pass


class UpwardorAPIClient:

    def __init__(self, base_url: str = "http://195.35.8.196:6100"):
        self.base_url = base_url
        self.session = requests.Session()
        self.access_token: Optional[str] = None
        self.token_expiry: Optional[datetime] = None
        self.user_data: Optional[Dict[str, Any]] = None

    def _get_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        return headers

    def login(self, email: str, password: str) -> Dict[str, Any]:
        url = f"{self.base_url}/user/login"
        response = self.session.post(url, json={"email": email, "password": password}, timeout=15)
        if response.status_code != 200:
            raise UpwardorAPIError(f"Login failed: {response.status_code}")
        result = response.json()
        if not result.get("success"):
            raise UpwardorAPIError(f"Login failed: {result.get('message')}")
        data = result.get("data", {})
        self.access_token = data.get("access_token")
        self.user_data = data
        self.token_expiry = datetime.now() + timedelta(days=7)
        logger.info(f"Logged in as {email}")
        return data

    def ensure_authenticated(self):
        if not self.access_token:
            raise UpwardorAPIError("Not authenticated")

    def get_categories(self, status: str = "active") -> List[Dict[str, Any]]:
        self.ensure_authenticated()
        response = self.session.get(f"{self.base_url}/category/listing", params={"status": status}, headers=self._get_headers(), timeout=15)
        result = response.json()
        return result.get("data", {}).get("result", []) if result.get("success") else []

    def calculate_panel_quantity(self, door_height: int) -> Dict[str, int]:
        self.ensure_authenticated()
        response = self.session.post(f"{self.base_url}/quote/panel/quantity", json={"doorHeight": str(door_height)}, headers=self._get_headers(), timeout=15)
        result = response.json()
        return result.get("data", {}) if result.get("success") else {}

    def calculate_struts_quantity(self, door_width: int, door_height: int = 0, window: str = "", door_type: str = "RESI") -> int:
        self.ensure_authenticated()
        response = self.session.post(f"{self.base_url}/quote/struts/quantity", json={"doorWidth": door_width, "doorHeight": door_height, "window": window, "type": door_type}, headers=self._get_headers(), timeout=15)
        result = response.json()
        return result.get("data", 0) if result.get("success") else 0

    def generate_quote(self, quote_config: Dict[str, Any]) -> Dict[str, Any]:
        self.ensure_authenticated()
        response = self.session.post(f"{self.base_url}/quote/generate", json=quote_config, headers=self._get_headers(), timeout=30)
        result = response.json()
        if not result.get("success"):
            raise UpwardorAPIError(f"Quote generation failed: {result.get('error', {}).get('message')}")
        return result.get("data", {})

    def get_quotes(self, page: int = 1, count: int = 10) -> Dict[str, Any]:
        self.ensure_authenticated()
        response = self.session.get(f"{self.base_url}/quote/group", params={"page": page, "count": count, "convertedToOrder": "false", "isExpired": "false"}, headers=self._get_headers(), timeout=15)
        return response.json()

    def build_door_config(self, door_width: int, door_height: int, panel_color: str = "WHITE", stamp_pattern: str = "SHXL", track_radius: str = "15", **kwargs) -> Dict[str, Any]:
        config = {
            "categoryType": "residential", "categoryValue": "678f8f79088796816d501456",
            "customerId": self.user_data.get("_id") if self.user_data else None,
            "doorCount": 1, "doorWidth": door_width, "doorHeight": door_height,
            "stampPattern": stamp_pattern, "panelColor": panel_color,
            "window": "no", "tracks": "yes", "trackRadius": track_radius,
            "trackThickness": "2 INCH TRACK", "trackType": "STANDARD LIFT BRACKET MOUNT",
            "shafts": "yes", "springs": "yes", "structs": "yes",
            "hardwareKits": "yes", "weatherStripping": "yes", "bottomRetainer": "yes",
            "wrapping": "yes", "angleConfrigation": "BRACKET TO WOOD", "isDoorRequiredStruts": True,
            "isBulk": "no", "insert": "no", "extraStrut": "no", "topRubber": "no",
            "decorativeHardWareParts": "no", "trackRequest": "NO",
        }
        config.update(kwargs)
        return config

    def create_quote_request(self, doors: List[Dict[str, Any]], po_number: str, tag_name: str) -> Dict[str, Any]:
        return {
            "selectType": "yes", "data": doors, "po_number": po_number, "tag_name": tag_name,
            "erpCustomerNo": self.user_data.get("customerId") if self.user_data else "OP01",
            "quote_id": int(time.time() * 1000), "angleConfrigationType": "BRACKET TO WOOD",
            "trackRadius": doors[0].get("trackRadius", "15") if doors else "15"
        }


_upwardor_client: Optional[UpwardorAPIClient] = None

def get_upwardor_client() -> UpwardorAPIClient:
    global _upwardor_client
    if _upwardor_client is None:
        _upwardor_client = UpwardorAPIClient()
        try:
            _upwardor_client.login(email="opentest@yopmail.com", password="Welcome@123")
        except UpwardorAPIError as e:
            logger.warning(f"Upwardor auth failed: {e}")
    return _upwardor_client


# Mapping constants for AI-parsed specs to Upwardor format
CATEGORY_MAP = {
    "AL976": {"type": "aluminium", "value": "67f7c1c39cf0ed4a3b00baea"},
    "TX380": {"type": "commercial", "value": "67ab1db858e8bd835f4898e3"},
    "TX450": {"type": "commercial", "value": "67ab1db858e8bd835f4898e4"},
    "TX500": {"type": "commercial", "value": "67ab1db858e8bd835f4898e5"},
    "TX450-20": {"type": "commercial", "value": "67ab1db858e8bd835f4898e6"},
    "RESIDENTIAL": {"type": "residential", "value": "678f8f79088796816d501456"},
}

COLOR_MAP = {
    "white": "WHITE", "brown": "BROWN", "almond": "ALMOND",
    "black": "BLACK", "grey": "GREY", "gray": "GREY",
    "sandstone": "SANDSTONE", "desert tan": "DESERT TAN",
}

PATTERN_MAP = {
    "short": "SHXL", "long": "LNXL", "flush": "FLUSH",
    "shxl": "SHXL", "lnxl": "LNXL", "raised": "SHXL",
}

TRACK_RADIUS_MAP = {
    "12": "12", "15": "15", "standard": "15", "low": "12",
}


def map_ai_door_to_upwardor(ai_door: Dict[str, Any], client: UpwardorAPIClient) -> Dict[str, Any]:
    """Map AI-parsed door specification to Upwardor door config format."""
    width_ft = ai_door.get("width_ft") or 0
    width_in = ai_door.get("width_in") or 0
    height_ft = ai_door.get("height_ft") or 0
    height_in = ai_door.get("height_in") or 0
    door_width = int(width_ft) * 12 + int(width_in) if width_ft or width_in else 96
    door_height = int(height_ft) * 12 + int(height_in) if height_ft or height_in else 84
    color_raw = (ai_door.get("color") or "white").lower().strip()
    panel_color = COLOR_MAP.get(color_raw, "WHITE")
    pattern_raw = (ai_door.get("panel_config") or "short").lower().strip()
    stamp_pattern = PATTERN_MAP.get(pattern_raw, "SHXL")
    track_raw = (ai_door.get("track_type") or "15").lower().strip()
    track_radius = TRACK_RADIUS_MAP.get(track_raw, "15")
    model_raw = (ai_door.get("model") or "RESIDENTIAL").upper().strip()
    category_info = CATEGORY_MAP.get(model_raw, CATEGORY_MAP["RESIDENTIAL"])
    config = client.build_door_config(door_width=door_width, door_height=door_height, panel_color=panel_color, stamp_pattern=stamp_pattern, track_radius=track_radius)
    config["categoryType"] = category_info["type"]
    config["categoryValue"] = category_info["value"]
    glazing = ai_door.get("glazing")
    if glazing and glazing.lower() not in ["none", "no", ""]:
        config["window"] = "yes"
    return config


def generate_upwardor_quote_from_request(quote_request, po_number: str = None, tag_name: str = None) -> Dict[str, Any]:
    """Generate an Upwardor quote from a BC-AI-Agent quote request."""
    client = get_upwardor_client()
    parsed_data = quote_request.parsed_data or {}
    doors_data = parsed_data.get("doors", [])
    project_data = parsed_data.get("project", {})
    customer_data = parsed_data.get("customer", {})
    if not po_number:
        po_number = f"QR-{quote_request.id}"
    if not tag_name:
        tag_name = project_data.get("name") or customer_data.get("company_name") or f"Quote-{quote_request.id}"
    if not doors_data:
        logger.warning(f"No door specs found in quote request {quote_request.id}, creating placeholder")
        doors_data = [{"model": "RESIDENTIAL", "quantity": 1}]
    upwardor_doors = []
    for ai_door in doors_data:
        quantity = ai_door.get("quantity", 1) or 1
        door_config = map_ai_door_to_upwardor(ai_door, client)
        door_config["doorCount"] = quantity
        upwardor_doors.append(door_config)
    quote_payload = client.create_quote_request(doors=upwardor_doors, po_number=po_number, tag_name=tag_name)
    logger.info(f"Submitting Upwardor quote for request {quote_request.id}: {len(upwardor_doors)} door config(s)")
    result = client.generate_quote(quote_payload)
    logger.info(f"Upwardor quote generated successfully for request {quote_request.id}")
    return result
