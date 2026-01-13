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
            "decorativeHardWareParts": "no", "trackRequest": "NO", "V_W_Qty": [],
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
