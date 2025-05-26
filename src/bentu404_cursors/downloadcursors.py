#!/usr/bin/env python3

"""
Script to automatically download cursor packs from bentu404's Ko-fi shop.
Specifically targets files ending with 'Pixel Cursors ani.zip'.
Uses the user's existing Chromium profile.
"""

import os
import time
import json
import argparse
import datetime
import re
import requests
import hashlib
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Any
import base64
from pathlib import Path
from urllib.parse import urlparse, unquote
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys

def sanitize_name(filename: str) -> str:
    """
    Sanitize filename to create a valid package name.

    Args:
        filename: The original filename

    Returns:
        A sanitized package name
    """
    # Handle common cursor pack suffixes
    if filename.endswith("s Pixel Cursors ani.zip"):
        base = filename.removesuffix("s Pixel Cursors ani.zip")
    elif filename.endswith("s Pixel Cursors.zip"):
        base = filename.removesuffix("s Pixel Cursors.zip")
    elif filename.endswith(" Pixel Cursors.zip"):
        base = filename.removesuffix(" Pixel Cursors.zip")
    elif filename.endswith(".zip"):
        base = filename.removesuffix(".zip")
    else:
        base = filename

    # Insert spaces at word boundaries: camelCase, PascalCase, digits
    spaced = re.sub(r'(?<=[a-z])(?=[A-Z0-9])|(?<=[0-9])(?=[A-Za-z])', ' ', base)

    # Lowercase, replace spaces and underscores with dashes, strip illegal characters
    lowered = spaced.lower()
    dashed = lowered.replace(" ", "-").replace("_", "-")
    sanitized = re.sub(r"[^a-z0-9-]", "", dashed)

    # Remove repeated dashes and trailing dashes
    sanitized = re.sub(r'-+', '-', sanitized)
    return sanitized.rstrip('-')

@dataclass
class CursorMetadata:
    """Class for storing cursor metadata."""
    filename: str
    url: str
    preview_image: Optional[str] = None
    hash: Optional[str] = None
    download_date: str = field(default_factory=lambda: datetime.datetime.now().isoformat())
    name: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CursorMetadata':
        """Create a CursorMetadata object from a dictionary."""
        return cls(**data)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    def __post_init__(self):
        """Generate the sanitized package name if not provided."""
        # Always regenerate name to ensure consistency
        if self.filename:
            self.name = sanitize_name(self.filename)

