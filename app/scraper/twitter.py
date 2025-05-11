import asyncio
import logging
import re
import ssl
import snscrape.modules.twitter as sntwitter
import requests
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from playwright.async_api import async_playwright
# Adding urllib3 to disable SSL warnings
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from app.main import SocialMediaPost

logger = logging.getLogger(__name__)

# Monkey patch SSL verification in SNScrape's requests session
original_init = sntwitter.TwitterSearchScraper.__init__
def patched_init(self, query, **kwargs):
    original_init(self, query)
    # Disable SSL certificate verification in SNScrape's session
    self._session.verify = False
    # Add headers to mimic a regular browser
    self._session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
    })
# Apply the monkey patch
sntwitter.TwitterSearchScraper.__init__ = patched_init

class TwitterScraper:
    """
    A scraper for Twitter/X posts using snscrape with Playwright fallback
    """
    
    # List of Twitter accounts to follow if API-based search fails
    ACCOUNTS_TO_FOLLOW = [
        "thehackernews",
        "malwrhunterteam",
        "threatpost",
        "nixcraft",
        "securityweek",
        "CVEnew",
        "USCERT_gov",
        "MalwarePatrol",
        "NCSC"
    ]
    
    @staticmethod
    async def search(keywords: List[str], location: Optional[str] = None, 
                    limit: int = 50, days_back: int = 7) -> List[SocialMediaPost]:
        """
        Search Twitter for posts matching the given keywords and location.
        First tries snscrape, then falls back to Playwright if needed.
        
        Args:
            keywords: List of keywords to search for
            location: Optional location to filter results
            limit: Maximum number of results to return
            days_back: How many days back to search
            
        Returns:
            List of Twitter posts formatted as SocialMediaPost objects
        """
        # Try with snscrape first
        try:
            results = await TwitterScraper._search_with_snscrape(keywords, location, limit, days_back)
            if results and len(results) > 0:
                return results
            else:
                logger.warning("SNScrape returned no Twitter results, trying Playwright fallback")
        except Exception as e:
            logger.error(f"Error with SNScrape for Twitter: {str(e)}. Trying Playwright fallback")
        
        # If snscrape fails or returns no results, try with Playwright
        try:
            return await TwitterScraper._search_with_playwright(keywords, limit, days_back)
        except Exception as e:
            logger.error(f"Both Twitter scraping methods failed: {str(e)}")
            return []
    
    @staticmethod
    async def _search_with_snscrape(keywords: List[str], location: Optional[str] = None, 
                                  limit: int = 50, days_back: int = 7) -> List[SocialMediaPost]:
        """
        Search Twitter using SNScrape library with SSL verification disabled
        """
        results = []
        
        # Construct the search query
        search_query = " OR ".join([f'"{keyword}"' for keyword in keywords])
        
        # Add location to query if provided
        if location:
            search_query += f' near:"{location}" within:50km'
        
        # Set time range
        since_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
        search_query += f" since:{since_date}"
        
        logger.info(f"Searching Twitter with SNScrape query: {search_query}")
        
        # Create scraper and get results with SSL verification disabled
        scraper = sntwitter.TwitterSearchScraper(search_query)
        posts_collected = 0
        
        try:
            for tweet in scraper.get_items():
                if posts_collected >= limit:
                    break
                
                engagement = {
                    "likes": tweet.likeCount if hasattr(tweet, 'likeCount') else 0,
                    "replies": tweet.replyCount if hasattr(tweet, 'replyCount') else 0,
                    "retweets": tweet.retweetCount if hasattr(tweet, 'retweetCount') else 0
                }
                
                # Extract media URLs if available
                media_urls = []
                if hasattr(tweet, 'media') and tweet.media:
                    for media in tweet.media:
                        if hasattr(media, 'fullUrl') and media.fullUrl:
                            media_urls.append(media.fullUrl)
                
                result = SocialMediaPost(
                    source="twitter",
                    content=tweet.content if hasattr(tweet, 'content') else "",
                    author=tweet.user.username if hasattr(tweet, 'user') and hasattr(tweet.user, 'username') else "Unknown",
                    timestamp=tweet.date.isoformat() if hasattr(tweet, 'date') else "Unknown",
                    url=f"https://twitter.com/{tweet.user.username}/status/{tweet.id}" if hasattr(tweet, 'id') and hasattr(tweet, 'user') else None,
                    engagement=engagement,
                    media_urls=media_urls if media_urls else None
                )
                
                results.append(result)
                posts_collected += 1
                
            logger.info(f"Collected {len(results)} Twitter posts via SNScrape")
            return results
        except Exception as e:
            logger.error(f"Error during SNScrape tweet collection: {str(e)}")
            raise
    
    @staticmethod
    async def _search_with_playwright(keywords: List[str], limit: int = 50, days_back: int = 7) -> List[SocialMediaPost]:
        """
        Fallback method to scrape Twitter using Playwright
        """
        results = []
        keywords_lower = [keyword.lower() for keyword in keywords]
        cutoff_date = datetime.now() - timedelta(days=days_back)
        
        logger.info(f"Searching Twitter with Playwright fallback")
        
        try:
            async with async_playwright() as p:
                # Launch browser in headless mode
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context()
                page = await context.new_page()
                
                # Process each Twitter account
                for account in TwitterScraper.ACCOUNTS_TO_FOLLOW:
                    if len(results) >= limit:
                        break
                        
                    account_url = f"https://twitter.com/{account}"
                    logger.info(f"Scraping Twitter account: {account_url}")
                    
                    try:
                        # Navigate to the account page
                        await page.goto(account_url, wait_until="networkidle", timeout=30000)
                        
                        # For Twitter we need to scroll to load more tweets
                        for _ in range(5):
                            await page.evaluate("window.scrollBy(0, 1000)")
                            await asyncio.sleep(1)
                        
                        # Find all tweets - Twitter structure changes frequently, so we need multiple selectors
                        tweet_selectors = [
                            'article[data-testid="tweet"]',
                            'div[data-testid="tweet"]',
                            'div[data-testid="tweetText"]'
                        ]
                        
                        tweet_elements = []
                        for selector in tweet_selectors:
                            elements = await page.query_selector_all(selector)
                            if elements and len(elements) > 0:
                                tweet_elements = elements
                                logger.info(f"Found {len(elements)} tweets with selector {selector}")
                                break
                        
                        if not tweet_elements:
                            logger.warning(f"No tweets found for {account}")
                            continue
                        
                        # Process tweets
                        for tweet_element in tweet_elements:
                            if len(results) >= limit:
                                break
                                
                            try:
                                # Get tweet text
                                text_element = await tweet_element.query_selector('div[data-testid="tweetText"]') or tweet_element
                                tweet_text = await text_element.inner_text() if text_element else ""
                                
                                # Check if tweet contains any keywords
                                if not any(keyword in tweet_text.lower() for keyword in keywords_lower):
                                    continue
                                
                                # Try to extract engagement metrics
                                engagement = {"likes": 0, "retweets": 0, "replies": 0}
                                engagement_selectors = {
                                    "likes": 'div[data-testid="like"]',
                                    "retweets": 'div[data-testid="retweet"]',
                                    "replies": 'div[data-testid="reply"]'
                                }
                                
                                for metric, selector in engagement_selectors.items():
                                    try:
                                        metric_element = await tweet_element.query_selector(selector)
                                        if metric_element:
                                            metric_text = await metric_element.inner_text()
                                            # Extract the number from text like "10K" or "5"
                                            number_match = re.search(r'(\d+(?:\.\d+)?)(K|M)?', metric_text)
                                            if number_match:
                                                value = float(number_match.group(1))
                                                if number_match.group(2) == 'K':
                                                    value *= 1000
                                                elif number_match.group(2) == 'M':
                                                    value *= 1000000
                                                engagement[metric] = int(value)
                                    except:
                                        pass
                                
                                # Extract media if available
                                media_urls = []
                                image_elements = await tweet_element.query_selector_all('img[src*="pbs.twimg.com/media"]')
                                for img in image_elements:
                                    img_src = await img.get_attribute("src")
                                    if img_src:
                                        media_urls.append(img_src)
                                
                                # Try to get tweet URL
                                url = None
                                timestamp_element = await tweet_element.query_selector('time')
                                if timestamp_element:
                                    link = await timestamp_element.evaluate('(node) => node.parentElement.href')
                                    if link:
                                        url = link
                                
                                # Create post object
                                post = SocialMediaPost(
                                    source="twitter",
                                    content=tweet_text,
                                    author=account,
                                    timestamp=datetime.now().isoformat(),  # We don't have the actual timestamp
                                    url=url,
                                    engagement=engagement,
                                    media_urls=media_urls if media_urls else None
                                )
                                
                                results.append(post)
                                
                            except Exception as e:
                                logger.error(f"Error processing Twitter tweet: {str(e)}")
                                continue
                    
                    except Exception as e:
                        logger.error(f"Error scraping Twitter account {account}: {str(e)}")
                        continue
                
                await browser.close()
                
                logger.info(f"Collected {len(results)} Twitter posts via Playwright")
                return results
                
        except Exception as e:
            logger.error(f"Error in Twitter Playwright scraping: {str(e)}")
            return []