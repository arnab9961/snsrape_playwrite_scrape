from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Union
from enum import Enum


class AssetClass(str, Enum):
    PERSON = "person"
    ORGANIZATION = "organization"
    LOCATION = "location"
    EVENT = "event"
    INFRASTRUCTURE = "infrastructure"
    TECHNOLOGY = "technology"
    OTHER = "other"


class ReportRequest(BaseModel):
    keywords: List[str] = Field(..., description="Keywords to search for")
    location: Optional[str] = Field(None, description="Location to filter results by")
    asset_class: Optional[AssetClass] = Field(None, description="Type of asset to focus on")


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


class ReportStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class Report(BaseModel):
    id: str
    request: ReportRequest
    status: ReportStatus
    created_at: str
    completed_at: Optional[str] = None
    download_url: Optional[str] = None
    error: Optional[str] = None


class ReportResponse(BaseModel):
    message: str
    report_id: str