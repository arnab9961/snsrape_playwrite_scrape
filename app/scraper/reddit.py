import asyncio
import logging
import praw
import os
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import time
import random
from prawcore import NotFound, Forbidden, RequestException, ServerError

# Update imports to use main.py instead of schemas.py
from app.main import SocialMediaPost

logger = logging.getLogger(__name__)

# Reddit API credentials - read from environment variables without defaults
REDDIT_CLIENT_ID = os.environ.get('REDDIT_CLIENT_ID')
REDDIT_CLIENT_SECRET = os.environ.get('REDDIT_CLIENT_SECRET')
REDDIT_USER_AGENT = os.environ.get('REDDIT_USER_AGENT')

class RedditScraper:
    """
    A scraper for Reddit posts using PRAW
    """
    
    # Add popular subreddits related to cybersecurity and intelligence
    POPULAR_SUBREDDITS = [
        "cybersecurity",
        "netsec",
        "osint",
        "intelligence",
        "InfoSecNews", 
        "privacy",
        "security",
        "hacking",
        "technology",
        "AskNetsec",
        "CompTIA",
        "sysadmin",
        "blueteamsec",
        "blackhat"
    ]
    
    @staticmethod
    async def search(keywords: List[str], location: Optional[str] = None, 
                    limit: int = 50, days_back: int = 7) -> List[SocialMediaPost]:
        """
        Search Reddit for posts matching the given keywords and location.
        
        Args:
            keywords: List of keywords to search for
            location: Optional location to filter results
            limit: Maximum number of results to return
            days_back: How many days back to search
            
        Returns:
            List of Reddit posts formatted as SocialMediaPost objects
        """
        # First try with searching specific subreddits (more reliable)
        results = await RedditScraper._search_subreddits(keywords, limit, days_back)
        
        # If results are still limited, try searching top posts
        if len(results) < limit * 0.5:  # If we got less than 50% of requested limit
            logger.info(f"Subreddit search returned limited results ({len(results)}), trying top posts")
            top_results = await RedditScraper._search_top_posts(keywords, limit - len(results), days_back)
            results.extend(top_results)
            
        return results
    
    @staticmethod
    async def _get_reddit_instance():
        """Get a Reddit API instance"""
        try:
            # Create a read-only Reddit instance
            reddit = praw.Reddit(
                client_id=REDDIT_CLIENT_ID,
                client_secret=REDDIT_CLIENT_SECRET,
                user_agent=REDDIT_USER_AGENT,
                check_for_async=False,  # Important for using PRAW in async code
            )
            return reddit
        except Exception as e:
            logger.error(f"Error creating Reddit instance: {str(e)}")
            return None
    
    @staticmethod
    async def _create_social_media_post(post) -> SocialMediaPost:
        """Convert a PRAW post to our SocialMediaPost format"""
        # Extract media URLs if available
        media_urls = []
        
        # Check for media
        if hasattr(post, 'url') and post.url:
            # Check if URL is an image
            if any(post.url.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif']):
                media_urls.append(post.url)
            
            # For galleries, try to extract images
            if hasattr(post, 'is_gallery') and post.is_gallery:
                if hasattr(post, 'media_metadata'):
                    for media_id, media_data in post.media_metadata.items():
                        if 's' in media_data and 'u' in media_data['s']:
                            media_urls.append(media_data['s']['u'])
        
        # Create post object with engagement metrics
        try:
            engagement = {
                "upvotes": post.score if hasattr(post, 'score') else 0,
                "comments": len(post.comments) if hasattr(post, 'comments') else 0
            }
            
            # Format post creation time
            timestamp = datetime.fromtimestamp(post.created_utc).isoformat() if hasattr(post, 'created_utc') else datetime.now().isoformat()
            
            # Get content (combining title and selftext if available)
            content = post.title
            if hasattr(post, 'selftext') and post.selftext:
                content += f"\n\n{post.selftext}"
                
            result = SocialMediaPost(
                source="reddit",
                content=content,
                author=post.author.name if hasattr(post, 'author') and post.author else "Unknown",
                timestamp=timestamp,
                url=f"https://www.reddit.com{post.permalink}" if hasattr(post, 'permalink') else None,
                engagement=engagement,
                media_urls=media_urls if media_urls else None
            )
            
            return result
        except Exception as e:
            logger.error(f"Error creating SocialMediaPost from Reddit post: {str(e)}")
            return None
    
    @staticmethod
    async def _search_subreddits(keywords: List[str], limit: int = 50, days_back: int = 7) -> List[SocialMediaPost]:
        """
        Search specific cybersecurity and intelligence subreddits
        """
        results = []
        posts_collected = 0
        keywords_lower = [keyword.lower() for keyword in keywords]
        
        # Create a Reddit instance
        reddit = await RedditScraper._get_reddit_instance()
        if not reddit:
            logger.error("Failed to create Reddit instance")
            return results
            
        # Calculate timestamp for filtering by date
        cutoff_timestamp = (datetime.now() - timedelta(days=days_back)).timestamp()
        
        # Define how many subreddits to try (to avoid hitting rate limits)
        max_subreddits = min(10, len(RedditScraper.POPULAR_SUBREDDITS))
        
        # Shuffle the subreddits to get different ones each time
        subreddits_to_check = random.sample(RedditScraper.POPULAR_SUBREDDITS, max_subreddits)
        
        for subreddit_name in subreddits_to_check:
            if posts_collected >= limit:
                break
                
            logger.info(f"Searching subreddit r/{subreddit_name}")
            
            try:
                subreddit = reddit.subreddit(subreddit_name)
                
                # Try different sorting methods
                for sort_method in [subreddit.new, subreddit.hot, subreddit.rising]:
                    if posts_collected >= limit:
                        break
                        
                    try:
                        # Get posts with this sorting method
                        for post in sort_method(limit=25):  # Limit to 25 posts per method to avoid overloading
                            # Skip if post is too old
                            if post.created_utc < cutoff_timestamp:
                                continue
                                
                            # Only process if post matches keywords
                            title_lower = post.title.lower()
                            selftext_lower = post.selftext.lower() if hasattr(post, 'selftext') else ""
                            
                            # Check if post contains any keywords in title or content
                            if any(keyword in title_lower or keyword in selftext_lower for keyword in keywords_lower):
                                social_post = await RedditScraper._create_social_media_post(post)
                                if social_post:
                                    results.append(social_post)
                                    posts_collected += 1
                                    
                                    if posts_collected >= limit:
                                        break
                    except (NotFound, Forbidden, RequestException, ServerError) as e:
                        logger.warning(f"Error with sort method in r/{subreddit_name}: {str(e)}")
                        continue
                        
            except Exception as e:
                logger.error(f"Error searching subreddit r/{subreddit_name}: {str(e)}")
                # Sleep a bit to respect rate limits
                await asyncio.sleep(2)
                continue
            
            # Sleep between subreddits to avoid hitting rate limits
            await asyncio.sleep(1)
        
        logger.info(f"Collected {len(results)} Reddit posts from subreddits")
        return results
        
    @staticmethod
    async def _search_top_posts(keywords: List[str], limit: int = 20, days_back: int = 7) -> List[SocialMediaPost]:
        """
        Search top posts from Reddit (not limited to specific subreddits)
        """
        results = []
        posts_collected = 0
        keywords_lower = [keyword.lower() for keyword in keywords]
        
        # Create a Reddit instance
        reddit = await RedditScraper._get_reddit_instance()
        if not reddit:
            return results
            
        # Calculate timestamp for filtering by date
        cutoff_timestamp = (datetime.now() - timedelta(days=days_back)).timestamp()
        
        try:
            # Try searching directly with Reddit's search functionality
            search_query = " OR ".join(keywords)
            
            # Search all of Reddit
            for post in reddit.subreddit("all").search(search_query, sort="relevance", time_filter="week", limit=50):
                # Skip if post is too old
                if post.created_utc < cutoff_timestamp:
                    continue
                    
                social_post = await RedditScraper._create_social_media_post(post)
                if social_post:
                    results.append(social_post)
                    posts_collected += 1
                    
                    if posts_collected >= limit:
                        break
                        
        except Exception as e:
            logger.error(f"Error in general Reddit search: {str(e)}")
            
        logger.info(f"Collected {len(results)} Reddit posts from top posts search")
        return results