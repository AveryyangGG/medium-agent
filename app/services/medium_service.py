import feedparser
import requests
import hashlib
import uuid
from datetime import datetime
import os
import sys
from bs4 import BeautifulSoup
import re
import json

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config import TOP_ARTICLES_COUNT, MEDIUM_COOKIES

class MediumService:
    def __init__(self):
        self.top_feeds = [
            "https://medium.com/feed/tag/programming",
            "https://medium.com/feed/tag/technology",
            "https://medium.com/feed/tag/data-science",
            "https://medium.com/feed/tag/artificial-intelligence",
            "https://medium.com/feed/tag/machine-learning",
            "https://medium.com/feed/tag/software-development"
        ]
        
        self.popular_feeds = [
            "https://medium.com/feed/tag/technology/popular",
            "https://medium.com/feed/tag/programming/popular",
            "https://medium.com/feed/tag/artificial-intelligence/popular"
        ]
        
        # Set up cookies for authenticated requests
        self.cookies = self._parse_cookies(MEDIUM_COOKIES)
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Referer': 'https://medium.com/',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
        }
    
    def _parse_cookies(self, cookie_string):
        """Parse cookie string into a dictionary"""
        if not cookie_string:
            return {}
            
        cookies = {}
        for item in cookie_string.split(';'):
            if '=' in item:
                key, value = item.strip().split('=', 1)
                cookies[key] = value
        return cookies
    
    def extract_content_from_url(self, url):
        """Extract content from Medium article URL using cookies for authentication"""
        try:
            # Make request with cookies
            response = requests.get(
                url, 
                cookies=self.cookies, 
                headers=self.headers
            )
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 提取掌聲（claps）數量
            claps_count = 0
            claps_elements = soup.find_all(text=re.compile(r'\d+K? claps'))
            if claps_elements:
                # 取第一個匹配元素
                claps_text = claps_elements[0].strip()
                # 轉換格式如 "2.1K claps" 或 "150 claps"
                claps_value = claps_text.split(' ')[0]
                if 'K' in claps_value:
                    # 如果是千位數，例如"2.1K"，轉換為數字
                    claps_count = int(float(claps_value.replace('K', '')) * 1000)
                else:
                    # 直接轉換
                    try:
                        claps_count = int(claps_value)
                    except ValueError:
                        claps_count = 0
            
            # 提取回應（responses）數量
            responses_count = 0
            responses_elements = soup.find_all(text=re.compile(r'\d+ responses'))
            if responses_elements:
                responses_text = responses_elements[0].strip()
                try:
                    responses_count = int(responses_text.split(' ')[0])
                except ValueError:
                    responses_count = 0
            
            # Check if we need to handle paywall content
            if self._is_paywall_content(soup):
                print(f"Paywall content detected for {url}")
                content = self._extract_paywall_content(soup)
            else:
                # Extract article content - first try the article section
                article_section = soup.find('section')
                if not article_section:
                    article_section = soup.find('article')
                
                if not article_section:
                    # Try another approach - look for the main content div
                    article_section = soup.find('div', {'role': 'main'})
                
                if not article_section:
                    print(f"Could not identify article section in {url}")
                    return None, 0, 0
                
                # Extract paragraphs - be more thorough with the selectors
                paragraphs = article_section.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'blockquote'])
                
                if not paragraphs and article_section:
                    # If no paragraphs found but article section exists, get all text
                    content = article_section.get_text()
                else:
                    # Join paragraphs with double newlines
                    content = "\n\n".join([p.get_text() for p in paragraphs])
                
                # Clean up the content
                content = re.sub(r'\s+', ' ', content).strip()
            
            return content, claps_count, responses_count
        except Exception as e:
            print(f"Error extracting content from {url}: {e}")
            return None, 0, 0
    
    def _is_paywall_content(self, soup):
        """Check if the content is behind a paywall"""
        # Look for typical paywall indicators
        paywall_indicators = [
            soup.find('div', string=re.compile(r'Member.only story', re.I)),
            soup.find('div', string=re.compile(r'You.ve reached the end of your free member preview', re.I)),
            soup.find('div', class_=re.compile(r'paywall|membership-prompt', re.I))
        ]
        
        return any(paywall_indicators)
    
    def _extract_paywall_content(self, soup):
        """Try to extract content from behind a paywall"""
        # Check if our cookies give us access to the full content
        # If they do, we should be able to find the content in the HTML
        
        # Try to find the main content in different potential formats
        # This is a heuristic approach as Medium's HTML structure may change
        content_containers = [
            soup.find('div', {'id': 'root'}),
            soup.find('article'),
            soup.find('div', {'role': 'main'})
        ]
        
        for container in content_containers:
            if container:
                paragraphs = container.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'blockquote'])
                if paragraphs:
                    # If we found paragraphs, assume we have access to the content
                    content = "\n\n".join([p.get_text() for p in paragraphs])
                    content = re.sub(r'\s+', ' ', content).strip()
                    return content
        
        # If we couldn't extract content with the methods above,
        # return whatever text content we can find
        article_text = ""
        main_content = soup.find('div', {'role': 'main'})
        if main_content:
            article_text = main_content.get_text()
            article_text = re.sub(r'\s+', ' ', article_text).strip()
        
        return article_text if article_text else "Could not access full content. May require membership."
    
    def get_top_articles(self, count=TOP_ARTICLES_COUNT):
        """Get top articles from Medium feeds"""
        all_entries = []
        
        for feed_url in self.top_feeds:
            try:
                feed = feedparser.parse(feed_url)
                all_entries.extend(feed.entries)
            except Exception as e:
                print(f"Error parsing feed {feed_url}: {e}")
        
        # Sort by published date
        all_entries.sort(key=lambda entry: entry.get('published_parsed', 0), reverse=True)
        
        # Take the top N entries
        top_entries = all_entries[:count]
        
        # Format the articles
        articles = self._format_articles(top_entries)
        
        return articles
    
    def get_popular_articles(self, count=TOP_ARTICLES_COUNT):
        """Get popular articles from Medium"""
        all_entries = []
        
        for feed_url in self.popular_feeds:
            try:
                feed = feedparser.parse(feed_url)
                all_entries.extend(feed.entries)
            except Exception as e:
                print(f"Error parsing feed {feed_url}: {e}")
        
        # Sort by published date
        all_entries.sort(key=lambda entry: entry.get('published_parsed', 0), reverse=True)
        
        # Remove duplicates based on link
        unique_entries = []
        seen_links = set()
        for entry in all_entries:
            if entry.link not in seen_links:
                seen_links.add(entry.link)
                unique_entries.append(entry)
        
        # Take the top N entries
        top_entries = unique_entries[:count]
        
        # Format the articles
        articles = self._format_articles(top_entries)
        
        return articles
    
    def get_articles_by_tag(self, tag, count=TOP_ARTICLES_COUNT):
        """Get articles from Medium by specific tag"""
        all_entries = []
        
        # Clean up the tag for URL
        clean_tag = tag.lower().replace(' ', '-')
        feed_url = f"https://medium.com/feed/tag/{clean_tag}"
        
        try:
            feed = feedparser.parse(feed_url)
            all_entries.extend(feed.entries)
        except Exception as e:
            print(f"Error parsing feed {feed_url}: {e}")
            return []
        
        # Sort by published date
        all_entries.sort(key=lambda entry: entry.get('published_parsed', 0), reverse=True)
        
        # Take the top N entries
        top_entries = all_entries[:count]
        
        # Format the articles
        articles = self._format_articles(top_entries)
        
        return articles
    
    def _format_articles(self, entries):
        """Format feed entries into article objects"""
        articles = []
        for entry in entries:
            # Generate a unique ID
            article_id = str(uuid.uuid4())
            
            # Parse the date
            published_at = datetime(*entry.published_parsed[:6]).isoformat()
            
            # Extract tags
            tags = []
            if 'tags' in entry:
                tags = [tag.term for tag in entry.tags]
            
            # Get the article content using authenticated requests
            content, claps_count, responses_count = self.extract_content_from_url(entry.link)
            
            articles.append({
                'id': article_id,
                'title': entry.title,
                'author': entry.author if hasattr(entry, 'author') else 'Unknown',
                'url': entry.link,
                'published_at': published_at,
                'tags': tags,
                'content': content,
                'summary': None,  # Will be filled by the summarization service
                'claps': claps_count,
                'responses': responses_count
            })
        
        return articles 