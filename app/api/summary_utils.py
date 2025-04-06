import os
import sys
import uuid
from datetime import datetime
import requests
from fastapi import HTTPException
from bs4 import BeautifulSoup
from typing import Dict, Any, Tuple

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from app.db.database import Database
from app.services.medium_service import MediumService
from app.services.summarization_service import SummarizationService

# Initialize services
db = Database()
medium_service = MediumService()
summarization_service = SummarizationService()

def validate_medium_url(url: str) -> bool:
    """Validate if the URL is from Medium or its publications"""
    valid_domains = [
        "https://medium.com/",
        "https://towardsdatascience.com/",
        "https://betterhumans.pub/",
        "https://www.freecodecamp.org/"
    ]
    return any(url.startswith(domain) for domain in valid_domains)

async def generate_article_summary(url: str) -> Dict[str, Any]:
    """Generate summary and detailed information for a Medium article URL"""
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")
    
    # Validate URL format
    #if not validate_medium_url(url):
    #    raise HTTPException(status_code=400, detail="Invalid Medium URL")
    
    try:
        # Extract content from URL
        content, claps_count, responses_count = medium_service.extract_content_from_url(url)
        
        if not content:
            raise HTTPException(status_code=404, detail="Could not extract article content")
        
        # Create temporary article object
        article = {
            'id': str(uuid.uuid4()),
            'title': "Medium Article",
            'author': "Unknown Author",
            'url': url,
            'published_at': datetime.now().isoformat(),
            'tags': None,
            'content': content,
            'summary': None,
            'claps': claps_count,
            'responses': responses_count
        }
        
        # Try to extract better title and author from the page
        try:
            response = requests.get(url, cookies=medium_service.cookies, headers=medium_service.headers)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                title_elem = soup.find('title')
                if title_elem and title_elem.text:
                    # Clean title string (remove Medium suffix etc)
                    title = title_elem.text.split('|')[0].strip()
                    article['title'] = title
                    
                # Try to extract author
                author_elem = soup.find('meta', {'name': 'author'})
                if author_elem and author_elem.get('content'):
                    article['author'] = author_elem.get('content')
        except Exception as e:
            print(f"Error extracting title: {e}")
            # Continue with default title
        
        # Generate detailed outline
        detailed_summary = summarization_service.create_detailed_outline(article)
        
        if not detailed_summary:
            raise HTTPException(status_code=500, detail="Failed to generate summary")
        
        # Generate summary and bullet points
        summary, bullet_points = summarization_service.summarize_article(article)
        formatted_summary = summarization_service.format_summary_with_bullets(summary, bullet_points)
        
        # Save the article with detailed summary and formatted summary
        article['summary'] = formatted_summary
        article['detailed_summary'] = detailed_summary
        
        # Save the article to the database for later use
        db.add_article(article)
        
        # Return the processed article data
        return {
            "id": article['id'],
            "title": article['title'],
            "author": article['author'],
            "url": url,
            "claps": claps_count,
            "responses": responses_count,
            "summary": formatted_summary,
            "detailed_summary": detailed_summary
        }
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        print(f"Error generating summary: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate summary: {str(e)}") 