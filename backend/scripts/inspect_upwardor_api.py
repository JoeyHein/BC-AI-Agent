"""
Upwardor Portal API Inspector
Logs into the portal and captures all API calls to document the API structure
"""

import requests
import json
from datetime import datetime
import sys
import io

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Portal configuration
PORTAL_URL = "http://195.35.8.196:8100"
USERNAME = "opentest@yopmail.com"
PASSWORD = "Welcome@123"

print("=" * 80)
print("UPWARDOR PORTAL API INSPECTOR")
print("=" * 80)
print(f"Portal URL: {PORTAL_URL}")
print(f"Username: {USERNAME}")
print()

# Create a session to maintain cookies/auth
session = requests.Session()

# Step 1: Try to access the login page
print("Step 1: Accessing login page...")
try:
    response = session.get(f"{PORTAL_URL}/login", timeout=10)
    print(f"   ✅ Login page status: {response.status_code}")
    print(f"   Content-Type: {response.headers.get('Content-Type')}")
    print(f"   Cookies received: {list(session.cookies.keys())}")
except Exception as e:
    print(f"   ❌ Error accessing login page: {e}")
    print()
    print("TROUBLESHOOTING:")
    print("- Is the portal running?")
    print("- Are you on the correct network/VPN?")
    print("- Can you access the portal in your browser?")
    exit(1)

# Step 2: Try to login
print()
print("Step 2: Attempting login...")

# Try common login endpoints
login_endpoints = [
    "/api/auth/login",
    "/api/login",
    "/auth/login",
    "/login",
    "/api/v1/auth/login",
]

login_data_formats = [
    {"email": USERNAME, "password": PASSWORD},
    {"username": USERNAME, "password": PASSWORD},
    {"user": USERNAME, "password": PASSWORD},
]

login_successful = False
auth_response = None

for endpoint in login_endpoints:
    for data_format in login_data_formats:
        try:
            url = f"{PORTAL_URL}{endpoint}"
            print(f"   Trying: POST {endpoint} with {list(data_format.keys())}")

            response = session.post(
                url,
                json=data_format,
                headers={"Content-Type": "application/json"},
                timeout=10
            )

            print(f"      Status: {response.status_code}")

            if response.status_code in [200, 201]:
                print(f"      ✅ Login successful!")
                auth_response = response.json()
                print(f"      Response: {json.dumps(auth_response, indent=2)[:500]}")
                login_successful = True
                break
            elif response.status_code == 404:
                print(f"      ❌ Endpoint not found")
            else:
                print(f"      Response: {response.text[:200]}")

        except Exception as e:
            print(f"      Error: {e}")

    if login_successful:
        break

if not login_successful:
    print()
    print("❌ Could not find working login endpoint")
    print()
    print("NEXT STEPS:")
    print("1. Open the portal in your browser: " + PORTAL_URL)
    print("2. Open Developer Tools (F12)")
    print("3. Go to Network tab")
    print("4. Login with the credentials")
    print("5. Look for the login API call and note:")
    print("   - Endpoint URL")
    print("   - Request method (POST/GET)")
    print("   - Request body format")
    print("   - Response format")
    print()
    print("Share that information and I'll build the integration!")
    exit(1)

# Step 3: Explore available endpoints
print()
print("Step 3: Exploring API endpoints...")

# Check if there's an auth token
auth_token = None
if auth_response:
    # Common token field names
    for key in ['token', 'access_token', 'accessToken', 'jwt', 'auth_token']:
        if key in auth_response:
            auth_token = auth_response[key]
            print(f"   Found auth token: {key}")
            break

# Set up headers with auth token
headers = {"Content-Type": "application/json"}
if auth_token:
    # Try different auth header formats
    headers["Authorization"] = f"Bearer {auth_token}"

# Try to discover API endpoints
common_endpoints = [
    "/api/doors",
    "/api/products",
    "/api/configurations",
    "/api/quotes",
    "/api/pricing",
    "/api/models",
    "/api/catalog",
    "/api/items",
    "/api/door-models",
    "/api/door-configs",
]

print()
print("Checking common endpoints:")
results = {}

for endpoint in common_endpoints:
    try:
        url = f"{PORTAL_URL}{endpoint}"
        response = session.get(url, headers=headers, timeout=5)

        status = "✅" if response.status_code == 200 else "❌"
        print(f"   {status} GET {endpoint} -> {response.status_code}")

        if response.status_code == 200:
            results[endpoint] = {
                "status": response.status_code,
                "content_type": response.headers.get("Content-Type"),
                "data_preview": response.text[:500]
            }
    except Exception as e:
        print(f"   ⚠️  GET {endpoint} -> Error: {str(e)[:50]}")

# Step 4: Save results
print()
print("Step 4: Saving API inspection results...")

output = {
    "portal_url": PORTAL_URL,
    "timestamp": datetime.utcnow().isoformat(),
    "login_successful": login_successful,
    "auth_response": auth_response,
    "auth_token": auth_token[:20] + "..." if auth_token and len(auth_token) > 20 else auth_token,
    "discovered_endpoints": results,
}

output_file = "upwardor_api_inspection.json"
with open(output_file, "w") as f:
    json.dump(output, f, indent=2)

print(f"   ✅ Results saved to: {output_file}")

print()
print("=" * 80)
print("INSPECTION COMPLETE")
print("=" * 80)
print()

if login_successful and results:
    print("✅ Successfully discovered API endpoints!")
    print()
    print("Working endpoints:")
    for endpoint, data in results.items():
        print(f"   - {endpoint}")
    print()
    print(f"Full details saved to: {output_file}")
else:
    print("⚠️  Limited information gathered")
    print()
    print("RECOMMENDED NEXT STEPS:")
    print("1. Open the portal in Chrome/Firefox")
    print("2. Open Developer Tools (F12) → Network tab")
    print("3. Login and navigate around the portal")
    print("4. Look for API calls (XHR/Fetch)")
    print("5. Share screenshots or the Request/Response details")
    print()
    print("I'll use that to build the full API integration!")

print()
