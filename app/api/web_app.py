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

# API Routes
@app.get("/", response_class=HTMLResponse)
async def root():
    """Return a simple welcome page"""
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Medium Agent</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                margin: 40px;
                line-height: 1.6;
            }
            h1 {
                color: #333;
                border-bottom: 1px solid #eee;
                padding-bottom: 10px;
            }
            a {
                color: #0066cc;
                text-decoration: none;
            }
            a:hover {
                text-decoration: underline;
            }
            .endpoints {
                background-color: #f5f5f5;
                padding: 20px;
                border-radius: 5px;
                margin-top: 20px;
            }
        </style>
    </head>
    <body>
        <h1>Medium Agent</h1>
        <p>Welcome to the Medium Agent API. Use the following endpoints:</p>
        
        <div class="endpoints">
            <p><a href="/docs">/docs</a> - Interactive API documentation</p>
            <p><a href="/articles">/articles</a> - List recent articles</p>
            <p><a href="/articles/1">/articles/{id}</a> - Get a specific article</p>
            <p>POST to <a href="/search">/search</a> - Search articles</p>
        </div>
    </body>
    </html>
    """
    return html_content

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
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Search Medium Articles</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                margin: 40px auto;
                max-width: 800px;
                line-height: 1.6;
                padding: 0 20px;
            }
            h1 {
                color: #333;
                border-bottom: 1px solid #eee;
                padding-bottom: 10px;
            }
            form {
                margin: 20px 0;
            }
            input[type="text"] {
                width: 70%;
                padding: 10px;
                font-size: 16px;
                border: 1px solid #ddd;
                border-radius: 4px;
            }
            button {
                padding: 10px 20px;
                background-color: #0066cc;
                color: white;
                border: none;
                border-radius: 4px;
                cursor: pointer;
                font-size: 16px;
            }
            button:hover {
                background-color: #004c99;
            }
            #results {
                margin-top: 30px;
            }
            .article {
                background-color: #f9f9f9;
                padding: 15px;
                margin-bottom: 15px;
                border-radius: 5px;
                border-left: 3px solid #0066cc;
            }
            .article h3 {
                margin-top: 0;
                color: #333;
            }
            .article .meta {
                color: #666;
                font-size: 14px;
                margin-bottom: 10px;
            }
            .article .summary {
                margin-top: 10px;
            }
            .article a {
                color: #0066cc;
                text-decoration: none;
            }
            .article a:hover {
                text-decoration: underline;
            }
            .no-results {
                color: #666;
                font-style: italic;
            }
        </style>
        <script>
            async function searchArticles() {
                const query = document.getElementById('search-input').value;
                if (!query) return;
                
                document.getElementById('search-button').disabled = true;
                document.getElementById('search-button').innerText = 'Searching...';
                document.getElementById('results').innerHTML = '<p>Searching for articles...</p>';
                
                try {
                    const response = await fetch('/search', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify({
                            query: query,
                            limit: 10
                        }),
                    });
                    
                    if (!response.ok) {
                        throw new Error(`Error: ${response.status}`);
                    }
                    
                    const data = await response.json();
                    displayResults(data, query);
                } catch (error) {
                    document.getElementById('results').innerHTML = `
                        <div class="no-results">
                            <p>Error searching for articles: ${error.message}</p>
                        </div>
                    `;
                } finally {
                    document.getElementById('search-button').disabled = false;
                    document.getElementById('search-button').innerText = 'Search';
                }
            }
            
            function displayResults(results, query) {
                const resultsDiv = document.getElementById('results');
                
                if (results.length === 0) {
                    resultsDiv.innerHTML = `
                        <div class="no-results">
                            <p>No articles found matching "${query}"</p>
                        </div>
                    `;
                    return;
                }
                
                let html = `<h2>Search Results for "${query}"</h2>`;
                
                results.forEach(article => {
                    html += `
                        <div class="article">
                            <h3><a href="${article.url}" target="_blank">${article.title}</a></h3>
                            <div class="meta">
                                By ${article.author} · Published ${new Date(article.published_at).toLocaleDateString()}
                                ${article.similarity_score ? ` · Relevance: ${(1 - article.similarity_score).toFixed(2)}` : ''}
                            </div>
                            <div class="summary">${article.summary || 'No summary available'}</div>
                            <p>
                                <a href="/articles/${article.id}" target="_blank">View in Medium Agent</a> | 
                                <a href="/articles/${article.id}/outline" target="_blank">View Detailed Outline</a>
                            </p>
                        </div>
                    `;
                });
                
                resultsDiv.innerHTML = html;
            }
            
            // Submit form when Enter key is pressed
            document.addEventListener('DOMContentLoaded', () => {
                const input = document.getElementById('search-input');
                input.addEventListener('keyup', (event) => {
                    if (event.key === 'Enter') {
                        event.preventDefault();
                        searchArticles();
                    }
                });
            });
        </script>
    </head>
    <body>
        <h1>Search Saved Medium Articles</h1>
        <p>Search for articles that have been saved to the RAG database:</p>
        
        <form onsubmit="event.preventDefault(); searchArticles();">
            <input type="text" id="search-input" placeholder="Enter your search query...">
            <button type="submit" id="search-button">Search</button>
        </form>
        
        <div id="results"></div>
        
        <p><a href="/">Back to Home</a></p>
    </body>
    </html>
    """
    return html_content

@app.get("/articles/{article_id}/outline", response_class=HTMLResponse)
async def view_article_outline(article_id: str):
    """View a formatted HTML page with the article's detailed outline"""
    article = db.get_article(article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    
    detailed_summary = article.get('detailed_summary', 'No detailed outline available for this article.')
    title = article.get('title', 'Untitled Article')
    author = article.get('author', 'Unknown Author')
    
    # Format the detailed summary with proper line breaks
    formatted_summary = detailed_summary.replace('\n', '<br>')
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>{title} - Detailed Outline</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                margin: 40px auto;
                max-width: 800px;
                line-height: 1.6;
                padding: 0 20px;
            }}
            h1 {{
                color: #333;
                border-bottom: 1px solid #eee;
                padding-bottom: 10px;
            }}
            .article-meta {{
                color: #666;
                margin-bottom: 20px;
            }}
            .outline-content {{
                background-color: #f9f9f9;
                padding: 20px;
                border-radius: 5px;
                border-left: 4px solid #0066cc;
            }}
            a {{
                color: #0066cc;
                text-decoration: none;
            }}
            a:hover {{
                text-decoration: underline;
            }}
        </style>
    </head>
    <body>
        <h1>{title}</h1>
        <div class="article-meta">By: {author}</div>
        
        <div class="outline-content">
            {formatted_summary}
        </div>
        
        <p><a href="/articles/{article_id}">Back to Article</a></p>
    </body>
    </html>
    """
    return html_content 