class KofiCursorDownloader:
    def __init__(self, download_dir, headless=False, user_profile=None, skip_items=0, specific_url=None):
        """
        Initialize the downloader with the target download directory.

        Args:
            download_dir: Directory where cursor files will be saved
            headless: Whether to run the browser in headless mode
            user_profile: Path to the user's Chromium profile directory
            skip_items: Number of items to skip from the beginning
            specific_url: URL of a specific cursor item to download (bypasses list fetching)
        """
        self.download_dir = Path(download_dir)
        self.headless = headless
        self.user_profile = user_profile or os.path.expanduser("~/.config/chromium")
        self.skip_items = skip_items
        self.specific_url = specific_url
        self.tracking_file = self.download_dir / "download_tracking.json"
        self.downloaded_cursors: List[CursorMetadata] = self.load_tracking_data()

        # Create download directory if it doesn't exist
        os.makedirs(self.download_dir, exist_ok=True)

        # Initialize the browser
        self.setup_browser()

    def load_tracking_data(self) -> List[CursorMetadata]:
        """Load the tracking data from the JSON file if it exists."""
        if self.tracking_file.exists():
            try:
                with open(self.tracking_file, 'r') as f:
                    data = json.load(f)
                    # Handle both formats (new list format and old dict format)
                    if isinstance(data, dict) and "downloaded_cursors" in data:
                        cursor_list = data["downloaded_cursors"]
                    else:
                        cursor_list = data

                    # Convert dictionaries to CursorMetadata objects
                    cursors = []
                    for cursor_data in cursor_list:
                        # Create the CursorMetadata object
                        cursor = CursorMetadata.from_dict(cursor_data)
                        # Always regenerate the name to ensure it's up to date with current rules
                        cursor.name = sanitize_name(cursor.filename)
                        cursors.append(cursor)
                    return cursors
            except json.JSONDecodeError:
                print(f"Warning: Could not parse tracking file {self.tracking_file}, creating new one")
                return []
        return []

    def save_tracking_data(self):
        """Save the tracking data to the JSON file."""
        # Convert CursorMetadata objects to dictionaries for JSON serialization
        serializable_data = [cursor.to_dict() for cursor in self.downloaded_cursors]
        with open(self.tracking_file, 'w') as f:
            json.dump(serializable_data, f, indent=2)

    def add_downloaded_cursor(self, filename, url, preview_image=None, sri_hash=None):
        """Add a downloaded cursor to the tracking data."""
        cursor = CursorMetadata(
            filename=filename,
            url=url,
            preview_image=preview_image,
            hash=sri_hash,
            name=sanitize_name(filename)
        )
        self.downloaded_cursors.append(cursor)
        self.save_tracking_data()

    def is_url_downloaded(self, url) -> bool:
        """Check if a URL has already been downloaded."""
        for cursor in self.downloaded_cursors:
            if cursor.url == url:
                return True
        return False

    def calculate_sri_hash(self, file_path):
        """
        Calculate the SRI (Subresource Integrity) hash for a file.

        Args:
            file_path: Path to the file

        Returns:
            SRI hash string in the format 'sha256-base64hash'
        """
        with open(file_path, 'rb') as f:
            file_data = f.read()
            hash_obj = hashlib.sha256(file_data)
            hash_base64 = base64.b64encode(hash_obj.digest()).decode('ascii')
            return f"sha256-{hash_base64}"

    def download_file(self, url, cookies=None):
        """
        Download a file from a URL, following redirects, and save it to the download directory.
        Returns the path to the downloaded file, filename, and SRI hash.

        Args:
            url: The URL to download
            cookies: Cookies to include in the request (from Selenium)

        Returns:
            Tuple of (file_path, filename, sri_hash)
        """
        print(f"Downloading file from: {url}")

        # Create a session to handle cookies and redirects
        session = requests.Session()

        # Add cookies from the browser if provided
        if cookies:
            for cookie in cookies:
                session.cookies.set(cookie['name'], cookie['value'], domain=cookie['domain'])

        # Set headers to mimic a browser
        headers = {
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }

        # Make the request, following redirects
        response = session.get(url, headers=headers, stream=True, allow_redirects=True)
        response.raise_for_status()

        # Try to get filename from Content-Disposition header
        filename = None
        content_disposition = response.headers.get('Content-Disposition')
        if content_disposition:
            # Try to extract filename from Content-Disposition
            match = re.search(r'filename=["\']?([^"\';\n]+)', content_disposition)
            if match:
                filename = match.group(1)

        # If no filename in header, use the last part of the URL
        if not filename:
            parsed_url = urlparse(response.url)
            filename = unquote(os.path.basename(parsed_url.path))

        # Ensure we have a valid filename
        if not filename or filename == '':
            filename = f"download_{int(time.time())}.zip"

        # Make sure the filename is safe
        filename = os.path.basename(filename)

        # Create the full file path
        file_path = self.download_dir / filename

        # Download the file in chunks
        with open(file_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

        print(f"Downloaded file to: {file_path}")

        # Calculate SRI hash
        sri_hash = self.calculate_sri_hash(file_path)
        print(f"Generated SRI hash: {sri_hash}")

        return file_path, filename, sri_hash

    def setup_browser(self):
        """Set up the Selenium WebDriver with appropriate options."""
        options = webdriver.ChromeOptions()

        # Use chromium from PATH
        import shutil
        chromium_path = shutil.which("chromium")
        if not chromium_path:
            print("Warning: 'chromium' not found in PATH, falling back to default")
        else:
            print(f"Using chromium from: {chromium_path}")
            options.binary_location = chromium_path

        # Use existing user profile
        options.add_argument(f"--user-data-dir={self.user_profile}")

        # Configure download directory
        prefs = {
            "download.default_directory": str(self.download_dir.absolute()),
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": False
        }
        options.add_experimental_option("prefs", prefs)

        if self.headless:
            options.add_argument("--headless")

        # Add additional options for stability
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")

        self.driver = webdriver.Chrome(options=options)
        self.wait = WebDriverWait(self.driver, 10)

    def scroll_and_load_all_items(self):
        """
        Scroll down the page to trigger infinite scrolling and load all items.
        Returns the total number of items found.
        """
        shop_card_xpath = '//*[@id="shop-card"]'
        previous_item_count = 0
        current_item_count = 0
        max_attempts = 10
        attempts = 0

        print("Loading all items by scrolling...")

        while attempts < max_attempts:
            # Get current item count
            items = self.driver.find_elements(By.XPATH, shop_card_xpath)
            current_item_count = len(items)

            print(f"Currently loaded items: {current_item_count}")

            if current_item_count == previous_item_count:
                attempts += 1
                print(f"No new items loaded. Attempt {attempts}/{max_attempts}")
            else:
                attempts = 0  # Reset attempts if we found new items
                previous_item_count = current_item_count

            # Scroll to the bottom of the page
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)  # Wait for items to load

            # Press End key to ensure we're at the bottom
            ActionChains(self.driver).send_keys(Keys.END).perform()
            time.sleep(1)

        print(f"Finished loading all items. Total found: {current_item_count}")
        return current_item_count

    def _process_item_url(self, url, main_window=None, item_index=None, total_items=None, force_download=False):
        """
        Process a single item URL to download the cursor pack.

        Args:
            url: The URL of the item to download
            main_window: The main window handle to return to (if None, will be the current window)
            item_index: Index of the item in the list (for logging)
            total_items: Total number of items (for logging)
            force_download: If True, download even if already downloaded and replace tracking data
        """
        if main_window is not None:
            self.driver.switch_to.new_window('tab')

        try:
            # Optional item number for logging
            item_info = ""
            if item_index is not None and total_items is not None:
                item_info = f" {item_index+1}/{total_items}"

            print(f"Processing item{item_info}: {url}")

            # Skip if this URL has already been downloaded and we're not forcing a redownload
            if not force_download and self.is_url_downloaded(url):
                print(f"Skipping already downloaded item: {url}")
                if main_window is not None:
                    self.driver.close()
                    self.driver.switch_to.window(main_window)
                return

            # If forcing a download, remove existing entries for this URL
            if force_download and self.is_url_downloaded(url):
                print(f"Forcing redownload of item: {url}")
                # Remove all entries with this URL
                self.downloaded_cursors = [item for item in self.downloaded_cursors if item.url != url]
                self.save_tracking_data()

            # Navigate to the item URL
            self.driver.get(url)
            time.sleep(2)

            # Try to get all preview image sources
            preview_images = []
            try:
                preview_image_elements = self.driver.find_elements(
                    By.XPATH, "//div[contains(@class, 'carousel-item')]/img"
                )
                for element in preview_image_elements:
                    img_src = element.get_attribute('src')
                    if img_src:
                        preview_images.append(img_src)

                if preview_images:
                    print(f"Found {len(preview_images)} preview images")
                else:
                    print("No preview images found")
            except Exception as e:
                print(f"Error getting preview images: {e}")

            # Enter 0 in the payment field
            payment_field = self.wait.until(
                EC.element_to_be_clickable((By.XPATH, "//input[contains(@placeholder, '$0 or more')]"))
            )
            payment_field.clear()
            payment_field.send_keys("0")

            # Click Get Now
            get_now_button = self.wait.until(
                EC.element_to_be_clickable((By.XPATH, '//*[@id="addToCartButton"]'))
            )
            get_now_button.click()
            time.sleep(2)

            # Check if we're already logged in
            try:
                # If we need to enter email/name, we're not logged in
                email_field = self.driver.find_element(By.XPATH, "//input[@placeholder='Email address']")
                print("Not logged in, filling guest checkout form")

                # Fill in guest checkout form
                email_field.send_keys("guest@example.com")

                name_field = self.driver.find_element(By.XPATH, "//input[@placeholder='Your name or nickname']")
                name_field.send_keys("Guest")

            except NoSuchElementException:
                # We're already logged in, no need to fill in details
                print("Already logged in, proceeding with checkout")

            # Click Checkout Now
            checkout_button = self.wait.until(
                EC.element_to_be_clickable((By.XPATH, "/html/body/div[2]/div/div/div/div[1]/div[5]/button"))
            )
            checkout_button.click()
            time.sleep(3)

            # Click View Content
            view_content_button = self.wait.until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'View Content')]"))
            )
            view_content_button.click()
            time.sleep(2)

            # Find all ani.zip files
            ani_buttons = self.driver.find_elements(
                By.XPATH, "//div[contains(text(), 'ani.zip')]/..//a"
            )

            # Track whether we successfully downloaded any files for this item
            files_downloaded = False

            if ani_buttons:
                print(f"Found {len(ani_buttons)} ani.zip download buttons")

                # Process all ani.zip downloads
                for idx, button in enumerate(ani_buttons):
                    try:
                        # Get file name hint from the UI if possible
                        file_hint = ""
                        try:
                            file_text_element = button.find_element(
                                By.XPATH, "./ancestor::li/div[contains(@class, 'kfds-font-text-limit')]"
                            )
                            file_hint = file_text_element.text.strip()
                            print(f"Processing ani.zip ({idx+1}/{len(ani_buttons)}): {file_hint}")
                        except Exception as hint_error:
                            print(f"Processing ani.zip ({idx+1}/{len(ani_buttons)})")
                            print(f"Note: Could not get file hint: {hint_error}")

                        # Get the download URL
                        download_url = button.get_attribute('href')
                        if not download_url:
                            print(f"Could not get download URL for ani.zip ({idx+1}/{len(ani_buttons)})")
                            continue

                        # Get browser cookies for the download
                        cookies = self.driver.get_cookies()

                        # Download the file
                        file_path, actual_filename, sri_hash = self.download_file(download_url, cookies)
                        print(f"Downloaded cursor pack: {actual_filename}")

                        # Get a preview image for this download
                        preview_image = None
                        if preview_images:
                            # Use the image at the current index, or the last one if we've run out
                            img_index = min(idx, len(preview_images) - 1)
                            preview_image = preview_images[img_index]

                        # Add to tracking data
                        self.add_downloaded_cursor(actual_filename, url, preview_image, sri_hash)
                        files_downloaded = True
                    except Exception as e:
                        import traceback
                        print(f"Error downloading ani.zip ({idx+1}/{len(ani_buttons)}): {e}")
                        print("Traceback for this download attempt:")
                        traceback.print_exc()

            # If no ani.zip files were found or none were successfully downloaded, try alternative downloads
            if not ani_buttons or not files_downloaded:
                if not ani_buttons:
                    print("No ani.zip button found, looking for alternative downloads")
                else:
                    print("Failed to download any ani.zip files, trying alternative downloads")

                download_buttons = []

                # Find all download buttons
                all_download_buttons = self.driver.find_elements(
                    By.XPATH, "//span[contains(text(), 'Download')]/ancestor::a"
                )

                # Filter out "fast install.zip" buttons and prioritize any other .zip files
                zip_buttons = []
                other_buttons = []

                for button in all_download_buttons:
                    try:
                        # Check the file text description
                        file_text_element = button.find_element(
                            By.XPATH, "./ancestor::li/div[contains(@class, 'kfds-font-text-limit')]"
                        )
                        file_text = file_text_element.text.strip().lower()

                        if "fast install.zip" in file_text:
                            print(f"Skipping 'fast install.zip' button: {file_text}")
                            continue

                        if ".zip" in file_text:
                            print(f"Found zip download button: {file_text}")
                            zip_buttons.append(button)
                        else:
                            print(f"Found other download button: {file_text}")
                            other_buttons.append(button)
                    except Exception as e:
                        # If we can't determine the file type, include the button to be safe
                        print(f"Couldn't determine file type for download button, including it: {e}")
                        other_buttons.append(button)

                # Prioritize .zip files, then fall back to other buttons
                if zip_buttons:
                    download_buttons = zip_buttons
                else:
                    download_buttons = other_buttons

                # Process alternative downloads
                if download_buttons:
                    # Process the first alternative download
                    try:
                        print(f"Processing alternative download button (type: {type(download_buttons[0]).__name__})")
                        download_url = download_buttons[0].get_attribute('href')

                        if download_url:
                            # Get browser cookies for the download
                            cookies = self.driver.get_cookies()

                            # Download the file using our custom function
                            file_path, actual_filename, sri_hash = self.download_file(download_url, cookies)
                            print(f"Downloaded cursor pack: {actual_filename}")

                            # Get a preview image for this alternative download
                            preview_image = None
                            if preview_images:
                                # Use the first image for alternative downloads
                                preview_image = preview_images[0]

                            # Add to tracking data
                            self.add_downloaded_cursor(actual_filename, url, preview_image, sri_hash)
                            files_downloaded = True
                        else:
                            print("Could not get download URL")
                    except Exception as alt_error:
                        import traceback
                        print(f"Error processing alternative download: {alt_error}")
                        print("Traceback for alternative download:")
                        traceback.print_exc()

            if not files_downloaded:
                print(f"Could not download any files for item{item_info}")

            # Close the current tab and switch back to main window if we opened a new tab
            if main_window is not None:
                self.driver.close()
                self.driver.switch_to.window(main_window)

        except Exception as e:
            print(f"Error processing item {item_info}: {e}") # pyright: ignore


            # Close the current tab if it's still open and we opened a new tab
            if main_window is not None:
                try:
                    self.driver.close()
                    self.driver.switch_to.window(main_window)
                except:
                    print("Failed to close tab and return to main window")

            # Re-raise to let the caller handle it
            raise

    def download_cursor_packs(self):
        """
        Main method to download all free cursor packs from the shop.
        If specific_url is provided, only that item will be downloaded.
        """
        # If we have a specific URL, download just that item
        if self.specific_url:
            print(f"Downloading specific item: {self.specific_url}")
            # Force download even if it's already been downloaded
            self._process_item_url(self.specific_url, force_download=True)
            return

        # Navigate to the shop page
        self.driver.get("https://ko-fi.com/bentu404/shop")
        print("Navigated to Ko-fi shop")

        # Wait for page to fully load
        time.sleep(2)

        # Scroll and load all items
        total_items = self.scroll_and_load_all_items()

        if total_items == 0:
            print("No items found")
            return

        print(f"Found {total_items} items")

        # Apply skip items
        start_index = self.skip_items
        if start_index > 0:
            print(f"Skipping first {start_index} items as requested")

        # Collect URLs from the shop cards
        shop_card_xpath = '//a[@id="shop-card"]'
        free_buttons = self.wait.until(
            EC.presence_of_all_elements_located((By.XPATH, shop_card_xpath))
        )

        # Extract URLs from the buttons
        item_urls = []
        for button in free_buttons:
            try:
                # Get the URL from the href attribute
                url = button.get_attribute('href')
                if url:
                    item_urls.append(url)
            except Exception as e:
                print(f"Error getting URL from button: {e}")

        print(f"Collected {len(item_urls)} item URLs")

        # Skip items if requested
        if self.skip_items > 0:
            if self.skip_items >= len(item_urls):
                print(f"Skip count ({self.skip_items}) exceeds available items ({len(item_urls)})")
                return

            print(f"Skipping first {self.skip_items} items")
            item_urls = item_urls[self.skip_items:]

        # Store the main window handle
        main_window = self.driver.current_window_handle

        # Process each item URL in a new tab
        for i, url in enumerate(item_urls):
            try:
                print(f"Processing item {i+1+self.skip_items}/{total_items}: {url}")

                # Skip if this URL has already been downloaded
                if self.is_url_downloaded(url):
                    print(f"Skipping already downloaded item: {url}")
                    continue

                self._process_item_url(url, main_window, i+self.skip_items, total_items, force_download=False)

            except Exception as e:
                print(f"Error processing item {i+1+self.skip_items}: {e}")
                print("Skipping this item and continuing...")

                # Close the current tab if it's still open
                try:
                    self.driver.close()
                    self.driver.switch_to.window(main_window)
                except:
                    print("Failed to close tab and return to main window")
                    # Try to recover by going back to the shop page
                    self.driver.get("https://ko-fi.com/bentu404/shop")

    def cleanup(self):
        """Close the browser and perform any necessary cleanup."""
        if hasattr(self, 'driver'):
            self.driver.quit()
            print("Browser closed")


