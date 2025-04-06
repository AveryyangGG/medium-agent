import os
import sys
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Optional, Dict, Any

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config import WEB_APP_HOST, WEB_APP_PORT
from app.db.database import Database
from app.db.vector_db import VectorDatabase
from app.api.summary_utils import generate_article_summary
from app.api.templates import get_home_page, get_search_page, get_detailed_summary_page, get_summary_form

app = FastAPI(title="Medium Agent API", description="API for Medium Articles")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allow all methods
    allow_headers=["*"],  # Allow all headers
)

# Initialize database connections
db = Database()
vector_db = VectorDatabase()

# Models
class ArticleResponse(BaseModel):
    id: str
    title: str
    author: str
    url: str
    published_at: str
    tags: Optional[List[str]] = None
    summary: Optional[str] = None
    content: Optional[str] = None
    is_saved: Optional[bool] = None
    detailed_summary: Optional[str] = None
    user_tags: Optional[List[str]] = None
    user_notes: Optional[str] = None

class SearchQuery(BaseModel):
    query: str
    limit: int = 5

class SummaryRequest(BaseModel):
    url: str

# API Routes
@app.get("/", response_class=HTMLResponse)
async def root():
    """Return a simple welcome page"""
    return get_home_page()

@app.get("/articles", response_model=List[ArticleResponse])
async def get_articles(limit: int = Query(10, ge=1, le=50)):
    """Get recent articles"""
    articles = db.get_recent_articles(limit=limit)
    return articles

@app.get("/articles/{article_id}", response_model=ArticleResponse)
async def get_article(article_id: str):
    """Get a specific article by ID"""
    article = db.get_article(article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    return article

@app.post("/articles/{article_id}/save")
async def save_article(article_id: str):
    """Save an article to the RAG database"""
    article = db.get_article(article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    
    success = vector_db.add_article_to_rag(article_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to save article to RAG database")
    
    return {"message": "Article saved successfully"}

@app.post("/search", response_model=List[Dict[str, Any]])
async def search_articles(query: SearchQuery):
    """Search for articles in the RAG database"""
    try:
        results = vector_db.query_similar_articles(query.query, n_results=query.limit)
        if not results:
            return []
        return results
    except Exception as e:
        print(f"Search error: {e}")
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")

@app.get("/search", response_class=HTMLResponse)
async def search_page():
    """HTML page for searching articles"""
    return get_search_page()

@app.get("/articles/{article_id}/outline", response_class=HTMLResponse)
async def view_article_outline(article_id: str):
    """View a formatted HTML page with the article's detailed summary"""
    article = db.get_article(article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    
    detailed_summary = article.get('detailed_summary', 'No detailed summary available for this article.')
    title = article.get('title', 'Untitled Article')
    author = article.get('author', 'Unknown Author')
    
    return get_detailed_summary_page(article_id, title, author, detailed_summary)

@app.get("/generate-summary", response_class=HTMLResponse)
async def generate_summary_form():
    """Show a form for generating summaries from Medium URLs"""
    return get_summary_form()

@app.post("/api/generate-summary")
async def api_generate_summary(request: SummaryRequest):
    """API endpoint to generate summary from a Medium URL"""
    return await generate_article_summary(request.url) 