"""
Selenium script to explore Upwardor Portal and capture configuration options
This will help us learn:
- Available door series
- Stamp patterns
- Colors
- Hardware options
- API endpoints and data structures
"""

import sys
import io
import time
import json
from selenium import webdriver

# Fix Windows console encoding for emojis
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# Portal credentials
PORTAL_URL = "http://195.35.8.196:8100/"
USERNAME = "opentest@yopmail.com"
PASSWORD = "Welcome@123"

class UpwardorPortalExplorer:
    def __init__(self):
        print("🚀 Starting Upwardor Portal Explorer...")

        # Setup Chrome driver
        service = Service(ChromeDriverManager().install())
        options = webdriver.ChromeOptions()
        options.add_argument('--start-maximized')
        # Enable browser logging to capture network requests
        options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})

        self.driver = webdriver.Chrome(service=service, options=options)
        self.wait = WebDriverWait(self.driver, 10)
        self.captured_data = {}

    def login(self):
        """Login to the portal"""
        print(f"\n📋 Navigating to: {PORTAL_URL}")
        self.driver.get(PORTAL_URL)
        time.sleep(3)

        try:
            print("🔑 Waiting for login form...")

            # Wait for page to fully load
            self.wait.until(EC.presence_of_element_located((By.TAG_NAME, "form")))

            # Take screenshot of login page for debugging
            self.driver.save_screenshot("login_page_before.png")
            print("📸 Saved login page screenshot")

            # Find all input fields
            all_inputs = self.driver.find_elements(By.TAG_NAME, "input")
            print(f"Found {len(all_inputs)} input fields")

            # Find email and password fields by type
            email_field = None
            password_field = None

            for input_elem in all_inputs:
                input_type = input_elem.get_attribute('type')
                placeholder = input_elem.get_attribute('placeholder') or ""

                if input_type == 'email' or 'email' in placeholder.lower():
                    email_field = input_elem
                    print(f"  Found email field: type={input_type}, placeholder={placeholder}")
                elif input_type == 'password':
                    password_field = input_elem
                    print(f"  Found password field: type={input_type}")

            if not email_field:
                raise Exception("Could not find email input field")
            if not password_field:
                raise Exception("Could not find password input field")

            # Fill in credentials
            print("📝 Filling in credentials...")
            email_field.clear()
            email_field.send_keys(USERNAME)
            time.sleep(0.5)

            password_field.clear()
            password_field.send_keys(PASSWORD)
            time.sleep(0.5)

            # Take screenshot after filling
            self.driver.save_screenshot("login_page_filled.png")

            # Find and click sign in button
            buttons = self.driver.find_elements(By.TAG_NAME, "button")
            sign_in_button = None

            for button in buttons:
                button_text = button.text.strip().lower()
                if 'sign in' in button_text or 'login' in button_text:
                    sign_in_button = button
                    print(f"  Found sign in button: '{button.text}'")
                    break

            if not sign_in_button:
                raise Exception("Could not find sign in button")

            print("🖱️  Clicking sign in...")
            sign_in_button.click()

            time.sleep(5)  # Wait longer for redirect

            # Take screenshot after login
            self.driver.save_screenshot("after_login.png")
            print("✅ Login attempt complete!")

        except Exception as e:
            print(f"❌ Login failed: {e}")
            self.driver.save_screenshot("login_error.png")
            raise

    def navigate_to_build_door(self):
        """Navigate to the Build A Door form"""
        print("\n🚪 Looking for 'Create A Quote' button...")

        try:
            # Wait longer for dashboard to load
            time.sleep(5)

            # Debug: Print all text on page
            body_text = self.driver.find_element(By.TAG_NAME, "body").text
            print(f"\n📄 Page text content:\n{body_text[:500]}")

            # Look for all clickable divs
            all_divs = self.driver.find_elements(By.TAG_NAME, "div")
            clickable_divs = [d for d in all_divs if d.get_attribute("onclick") or "cursor: pointer" in d.get_attribute("style") or ""]
            print(f"\n🖱️  Found {len(clickable_divs)} potentially clickable divs")

            # Look for elements containing "CREATE" text (it's split across lines)
            create_elements = self.driver.find_elements(By.XPATH, "//*[contains(text(), 'CREATE')]")

            if create_elements:
                print(f"Found {len(create_elements)} elements with 'CREATE' text")
                # Find the clickable parent (likely a div or link)
                for elem in create_elements:
                    parent = elem.find_element(By.XPATH, "..")
                    # Check if parent or grandparent is clickable
                    try:
                        # Try clicking the parent
                        print("Attempting to click CREATE A QUOTE card...")
                        parent.click()
                        time.sleep(3)
                        self.driver.save_screenshot("quote_selection_page.png")
                        print("✅ Clicked CREATE A QUOTE")
                        break
                    except:
                        # Try grandparent
                        try:
                            grandparent = parent.find_element(By.XPATH, "..")
                            grandparent.click()
                            time.sleep(3)
                            self.driver.save_screenshot("quote_selection_page.png")
                            print("✅ Clicked CREATE A QUOTE")
                            break
                        except:
                            continue

                # Now look for "Build A Door" option
                time.sleep(2)
                build_door_elements = self.driver.find_elements(By.XPATH,
                    "//*[contains(text(), 'Build') and contains(., 'Door')]"
                )

                if not build_door_elements:
                    # Try alternative search
                    build_door_elements = self.driver.find_elements(By.XPATH, "//*[contains(text(), 'Build')]")

                if build_door_elements:
                    print(f"Found 'Build A Door' option")
                    # Try to click it or its parent
                    for elem in build_door_elements:
                        try:
                            elem.click()
                            time.sleep(3)
                            self.driver.save_screenshot("build_door_form.png")
                            print("✅ Navigated to Build A Door form")
                            break
                        except:
                            try:
                                parent = elem.find_element(By.XPATH, "..")
                                parent.click()
                                time.sleep(3)
                                self.driver.save_screenshot("build_door_form.png")
                                print("✅ Navigated to Build A Door form")
                                break
                            except:
                                continue
                else:
                    print("⚠️ Could not find 'Build A Door' option")
                    self.driver.save_screenshot("quote_options.png")

            else:
                print("⚠️ Could not find 'CREATE' button")
                self.driver.save_screenshot("dashboard.png")

        except Exception as e:
            print(f"❌ Navigation failed: {e}")
            import traceback
            traceback.print_exc()
            self.driver.save_screenshot("navigation_error.png")

    def extract_dropdown_options(self, field_name, selector):
        """Extract all options from a dropdown field"""
        try:
            select_element = self.driver.find_element(By.CSS_SELECTOR, selector)
            select = Select(select_element)
            options = [option.text for option in select.options if option.text.strip()]

            print(f"  ✅ {field_name}: {len(options)} options")
            return options

        except Exception as e:
            print(f"  ⚠️ Could not find {field_name}: {e}")
            return []

    def explore_door_form_fields(self):
        """Explore all form fields on the Build A Door page"""
        print("\n🔍 Exploring form fields...")

        # Map of field names to CSS selectors (we'll try common patterns)
        fields_to_check = {
            "Door Type": "select[name*='type'], select[id*='type']",
            "Door Series": "select[name*='series'], select[id*='series']",
            "Panel Width": "select[name*='width'], select[id*='width']",
            "Panel Height": "select[name*='height'], select[id*='height'], select[name*='length']",
            "Stamp Pattern": "select[name*='pattern'], select[id*='pattern'], select[name*='stamp']",
            "Color": "select[name*='color'], select[id*='color']",
            "Window": "select[name*='window'], select[id*='window']",
            "Track Type": "select[name*='track'], select[id*='track']",
        }

        # Try to extract all dropdowns
        all_selects = self.driver.find_elements(By.TAG_NAME, "select")
        print(f"\n📊 Found {len(all_selects)} dropdown fields total")

        for idx, select_elem in enumerate(all_selects):
            try:
                # Get field label or name
                field_id = select_elem.get_attribute('id') or f"field_{idx}"
                field_name = select_elem.get_attribute('name') or field_id

                # Get all options
                select = Select(select_elem)
                options = [opt.text.strip() for opt in select.options if opt.text.strip()]

                if options:
                    self.captured_data[field_name] = options
                    print(f"  📋 {field_name}: {len(options)} options")
                    # Print first few options as preview
                    preview = options[:5]
                    print(f"     Preview: {', '.join(preview)}...")

            except Exception as e:
                print(f"  ⚠️ Error reading dropdown {idx}: {e}")

        # Also capture all labels to understand field names
        labels = self.driver.find_elements(By.TAG_NAME, "label")
        print(f"\n🏷️  Found {len(labels)} labels:")
        for label in labels[:20]:  # Show first 20
            text = label.text.strip()
            if text:
                print(f"  • {text}")

    def capture_network_requests(self):
        """Capture network requests to find API endpoints"""
        print("\n🌐 Capturing network requests...")

        try:
            logs = self.driver.get_log('performance')
            api_calls = []

            for log in logs:
                message = json.loads(log['message'])['message']

                if message['method'] == 'Network.requestWillBeSent':
                    request_url = message['params']['request']['url']

                    # Filter for API calls (not static assets)
                    if ':6100' in request_url or '/api/' in request_url:
                        api_calls.append({
                            'url': request_url,
                            'method': message['params']['request']['method']
                        })

            if api_calls:
                print(f"✅ Found {len(api_calls)} API calls:")
                for call in api_calls[:10]:  # Show first 10
                    print(f"  • {call['method']} {call['url']}")

                self.captured_data['api_endpoints'] = api_calls
            else:
                print("⚠️ No API calls captured yet")

        except Exception as e:
            print(f"⚠️ Could not capture network logs: {e}")

    def take_screenshots(self):
        """Take screenshots of key pages"""
        print("\n📸 Taking screenshots...")

        self.driver.save_screenshot("upwardor_current_page.png")
        print("✅ Saved: upwardor_current_page.png")

        # Try to scroll down to capture more of the form
        self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight/2);")
        time.sleep(1)
        self.driver.save_screenshot("upwardor_page_middle.png")
        print("✅ Saved: upwardor_page_middle.png")

        self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1)
        self.driver.save_screenshot("upwardor_page_bottom.png")
        print("✅ Saved: upwardor_page_bottom.png")

    def save_results(self):
        """Save captured data to JSON file"""
        print("\n💾 Saving captured data...")

        output_file = "upwardor_portal_data.json"
        with open(output_file, 'w') as f:
            json.dump(self.captured_data, f, indent=2)

        print(f"✅ Saved to: {output_file}")
        print(f"\n📊 Summary:")
        print(f"  • Total fields captured: {len(self.captured_data)}")
        for field, options in self.captured_data.items():
            if isinstance(options, list):
                print(f"  • {field}: {len(options)} options")

    def explore(self):
        """Main exploration flow"""
        try:
            # Login
            self.login()

            # Navigate to Build A Door
            self.navigate_to_build_door()

            # Explore form fields
            self.explore_door_form_fields()

            # Capture network requests
            self.capture_network_requests()

            # Take screenshots
            self.take_screenshots()

            # Save results
            self.save_results()

            print("\n✅ Exploration complete!")
            print("\n⏸️  Browser will stay open for 30 seconds for manual inspection...")
            time.sleep(30)

        except Exception as e:
            print(f"\n❌ Error during exploration: {e}")
            self.driver.save_screenshot("error_state.png")

        finally:
            print("\n🔒 Closing browser...")
            self.driver.quit()


if __name__ == "__main__":
    print("=" * 60)
    print("UPWARDOR PORTAL EXPLORER")
    print("=" * 60)

    explorer = UpwardorPortalExplorer()
    explorer.explore()

    print("\n" + "=" * 60)
    print("EXPLORATION COMPLETE")
    print("=" * 60)
    print("\nCheck the following files:")
    print("  - upwardor_portal_data.json - Captured form data")
    print("  - upwardor_*.png - Screenshots of portal pages")
    print("\n")
