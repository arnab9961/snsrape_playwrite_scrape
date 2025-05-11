import asyncio
import logging
import re
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from playwright.async_api import async_playwright

# Update imports to use main.py instead of schemas.py
from app.main import SocialMediaPost

logger = logging.getLogger(__name__)

class TelegramScraper:
    """
    A scraper for public Telegram channels using Playwright
    """
    
    # Updated list of public Telegram channels that are verified to be accessible
    PUBLIC_CHANNELS = [
        "telegram",         # Official Telegram channel
        "durov",            # Pavel Durov's channel
        "cnn",              # CNN news
        "bbcnews",          # BBC News
        "cryptonewscom",    # Crypto News
        "cybersecuritynews1", # Cybersecurity News
        "exploitzone",      # Exploit news
        "secnews1",         # Security News
        "threatpost",       # Threat Post
        "darkarmy",         # Dark Army
        "hackernews",       # Hacker News
        "thenextweb"        # The Next Web
    ]
    
    @staticmethod
    async def search(keywords: List[str], limit: int = 30, days_back: int = 7) -> List[SocialMediaPost]:
        """
        Search public Telegram channels for posts matching the given keywords.
        
        Args:
            keywords: List of keywords to search for
            limit: Maximum number of results to return
            days_back: How many days back to search
            
        Returns:
            List of Telegram posts formatted as SocialMediaPost objects
        """
        results = []
        
        # Convert keywords to lowercase for case-insensitive matching
        keywords_lower = [keyword.lower() for keyword in keywords]
        
        # Add more general keywords to increase chance of matches
        broader_keywords = ["security", "intelligence", "cyber", "threat", "hack", "breach", "malware", 
                           "ransomware", "attack", "vulnerability", "exploit", "virus", "phishing", "data"]
        
        # Calculate the cutoff date for filtering posts
        cutoff_date = datetime.now() - timedelta(days=days_back)
        
        try:
            async with async_playwright() as p:
                # Launch browser with specific options to improve reliability
                browser = await p.chromium.launch(
                    headless=True, 
                    args=['--disable-web-security', '--no-sandbox', '--disable-setuid-sandbox']
                )
                
                # Create a context with a viewport large enough to see content
                context = await browser.new_context(
                    viewport={'width': 1920, 'height': 1080},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36'
                )
                
                page = await context.new_page()
                
                # Increase timeout for better reliability
                page.set_default_timeout(60000)
                
                channels_checked = 0
                
                # Process each channel
                for channel in TelegramScraper.PUBLIC_CHANNELS:
                    if len(results) >= limit:
                        break
                        
                    # Use the public channel URL format
                    channel_url = f"https://t.me/s/{channel}"
                    logger.info(f"Scraping Telegram channel: {channel_url}")
                    
                    try:
                        # Navigate to the channel with retry logic
                        max_retries = 3
                        retry_count = 0
                        success = False
                        
                        while retry_count < max_retries and not success:
                            try:
                                # Clear cookies between attempts
                                await context.clear_cookies()
                                
                                # Take a screenshot before navigation for debugging
                                screenshot_path = f"/tmp/telegram_before_{channel}.png"
                                await page.screenshot(path=screenshot_path)
                                logger.info(f"Saved screenshot before navigation to {screenshot_path}")
                                
                                # Navigate to the channel with a longer timeout
                                response = await page.goto(channel_url, wait_until="networkidle", timeout=60000)
                                
                                if response and response.status == 200:
                                    # Take a screenshot after navigation for debugging
                                    screenshot_path = f"/tmp/telegram_after_{channel}.png"
                                    await page.screenshot(path=screenshot_path)
                                    logger.info(f"Saved screenshot after navigation to {screenshot_path}")
                                    
                                    # Wait a bit for JavaScript to execute
                                    await asyncio.sleep(3)
                                    
                                    # Check if we landed on the actual channel page
                                    channel_indicators = [
                                        '.tgme_channel_info',
                                        '.tgme_header',
                                        '.tgme_page_title'
                                    ]
                                    
                                    for indicator in channel_indicators:
                                        if await page.query_selector(indicator) is not None:
                                            success = True
                                            break
                                            
                                    # If we don't find standard indicators, check if any messages are present
                                    if not success and await page.query_selector('.tgme_widget_message') is not None:
                                        success = True
                                        
                                if not success:
                                    # If we hit a "channel not found" page, move on
                                    error_indicators = [
                                        '.tgme_page_description:has-text("You are trying to access a private channel")',
                                        '.tgme_page_description:has-text("This channel is private")',
                                        'div:has-text("Sorry, this channel is no longer accessible.")'
                                    ]
                                    
                                    for indicator in error_indicators:
                                        if await page.query_selector(indicator) is not None:
                                            logger.warning(f"Channel {channel} not found or is private")
                                            retry_count = max_retries  # Skip further retries
                                            break
                                            
                                    if retry_count < max_retries:
                                        retry_count += 1
                                        await asyncio.sleep(2)
                            except Exception as e:
                                logger.warning(f"Attempt {retry_count + 1} failed for channel {channel}: {str(e)}")
                                retry_count += 1
                                await asyncio.sleep(2)
                                
                        if not success:
                            logger.error(f"Failed to access channel {channel} after {max_retries} attempts")
                            channels_checked += 1
                            continue
                            
                        # Channel loaded successfully, now find messages
                        # Scroll a few times to load more content
                        for _ in range(5):
                            await page.evaluate("window.scrollBy(0, 1000)")
                            await asyncio.sleep(1)
                            
                        # Try multiple selector approaches to find messages
                        message_selectors = [
                            '.tgme_widget_message',
                            '.tgme_widget_message_wrap',
                            '.js-widget_message',
                            'div.tgme_widget_message_bubble',
                            'article[role="article"]'
                        ]
                        
                        message_elements = []
                        for selector in message_selectors:
                            try:
                                elements = await page.query_selector_all(selector)
                                if elements and len(elements) > 0:
                                    message_elements = elements
                                    logger.info(f"Found {len(elements)} messages with selector {selector}")
                                    break
                            except Exception as e:
                                logger.warning(f"Error finding messages with selector {selector}: {str(e)}")
                                continue
                                
                        # If still no messages found, continue to next channel
                        if not message_elements:
                            logger.warning(f"No message elements found in channel {channel}")
                            channels_checked += 1
                            continue
                            
                        channels_checked += 1
                        messages_checked = 0
                        messages_collected = 0
                        
                        # Process each message
                        for message_element in message_elements:
                            if len(results) >= limit:
                                break
                                
                            try:
                                messages_checked += 1
                                
                                # Try different selectors for content
                                content_selectors = [
                                    '.tgme_widget_message_text',
                                    '.js-message_text',
                                    '.message_media_view_wrap',
                                    'div.tgme_widget_message_text',
                                    'div[dir="auto"]'
                                ]
                                
                                content = ""
                                for selector in content_selectors:
                                    content_element = await message_element.query_selector(selector)
                                    if content_element:
                                        content = await content_element.inner_text()
                                        break
                                
                                # If no content found with specific selectors, try to get all text
                                if not content:
                                    content = await message_element.inner_text()
                                
                                if not content:
                                    continue
                                    
                                # Check if content contains any of the keywords (with broader matching)
                                content_lower = content.lower()
                                keywords_match = any(keyword in content_lower for keyword in keywords_lower)
                                broader_match = any(keyword in content_lower for keyword in broader_keywords)
                                
                                # Accept if matches user keywords or broader keywords
                                if not keywords_match and not broader_match:
                                    continue
                                
                                # Get post date
                                date_element = await message_element.query_selector('.tgme_widget_message_date time')
                                timestamp = datetime.now().isoformat()
                                if date_element:
                                    datetime_attr = await date_element.get_attribute('datetime')
                                    if datetime_attr:
                                        timestamp = datetime_attr
                                        
                                # Get post URL
                                url = None
                                link_element = await message_element.query_selector('.tgme_widget_message_date a')
                                if link_element:
                                    url = await link_element.get_attribute('href')
                                
                                # Extract media URLs if available
                                media_urls = []
                                
                                # Check for photos
                                photo_elements = await message_element.query_selector_all('.tgme_widget_message_photo_wrap')
                                for photo in photo_elements:
                                    style = await photo.get_attribute('style')
                                    if style:
                                        # Extract URL from the background-image CSS property
                                        url_match = re.search(r'url\([\'"]?([^\'"]*)[\'"]?\)', style)
                                        if url_match and url_match.group(1):
                                            media_urls.append(url_match.group(1))
                                
                                # Check for regular images
                                img_elements = await message_element.query_selector_all('img')
                                for img in img_elements:
                                    img_src = await img.get_attribute('src')
                                    if img_src and not any(img_src in url for url in media_urls):
                                        media_urls.append(img_src)
                                
                                # Create post object
                                post = SocialMediaPost(
                                    source="telegram",
                                    content=content,
                                    author=channel,
                                    timestamp=timestamp,
                                    url=url,
                                    media_urls=media_urls if media_urls else None,
                                    engagement=None  # Telegram doesn't provide engagement metrics for public channels
                                )
                                
                                results.append(post)
                                messages_collected += 1
                                
                            except Exception as e:
                                logger.error(f"Error processing Telegram message in {channel}: {str(e)}")
                                continue
                                
                        logger.info(f"Channel {channel}: checked {messages_checked} messages, collected {messages_collected}")
                    
                    except Exception as e:
                        logger.error(f"Error scraping Telegram channel {channel}: {str(e)}")
                        continue
                
                await browser.close()
                
                logger.info(f"Checked {channels_checked} Telegram channels, collected {len(results)} posts")
                return results
                
        except Exception as e:
            logger.error(f"Error in Telegram scraping: {str(e)}")
            return []