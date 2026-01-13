"""
Test script for Upwardor Portal API client
Verifies login and basic API access
"""

import sys
import io
from pathlib import Path

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Add parent directory to path so we can import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.upwardor_service import UpwardorAPIClient, UpwardorAPIError
import json


def main():
    print("=" * 80)
    print("UPWARDOR PORTAL API TEST")
    print("=" * 80)
    print()

    # Create client
    client = UpwardorAPIClient()

    # Test 1: Login
    print("Test 1: Login to Upwardor Portal")
    print("-" * 80)
    try:
        login_response = client.login(
            email="opentest@yopmail.com",
            password="Welcome@123"
        )

        print("✅ Login successful!")
        print()
        print("Full Response:")
        print(json.dumps(login_response, indent=2))
        print()

        # Extract user ID if available
        user_id = None
        if "user" in login_response and "id" in login_response["user"]:
            user_id = login_response["user"]["id"]
        elif "data" in login_response and "id" in login_response["data"]:
            user_id = login_response["data"]["id"]
        elif "id" in login_response:
            user_id = login_response["id"]

        if client.access_token:
            print(f"Access Token: {client.access_token[:30]}...")
        if user_id:
            print(f"User ID: {user_id}")
        print()

    except UpwardorAPIError as e:
        print(f"❌ Login failed: {e}")
        print()
        print("Tip: Check if the portal is accessible and credentials are correct")
        return

    # Test 2: Get User Detail (if we have a user ID)
    if user_id:
        print("Test 2: Get User Detail")
        print("-" * 80)
        try:
            detail_response = client.get_user_detail(user_id)

            print("✅ User detail retrieved!")
            print()
            print("Response preview:")
            print(json.dumps(detail_response, indent=2)[:500])
            print()

        except UpwardorAPIError as e:
            print(f"❌ Get user detail failed: {e}")
            print()

    # Test 3: Try to discover more endpoints
    print("Test 3: Discovering Additional Endpoints")
    print("-" * 80)
    print()

    # Try common endpoints
    test_endpoints = [
        "/api/doors",
        "/api/products",
        "/api/catalog",
        "/admin/products/list",
        "/door/list",
        "/api/door-models",
        "/api/configurations",
        "/api/pricing",
    ]

    discovered = []

    for endpoint in test_endpoints:
        try:
            url = f"{client.base_url}{endpoint}"
            response = client.session.get(
                url,
                headers={
                    "Authorization": f"Bearer {client.access_token}",
                    "Content-Type": "application/json"
                },
                timeout=5
            )

            if response.status_code == 200:
                print(f"✅ Found: {endpoint}")
                discovered.append({
                    "endpoint": endpoint,
                    "status": response.status_code,
                    "preview": response.text[:200]
                })
            elif response.status_code == 404:
                print(f"❌ Not found: {endpoint}")
            else:
                print(f"⚠️  {endpoint} -> {response.status_code}")

        except Exception as e:
            print(f"⚠️  {endpoint} -> Error: {str(e)[:50]}")

    print()
    print("=" * 80)
    print("TEST COMPLETE")
    print("=" * 80)
    print()

    if discovered:
        print("✅ Discovered working endpoints:")
        for item in discovered:
            print(f"   - {item['endpoint']}")
        print()
        print("Full details:")
        print(json.dumps(discovered, indent=2))
    else:
        print("ℹ️  No additional endpoints discovered automatically")
        print()
        print("Next steps:")
        print("1. Open the Upwardor Portal in your browser")
        print("2. Open Developer Tools (F12) -> Network tab")
        print("3. Navigate to door products/configurations")
        print("4. Capture the API calls (see UPWARDOR_API_CAPTURE.md)")


if __name__ == "__main__":
    main()
