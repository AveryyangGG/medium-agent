import os
import sys
import time
import asyncio
import threading
import schedule
from datetime import datetime
import uvicorn
import signal

# Add the project root to the path
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(script_dir)

from config import TOP_ARTICLES_COUNT, WEB_APP_HOST, WEB_APP_PORT
from app.db.database import Database
from app.db.vector_db import VectorDatabase
from app.services.medium_service import MediumService
from app.services.summarization_service import SummarizationService
from app.bot.telegram_bot import TelegramBot
from app.api.web_app import app

# 全局變數，用於協調多個線程的停止
running = True
stop_event = None
main_loop = None

class MediumAgent:
    def __init__(self):
        self.db = Database()
        self.vector_db = VectorDatabase()
        self.medium_service = MediumService()
        self.summarization_service = SummarizationService()
        self.telegram_bot = TelegramBot()
        self.is_running = False
        self.web_app_thread = None
        self.scheduler_thread = None
    
    def fetch_and_process_articles(self):
        """Fetch articles from Medium, summarize them, and store in the database"""
        print(f"[{datetime.now()}] Fetching articles from Medium...")
        
        # Get top articles from Medium
        articles = self.medium_service.get_top_articles(count=TOP_ARTICLES_COUNT)
        
        if not articles:
            print("No articles found")
            return []
        
        processed_articles = []
        
        # Process each article
        for article in articles:
            # Check if article content was retrieved
            if not article.get('content'):
                print(f"Skipping article with no content: {article['title']}")
                continue
            
            # Summarize the article
            try:
                # 使用非流式方法，避免流式處理可能造成的問題
                summary, bullet_points = self.summarization_service.summarize_article(article)
                
                if summary:
                    # Format the summary with bullet points
                    formatted_summary = self.summarization_service.format_summary_with_bullets(summary, bullet_points)
                    article['summary'] = formatted_summary
                
                # Save to database
                self.db.add_article(article)
                processed_articles.append(article)
                
                print(f"Processed article: {article['title']}")
            except Exception as e:
                print(f"Error processing article '{article.get('title')}': {e}")
        
        print(f"Processed {len(processed_articles)} articles")
        return processed_articles
    
    def daily_update(self):
        """Daily task to fetch articles and send them via Telegram"""
        print(f"[{datetime.now()}] Running daily update...")
        processed_articles = self.fetch_and_process_articles()
        
        if processed_articles and running:
            # 使用獨立的異步函數發送文章
            asyncio.run(self.send_articles_to_telegram(processed_articles))
    
    async def send_articles_to_telegram(self, articles):
        """Send articles to Telegram in a separate async context"""
        try:
            # 建立新的 client 連接 (避免跨線程問題)
            await self.telegram_bot.send_articles_to_chat(articles)
            print("Articles sent to Telegram successfully")
        except Exception as e:
            print(f"Error sending articles to Telegram: {e}")
    
    def schedule_daily_updates(self):
        """Schedule daily updates at a specific time"""
        # Schedule daily update at 8 AM
        schedule.every().day.at("08:00").do(self.daily_update)
        print("Scheduled daily updates at 8:00 AM")
    
    def run_scheduler(self):
        """Run the scheduler in a separate thread"""
        print("Starting scheduler thread...")
        self.schedule_daily_updates()
        
        # Run an initial update immediately
        self.daily_update()
        
        while self.is_running and running:
            schedule.run_pending()
            time.sleep(5)  # Check every 5 seconds
        
        print("Scheduler thread stopped")
    
    def run_web_app(self):
        """Run the web app in a separate thread"""
        print(f"Starting web app on http://{WEB_APP_HOST}:{WEB_APP_PORT}")
        try:
            uvicorn.run(app, host=WEB_APP_HOST, port=WEB_APP_PORT)
        except Exception as e:
            print(f"Web app error: {e}")
        finally:
            print("Web app stopped")
    
    async def run_telegram_bot(self):
        """Run the Telegram bot with its own event loop"""
        print("Starting Telegram bot...")
        try:
            await self.telegram_bot.run_async()
        except Exception as e:
            print(f"Error running Telegram bot: {e}")
    
    async def run_async(self):
        """Run the application asynchronously"""
        global stop_event, main_loop
        main_loop = asyncio.get_running_loop()
        stop_event = asyncio.Event()
        
        self.is_running = True
        
        # 啟動排程器線程
        self.scheduler_thread = threading.Thread(target=self.run_scheduler)
        self.scheduler_thread.daemon = True
        self.scheduler_thread.start()
        
        # 啟動 web 應用線程
        self.web_app_thread = threading.Thread(target=self.run_web_app)
        self.web_app_thread.daemon = True
        self.web_app_thread.start()
        
        # 在主異步上下文中運行 Telegram 機器人
        await self.run_telegram_bot()
        
        # 等待停止信號
        await stop_event.wait()
        print("Stop signal received, shutting down...")
    
    def start(self):
        """Start the Medium agent"""
        try:
            asyncio.run(self.run_async())
        except KeyboardInterrupt:
            print("\nKeyboard interrupt received, shutting down...")
        finally:
            self.stop()
    
    def stop(self):
        """Stop the Medium agent"""
        global running
        running = False
        self.is_running = False
        
        print("Stopping Medium Agent...")
        
        # 設置停止事件 - 使用更安全的方式
        self._trigger_stop_event()
        
        # 確保所有資源都適當關閉
        try:
            self.db.close()
        except Exception as e:
            print(f"關閉資料庫連接時發生錯誤: {e}")
        
        print("Medium Agent stopped")
    
    def _trigger_stop_event(self):
        """安全地觸發停止事件"""
        global stop_event, main_loop
        if stop_event is not None and main_loop is not None:
            if main_loop.is_running():
                try:
                    future = asyncio.run_coroutine_threadsafe(self._set_stop_event(), main_loop)
                    # 不等待結果，避免死鎖
                except Exception as e:
                    print(f"無法設置停止事件: {e}")
    
    async def _set_stop_event(self):
        """Set the stop event in the correct async context"""
        if stop_event:
            stop_event.set()

def signal_handler(sig, frame):
    """Handle Ctrl+C signal"""
    print("\nStopping the application...")
    global running
    running = False
    
    # 強制直接終止程序，避免更多的錯誤
    sys.exit(0)

if __name__ == "__main__":
    # Register signal handler for Ctrl+C
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Create agent
    agent = None
    
    try:
        print("Starting Medium Agent...")
        agent = MediumAgent()
        agent.start()
    except KeyboardInterrupt:
        print("\nStopping Medium Agent...")
        if agent:
            agent.stop()
    except Exception as e:
        print(f"Error in main application: {e}")
        if agent:
            agent.stop() 