import asyncio
import logging
import feedparser
import aiohttp
from typing import List, Dict, Any, Optional
from datetime import datetime
from bs4 import BeautifulSoup

# Update imports to use main.py instead of schemas.py
from app.main import NewsArticle

logger = logging.getLogger(__name__)

class RSSFeedScraper:
    """
    Scraper for RSS feeds from trusted intelligence-related publications
    """
    
    # List of trusted intelligence-related publications with their RSS feed URLs
    FEED_SOURCES = {
        "Reuters": "http://feeds.reuters.com/reuters/worldNews",
        "Al Jazeera": "https://www.aljazeera.com/xml/rss/all.xml",
        "BBC World": "http://feeds.bbci.co.uk/news/world/rss.xml",
        "Foreign Policy": "https://foreignpolicy.com/feed/",
        "The Diplomat": "https://thediplomat.com/feed/",
        "Defense One": "https://www.defenseone.com/rss/",
    }
    
    @staticmethod
    async def fetch_article_content(session: aiohttp.ClientSession, url: str) -> str:
        """Fetch and parse article content from URL"""
        try:
            async with session.get(url, timeout=10) as response:
                if response.status == 200:
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # Remove script and style elements
                    for script in soup(["script", "style"]):
                        script.decompose()
                        
                    # Get the text content
                    paragraphs = soup.find_all('p')
                    content = ' '.join([p.get_text() for p in paragraphs])
                    
                    # Limit content length to avoid massive articles
                    return content[:5000] + "..." if len(content) > 5000 else content
                else:
                    return f"Failed to fetch article content: Status code {response.status}"
        except Exception as e:
            logger.error(f"Error fetching article content from {url}: {str(e)}")
            return "Failed to fetch article content"
    
    @staticmethod
    async def search(keywords: List[str], limit: int = 20) -> List[NewsArticle]:
        """
        Search RSS feeds for articles matching the given keywords.
        
        Args:
            keywords: List of keywords to search for
            limit: Maximum number of results to return
            
        Returns:
            List of news articles formatted as NewsArticle objects
        """
        results = []
        
        # Create a case-insensitive keyword check function
        def contains_keywords(text):
            text_lower = text.lower()
            for keyword in keywords:
                if keyword.lower() in text_lower:
                    return True
            return False
        
        try:
            async with aiohttp.ClientSession() as session:
                for source_name, feed_url in RSSFeedScraper.FEED_SOURCES.items():
                    logger.info(f"Fetching RSS feed: {source_name} - {feed_url}")
                    
                    try:
                        # Parse the feed
                        feed = feedparser.parse(feed_url)
                        
                        # Process the entries
                        for entry in feed.entries:
                            # Skip if we've reached the limit
                            if len(results) >= limit:
                                break
                                
                            title = entry.get('title', '')
                            summary = entry.get('summary', '')
                            
                            # Check if entry matches keywords
                            if contains_keywords(title) or contains_keywords(summary):
                                # Get the link to the full article
                                url = entry.get('link', '')
                                
                                # Get the publication date
                                published = entry.get('published', '')
                                try:
                                    # Try to parse the date into ISO format
                                    if hasattr(entry, 'published_parsed') and entry.published_parsed:
                                        published_parsed = datetime(*entry.published_parsed[:6]).isoformat()
                                    else:
                                        published_parsed = published
                                except Exception:
                                    published_parsed = published
                                
                                # Attempt to get author
                                author = entry.get('author', 'Unknown')
                                
                                # Fetch full content if URL available
                                content = await RSSFeedScraper.fetch_article_content(session, url) if url else summary
                                
                                article = NewsArticle(
                                    title=title,
                                    source=source_name,
                                    content=content,
                                    author=author,
                                    timestamp=published_parsed,
                                    url=url
                                )
                                
                                results.append(article)
                    
                    except Exception as e:
                        logger.error(f"Error processing feed {source_name}: {str(e)}")
                        continue
                
                logger.info(f"Collected {len(results)} news articles from RSS feeds")
                return results
                
        except Exception as e:
            logger.error(f"Error in RSS feed scraping: {str(e)}")
            return []