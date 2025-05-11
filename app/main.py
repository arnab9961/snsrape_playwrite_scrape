import logging
import asyncio
import os
from typing import Dict, List, Optional
from enum import Enum
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Schema models
class AssetClass(str, Enum):
    PERSON = "person"
    ORGANIZATION = "organization"
    LOCATION = "location"
    EVENT = "event"
    INFRASTRUCTURE = "infrastructure"
    TECHNOLOGY = "technology"
    OTHER = "other"


class SearchRequest(BaseModel):
    keywords: List[str] = Field(..., description="Keywords to search for")
    location: Optional[str] = Field(None, description="Location to filter results by")
    asset_class: Optional[AssetClass] = Field(None, description="Type of asset to focus on")
    days_back: Optional[int] = Field(7, description="Number of days back to search")
    limit_per_source: Optional[int] = Field(50, description="Maximum number of results per source")


class SocialMediaPost(BaseModel):
    source: str
    content: str
    author: str
    timestamp: str
    url: Optional[str] = None
    engagement: Optional[Dict[str, int]] = None
    media_urls: Optional[List[str]] = None


class NewsArticle(BaseModel):
    title: str
    source: str
    content: str
    author: Optional[str] = None
    timestamp: str
    url: str


class ScrapingResult(BaseModel):
    social_media_posts: List[SocialMediaPost] = []
    news_articles: List[NewsArticle] = []
    stats: Dict[str, int] = {}


# Import scrapers
from app.scraper.reddit import RedditScraper
from app.scraper.twitter import TwitterScraper
from app.scraper.telegram import TelegramScraper
from app.scraper.rss import RSSFeedScraper
from app.scraper.facebook import FacebookScraper  # Import the new Facebook scraper

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="BlackGlass Intelligence Platform",
    description="API for scraping OSINT data from various sources",
    version="1.0.0",
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def scrape_data(keywords: List[str], location: Optional[str] = None, 
                     days_back: int = 7, limit_per_source: int = 50) -> ScrapingResult:
    """
    Function to scrape data from all sources with enhanced options
    
    Args:
        keywords: Keywords to search for
        location: Optional location to filter results
        days_back: How many days back to search
        limit_per_source: Maximum results per source
    """
    # Create tasks for all scrapers
    tasks = [
        RedditScraper.search(keywords, location, limit=limit_per_source, days_back=days_back),
        TwitterScraper.search(keywords, location, limit=limit_per_source, days_back=days_back),
        TelegramScraper.search(keywords, limit=limit_per_source, days_back=days_back),
        FacebookScraper.search(keywords, limit=limit_per_source, days_back=days_back),
        RSSFeedScraper.search(keywords, limit=limit_per_source)
    ]
    
    source_names = ["Reddit", "Twitter", "Telegram", "Facebook", "RSS"]
    
    # Run scrapers in parallel
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Process results and handle any exceptions
    scraping_result = ScrapingResult()
    stats = {}
    
    for i, result in enumerate(results):
        source = source_names[i]
        if isinstance(result, Exception):
            logger.error(f"Error in {source} scraper: {str(result)}")
            stats[source] = 0
            continue
            
        # Log and track statistics
        count = len(result)
        stats[source] = count
        if count == 0:
            logger.warning(f"{source} scraper returned no results")
        else:
            logger.info(f"{source} scraper returned {count} results")
            
        if i <= 3:  # Social media scrapers (Reddit, Twitter, Telegram, Facebook)
            scraping_result.social_media_posts.extend(result)
        elif i == 4:  # RSS 
            scraping_result.news_articles.extend(result)
    
    # Add stats to result
    scraping_result.stats = stats
    
    # Log total counts
    logger.info(f"Total social media posts collected: {len(scraping_result.social_media_posts)}")
    logger.info(f"Total news articles collected: {len(scraping_result.news_articles)}")
    
    return scraping_result


@app.get("/api/data", response_model=ScrapingResult)
async def get_all_data(days_back: int = 7, limit_per_source: int = 30):
    """
    GET endpoint: Fetch all data using default keywords with configurable options
    """
    default_keywords = ["osint", "intelligence", "security"]
    logger.info(f"Fetching all data with default keywords: {default_keywords}")
    logger.info(f"Search parameters: days_back={days_back}, limit_per_source={limit_per_source}")
    
    try:
        result = await scrape_data(
            keywords=default_keywords, 
            days_back=days_back, 
            limit_per_source=limit_per_source
        )
        return result
    except Exception as e:
        logger.error(f"Error fetching all data: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error during data fetch: {str(e)}")


@app.post("/api/search", response_model=ScrapingResult)
async def search_with_fields(request: SearchRequest):
    """
    POST endpoint: Search with specific fields (keywords, location, asset class)
    """
    logger.info(f"Searching with fields: {request.dict()}")
    
    try:
        result = await scrape_data(
            keywords=request.keywords, 
            location=request.location,
            days_back=request.days_back,
            limit_per_source=request.limit_per_source
        )
        
        # Filter by asset class if provided
        if request.asset_class:
            # This is a placeholder - in a real implementation, you'd
            # analyze content to determine if it matches the asset class
            logger.info(f"Would filter results by asset class: {request.asset_class}")
            
        return result
    except Exception as e:
        logger.error(f"Error searching with fields: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error during search: {str(e)}")


@app.get("/health")
async def health_check():
    """
    Health check endpoint
    """
    return {"status": "healthy"}