def main():
    """Main function to run the downloader."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Download cursor packs from bentu404's Ko-fi shop")
    parser.add_argument("--skip", type=int, default=0, help="Number of items to skip from the beginning")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    parser.add_argument("--profile", type=str, help="Path to Chromium profile directory")
    parser.add_argument("--download-dir", type=str, help="Directory to save downloaded files")
    parser.add_argument("--skip-downloaded", action="store_true", help="Skip already downloaded items")
    parser.add_argument("--url", type=str, help="Download a specific cursor item by its URL")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode with full traceback")
    parser.add_argument("--migrate", action="store_true", help="Migrate existing tracking data to add missing fields")
    args = parser.parse_args()

    # Get the directory where this script is located
    script_dir = Path(__file__).parent.parent.parent
    download_dir = Path(args.download_dir) if args.download_dir else script_dir / "cursors"

    # Default Chromium profile path (can be customized)
    chromium_profile = args.profile or os.environ.get(
        "CHROMIUM_PROFILE",
        os.path.expanduser("~/.config/chromium")
    )

    print(f"Using Chromium profile: {chromium_profile}")
    print(f"Downloading cursor packs to: {download_dir}")

    if args.skip > 0 and not args.url:
        print(f"Skipping first {args.skip} items")

    if args.url:
        print(f"Downloading specific cursor URL: {args.url}")

    if args.migrate:
        print("Running migration to update tracking data...")

    downloader = KofiCursorDownloader(
        download_dir=download_dir,
        headless=args.headless,
        user_profile=chromium_profile,
        skip_items=args.skip,
        specific_url=args.url
    )

    try:
        if args.migrate:
            # Force regeneration of all names
            print(f"Found {len(downloader.downloaded_cursors)} records to migrate")

            # Ensure all records have updated names
            for cursor in downloader.downloaded_cursors:
                cursor.name = sanitize_name(cursor.filename)

            downloader.save_tracking_data()
            print("Migration completed successfully")
        else:
            # Download the cursor packs
            downloader.download_cursor_packs()
            print("Download process completed")
    except Exception as e:
        if args.debug:
            import traceback
            print(f"An error occurred: {e}")
            print("Full traceback:")
            traceback.print_exc()
        else:
            print(f"An error occurred: {e}")
            print("Run with --debug flag for full traceback")
    finally:
        downloader.cleanup()


if __name__ == "__main__":
    main()
