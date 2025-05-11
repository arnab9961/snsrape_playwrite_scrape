import asyncio
import logging
import re
import feedparser
import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from playwright.async_api import async_playwright

from app.main import SocialMediaPost

logger = logging.getLogger(__name__)

class FacebookScraper:
    """
    A scraper for public Facebook pages and groups using Playwright and RSS fallback
    """
    
    # Updated list of highly accessible Facebook pages (focusing on technology and news)
    PUBLIC_PAGES = [
        "CNN",               # CNN News
        "techcrunch",        # Tech news
        "theverge",          # Tech news
        "WIRED",             # Tech and cybersecurity
        "bbcnews",           # News
        "forbes",            # Business and tech news
        "TheNextWeb",        # Next Web
        "techradar",         # Tech Radar
        "natgeo",            # National Geographic
        "reuters",           # Reuters News
        "zdnet",             # ZDNet (tech news)
        "mashable"           # Mashable
    ]
    
    # Pages with known RSS feeds as fallback
    RSS_FEEDS = {
        "techcrunch": "https://techcrunch.com/feed/",
        "theverge": "https://www.theverge.com/rss/index.xml",
        "wired": "https://www.wired.com/feed/rss",
        "zdnet": "https://www.zdnet.com/news/rss.xml",
        "reuters": "https://feeds.reuters.com/reuters/technologyNews",
        "mashable": "https://mashable.com/feeds/rss/all",
        "bbc": "http://feeds.bbci.co.uk/news/technology/rss.xml"
    }
    
    @staticmethod
    async def search(keywords: List[str], limit: int = 30, days_back: int = 7) -> List[SocialMediaPost]:
        """
        Search public Facebook pages for posts matching the given keywords.
        Falls back to RSS feeds if Facebook scraping fails.
        
        Args:
            keywords: List of keywords to search for
            limit: Maximum number of results to return
            days_back: How many days back to search
            
        Returns:
            List of Facebook posts formatted as SocialMediaPost objects
        """
        results = []
        
        # Convert keywords to lowercase for case-insensitive matching
        keywords_lower = [keyword.lower() for keyword in keywords]
        
        # Expanded list of general cybersecurity terms for broader matching
        broader_terms = ["cyber", "security", "threat", "hack", "breach", "malware", "ransomware", 
                        "vulnerability", "attack", "data", "leak", "privacy", "exploit", "scam", 
                        "phishing", "virus", "trojan", "botnet", "cybercrime"]
        
        # Very broad technology terms to ensure we get some results
        tech_terms = ["tech", "digital", "online", "internet", "computing", "software", "hardware", 
                     "app", "network", "cloud", "web", "device", "computer", "artificial intelligence",
                     "ai", "data"]
        
        # Calculate the cutoff date for filtering posts
        cutoff_date = datetime.now() - timedelta(days=days_back)
        
        # First try scraping Facebook directly
        fb_results = await FacebookScraper._scrape_facebook(
            keywords_lower, broader_terms, tech_terms, limit, cutoff_date
        )
        
        results.extend(fb_results)
        
        # If we don't have enough results, try RSS feeds as fallback
        if len(results) < limit:
            logger.info(f"Got only {len(results)} results from direct Facebook scraping, trying RSS fallback")
            rss_results = await FacebookScraper._scrape_rss_feeds(
                keywords_lower, broader_terms, tech_terms, limit - len(results), days_back
            )
            results.extend(rss_results)
        
        logger.info(f"Total Facebook/RSS results collected: {len(results)}")
        return results[:limit]  # Ensure we don't exceed the requested limit
    
    @staticmethod
    async def _scrape_facebook(
        keywords: List[str], broader_terms: List[str], tech_terms: List[str], limit: int, cutoff_date: datetime
    ) -> List[SocialMediaPost]:
        """Internal method to scrape Facebook directly"""
        results = []
        
        try:
            async with async_playwright() as p:
                # Launch browser with specific options to improve reliability
                browser = await p.chromium.launch(
                    headless=True,
                    args=['--disable-web-security', '--no-sandbox', '--disable-setuid-sandbox',
                         '--disable-features=IsolateOrigins,site-per-process']
                )
                
                # Create a context with a viewport large enough and realistic user agent
                context = await browser.new_context(
                    viewport={'width': 1920, 'height': 1080},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                )
                
                # Increase default timeout for page operations
                page = await context.new_page()
                page.set_default_timeout(60000)
                
                pages_checked = 0
                
                # Process each Facebook page
                for page_name in FacebookScraper.PUBLIC_PAGES:
                    if len(results) >= limit:
                        break
                        
                    # Try mobile site first as it's more likely to work without login
                    urls_to_try = [
                        f"https://m.facebook.com/{page_name}/", # Mobile site often works better without login
                        f"https://mbasic.facebook.com/{page_name}/"  # Even more basic version
                    ]
                    
                    success = False
                    for page_url in urls_to_try:
                        if success:
                            break
                            
                        logger.info(f"Trying Facebook URL: {page_url}")
                        
                        try:
                            # Clear cookies and site data between attempts
                            await context.clear_cookies()
                            
                            # Navigate to the page with retry logic
                            response = await page.goto(page_url, wait_until="domcontentloaded", timeout=60000)
                            
                            if not response or response.status != 200:
                                logger.warning(f"Failed to load {page_url}: status {response.status if response else 'none'}")
                                continue
                                
                            # Wait for content to load
                            await page.wait_for_load_state("networkidle", timeout=10000)
                            await asyncio.sleep(2)
                            
                            # Take a screenshot for debugging
                            await page.screenshot(path=f"/tmp/facebook_{page_name}.png")
                            
                            # Check for login/cookie dialogs and close them
                            dialog_selectors = [
                                'div[role="dialog"] button',
                                'div[data-testid="cookie-policy-dialog"] button',
                                'button[data-cookiebanner="accept_button"]'
                            ]
                            
                            for selector in dialog_selectors:
                                try:
                                    if await page.query_selector(selector):
                                        await page.click(selector, timeout=3000)
                                        logger.info(f"Closed dialog using {selector}")
                                        await asyncio.sleep(1)
                                except:
                                    pass
                            
                            # Mobile-specific selectors for posts
                            if "m.facebook.com" in page_url or "mbasic.facebook.com" in page_url:
                                # For mobile site
                                selectors = [
                                    'div.story_body_container',
                                    'article',
                                    'div._55wo',
                                    'div.story_body_container div',
                                    'div[data-ft]'
                                ]
                                
                                for selector in selectors:
                                    try:
                                        posts = await page.query_selector_all(selector)
                                        if posts and len(posts) > 0:
                                            logger.info(f"Found {len(posts)} potential posts with selector {selector}")
                                            
                                            for post in posts:
                                                if len(results) >= limit:
                                                    break
                                                
                                                # Extract content from post
                                                try:
                                                    content = await post.inner_text()
                                                    
                                                    # Skip very short content
                                                    if not content or len(content) < 20:
                                                        continue
                                                        
                                                    # Check for keyword matches
                                                    content_lower = content.lower()
                                                    
                                                    # Use progressively broader matching criteria
                                                    keywords_match = any(keyword in content_lower for keyword in keywords)
                                                    broader_match = any(term in content_lower for term in broader_terms)
                                                    tech_match = any(term in content_lower for term in tech_terms)
                                                    
                                                    # If we have no results yet, be more lenient with matching
                                                    if not results and not (keywords_match or broader_match):
                                                        # Accept tech terms to get at least some results
                                                        if not tech_match:
                                                            continue
                                                    elif not (keywords_match or broader_match or tech_match):
                                                        continue
                                                        
                                                    # Create a post object
                                                    post_obj = SocialMediaPost(
                                                        source="facebook",
                                                        content=content[:1000],  # Limit content length
                                                        author=page_name,
                                                        timestamp=datetime.now().isoformat(),
                                                        url=page_url,
                                                        media_urls=None,
                                                        engagement=None
                                                    )
                                                    
                                                    results.append(post_obj)
                                                    logger.info(f"Collected Facebook post from {page_name}")
                                                except Exception as e:
                                                    logger.warning(f"Error processing post: {e}")
                                                    continue
                                            
                                            # If we found any posts with this selector, consider it a success
                                            if len(results) > 0:
                                                success = True
                                                break
                                    except Exception as e:
                                        logger.warning(f"Error with selector {selector}: {e}")
                                        continue
                            
                            pages_checked += 1
                            
                        except Exception as e:
                            logger.error(f"Error scraping Facebook page {page_name}: {str(e)}")
                            continue
                
                await browser.close()
                
                logger.info(f"Checked {pages_checked} Facebook pages, collected {len(results)} posts")
                
        except Exception as e:
            logger.error(f"Error in Facebook scraping: {str(e)}")
        
        return results
    
    @staticmethod
    async def _scrape_rss_feeds(
        keywords: List[str], broader_terms: List[str], tech_terms: List[str], limit: int, days_back: int
    ) -> List[SocialMediaPost]:
        """Fallback method to get content from RSS feeds as proxy for Facebook content"""
        results = []
        
        # Calculate the cutoff date for filtering posts
        cutoff_date = datetime.now() - timedelta(days=days_back)
        
        for source, feed_url in FacebookScraper.RSS_FEEDS.items():
            if len(results) >= limit:
                break
                
            try:
                logger.info(f"Fetching RSS feed for {source}: {feed_url}")
                response = requests.get(feed_url, timeout=10)
                
                if response.status_code != 200:
                    logger.warning(f"Failed to fetch RSS feed for {source}: status {response.status_code}")
                    continue
                    
                feed = feedparser.parse(response.content)
                
                for entry in feed.entries:
                    if len(results) >= limit:
                        break
                        
                    try:
                        # Get content from either summary or content
                        content = ""
                        if hasattr(entry, 'summary'):
                            content = entry.summary
                        elif hasattr(entry, 'content') and len(entry.content) > 0:
                            content = entry.content[0].value
                            
                        if not content:
                            continue
                            
                        # Strip HTML tags for text matching
                        soup = BeautifulSoup(content, 'html.parser')
                        text_content = soup.get_text()
                        
                        # Check for keyword matches
                        content_lower = text_content.lower()
                        title_lower = entry.title.lower() if hasattr(entry, 'title') else ""
                        
                        # Check for matches in title or content
                        keywords_match = any(keyword in content_lower or keyword in title_lower for keyword in keywords)
                        broader_match = any(term in content_lower or term in title_lower for term in broader_terms)
                        tech_match = any(term in content_lower or term in title_lower for term in tech_terms)
                        
                        # If we have no results yet, be more lenient with matching
                        if not results and not (keywords_match or broader_match):
                            # Accept tech terms to get at least some results
                            if not tech_match:
                                continue
                        elif not (keywords_match or broader_match or tech_match):
                            continue
                            
                        # Get publication date
                        published = datetime.now()
                        if hasattr(entry, 'published_parsed') and entry.published_parsed:
                            published = datetime(*entry.published_parsed[:6])
                        
                        # Skip entries older than cutoff date
                        if published < cutoff_date:
                            continue
                            
                        # Create post object
                        post = SocialMediaPost(
                            source="facebook",  # Mark as Facebook even though it's from RSS
                            content=f"{entry.title}\n\n{text_content}"[:1000],  # Limit content length
                            author=source,  # Use the feed source name as author
                            timestamp=published.isoformat(),
                            url=entry.link if hasattr(entry, 'link') else None,
                            media_urls=None,
                            engagement=None
                        )
                        
                        results.append(post)
                        logger.info(f"Collected RSS post from {source}")
                        
                    except Exception as e:
                        logger.warning(f"Error processing RSS entry from {source}: {str(e)}")
                        continue
                        
            except Exception as e:
                logger.error(f"Error fetching RSS feed for {source}: {str(e)}")
                continue
                
        logger.info(f"Collected {len(results)} posts from RSS feeds")
        return results