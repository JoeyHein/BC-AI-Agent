"""
Interactive Upwardor Portal Explorer
Logs in and stays open for manual exploration while capturing all API calls
"""

import sys
import io
import time
import json
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Portal credentials
PORTAL_URL = "http://195.35.8.196:8100/"
USERNAME = "opentest@yopmail.com"
PASSWORD = "Welcome@123"

def login_to_portal():
    """Login and stay open for manual exploration"""
    print("=" * 60)
    print("INTERACTIVE UPWARDOR PORTAL EXPLORER")
    print("=" * 60)

    # Setup Chrome with network logging
    service = Service(ChromeDriverManager().install())
    options = webdriver.ChromeOptions()
    options.add_argument('--start-maximized')
    options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})

    driver = webdriver.Chrome(service=service, options=options)
    wait = WebDriverWait(driver, 10)

    print(f"\nNavigating to: {PORTAL_URL}")
    driver.get(PORTAL_URL)
    time.sleep(3)

    try:
        # Login
        print("Logging in...")
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "form")))

        # Find and fill email/password
        all_inputs = driver.find_elements(By.TAG_NAME, "input")
        email_field = None
        password_field = None

        for input_elem in all_inputs:
            input_type = input_elem.get_attribute('type')
            if input_type == 'email' or input_type == 'text':
                email_field = input_elem
            elif input_type == 'password':
                password_field = input_elem

        if email_field and password_field:
            email_field.send_keys(USERNAME)
            password_field.send_keys(PASSWORD)

            # Find and click sign in
            buttons = driver.find_elements(By.TAG_NAME, "button")
            for button in buttons:
                if 'sign in' in button.text.lower():
                    button.click()
                    break

            time.sleep(5)
            print("✅ Login successful!")
            print("\n" + "=" * 60)
            print("PORTAL IS NOW OPEN")
            print("=" * 60)
            print("\nInstructions:")
            print("1. Manually navigate to CREATE A QUOTE")
            print("2. Click 'Build A Door'")
            print("3. Explore the form - select different options")
            print("4. All API calls are being captured")
            print("\nWhen done, press Ctrl+C in this terminal")
            print("\nBrowser will stay open for 10 minutes...")
            print("=" * 60)

            # Keep browser open and capture network activity
            start_time = time.time()
            api_calls = set()  # Use set to avoid duplicates

            while time.time() - start_time < 600:  # 10 minutes
                try:
                    # Capture network logs
                    logs = driver.get_log('performance')
                    for log in logs:
                        try:
                            message = json.loads(log['message'])['message']
                            if message['method'] == 'Network.requestWillBeSent':
                                request_url = message['params']['request']['url']
                                method = message['params']['request']['method']

                                # Filter for API calls
                                if ':6100' in request_url and '/socket.io/' not in request_url:
                                    api_call = f"{method} {request_url}"
                                    if api_call not in api_calls:
                                        api_calls.add(api_call)
                                        print(f"\n🌐 API Call: {method} {request_url}")

                                        # Try to print request body if POST
                                        if method == 'POST' and 'postData' in message['params']['request']:
                                            print(f"   Body: {message['params']['request']['postData'][:200]}")

                        except:
                            pass

                    time.sleep(2)  # Check every 2 seconds

                except KeyboardInterrupt:
                    print("\n\n👋 Stopping capture...")
                    break
                except:
                    pass

            # Save captured API calls
            print("\n\n" + "=" * 60)
            print(f"CAPTURED {len(api_calls)} UNIQUE API CALLS")
            print("=" * 60)

            output = {
                "api_calls": sorted(list(api_calls)),
                "total_calls": len(api_calls)
            }

            with open("upwardor_api_calls.json", "w") as f:
                json.dump(output, f, indent=2)

            print(f"\n✅ Saved to: upwardor_api_calls.json")
            print("\nClosing browser...")
            driver.quit()

        else:
            print("❌ Could not find login fields")
            driver.quit()

    except Exception as e:
        print(f"❌ Error: {e}")
        driver.save_screenshot("error.png")
        driver.quit()


if __name__ == "__main__":
    login_to_portal()
