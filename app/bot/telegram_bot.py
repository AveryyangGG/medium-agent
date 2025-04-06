import os
import sys
import asyncio
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
from telegram.error import NetworkError, TimedOut, TelegramError
from enum import Enum
import requests
from bs4 import BeautifulSoup
import uuid
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, ADMIN_USER_IDS
from app.db.database import Database
from app.db.vector_db import VectorDatabase
from app.services.summarization_service import SummarizationService
from app.services.medium_service import MediumService
from config import WEB_APP_HOST, WEB_APP_PORT, PUBLIC_URL_BASE, TOP_ARTICLES_COUNT

# 定義用戶狀態
class UserState(Enum):
    IDLE = 0
    WAITING_FOR_TAGS = 1
    WAITING_FOR_NOTES = 2

# 存儲用戶狀態和上下文信息
user_states = {}

class TelegramBot:
    def __init__(self):
        self.token = TELEGRAM_BOT_TOKEN
        self.chat_id = TELEGRAM_CHAT_ID
        self.db = Database()
        self.vector_db = VectorDatabase()
        self.summarization_service = SummarizationService()
        self.medium_service = MediumService()
        self.application = None
        self._init_app()
    
    def _init_app(self):
        """Initialize the bot application"""
        # Check if token exists
        if not self.token:
            print("WARNING: Telegram bot token not provided. Telegram functionality will not work.")
            return
            
        self.application = Application.builder().token(self.token).build()
        
        # Add handlers
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("today", self.today_command))
        self.application.add_handler(CommandHandler("recent", self.recent_command))
        self.application.add_handler(CommandHandler("search", self.search_command))
        self.application.add_handler(CommandHandler("fetch", self.fetch_command))
        self.application.add_handler(CommandHandler("popular", self.popular_command))
        self.application.add_handler(CommandHandler("tag", self.tag_command))
        self.application.add_handler(CommandHandler("summary", self.summary_command))
        
        # 資料庫管理命令
        self.application.add_handler(CommandHandler("db_stats", self.db_stats_command))
        self.application.add_handler(CommandHandler("db_clean", self.db_clean_command))
        self.application.add_handler(CommandHandler("db_delete", self.db_delete_command))
        self.application.add_handler(CommandHandler("db_find_tag", self.db_find_tag_command))
        
        self.application.add_handler(CallbackQueryHandler(self.button_callback))
        
        # 添加文本消息處理器 - 用於處理標籤輸入
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text_input))
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Send a message when the command /start is issued."""
        user = update.effective_user
        await update.message.reply_html(
            f"Hi {user.mention_html()}! I'm your Medium article bot. "
            f"I'll send you top Medium articles daily.\n\n"
            f"Use /today to see today's articles or /help for more commands."
        )
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Send a message when the command /help is issued."""
        basic_commands = (
            "Available commands:\n"
            "/start - Start the bot\n"
            "/today - Get today's top articles\n"
            "/recent - Show recent articles\n"
            "/search <query> - Search saved articles\n"
            "/fetch - Fetch new top Medium articles\n"
            "/popular - Get popular Medium articles\n"
            "/tag <tag> - Find articles with specific tag\n"
            "/summary <url> - Generate summary for a Medium article URL\n"
            "/help - Show this help message"
        )
        
        # 檢查是否為管理員
        is_admin = str(update.effective_user.id) in ADMIN_USER_IDS
        
        if is_admin:
            admin_commands = (
                "\n\nAdmin commands:\n"
                "/db_stats - Get database statistics\n"
                "/db_clean <days> - Clean old articles (default: 30 days)\n"
                "/db_delete <article_id> - Delete specific article\n"
                "/db_find_tag <tag> - Find articles by tag"
            )
            help_text = basic_commands + admin_commands
        else:
            help_text = basic_commands
            
        await update.message.reply_text(help_text)
    
    async def today_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Send today's top articles when the command /today is issued."""
        articles = self.db.get_recent_articles(limit=5)
        
        if not articles:
            await update.message.reply_text("No articles available for today.")
            return
        
        await update.message.reply_text("Today's top Medium articles:")
        
        for article in articles:
            # 獲取掌聲與回應數
            claps = article.get('claps', 0)
            responses = article.get('responses', 0)
            engagement_info = f"👏 {claps:,} · 💬 {responses}"
            
            # Create buttons for each article
            keyboard = [
                [
                    InlineKeyboardButton("Read Article", url=article['url']),
                    InlineKeyboardButton("Save to RAG", callback_data=f"save_{article['id']}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Format the message
            summary = article.get('summary', 'No summary available.')
            message = (
                f"*{article['title']}*\n"
                f"By: {article['author']} · {engagement_info}\n\n"
                f"{summary}\n\n"
            )
            
            await update.message.reply_text(
                message, 
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
    
    async def recent_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Show recent articles when the command /recent is issued."""
        limit = 5
        if context.args and context.args[0].isdigit():
            limit = min(int(context.args[0]), 10)  # Limit to max 10 articles
        
        articles = self.db.get_recent_articles(limit=limit)
        
        if not articles:
            await update.message.reply_text("No recent articles available.")
            return
        
        await update.message.reply_text(f"Recent {len(articles)} Medium articles:")
        
        for article in articles:
            # 獲取掌聲與回應數
            claps = article.get('claps', 0)
            responses = article.get('responses', 0)
            engagement_info = f"👏 {claps:,} · 💬 {responses}"
            
            keyboard = [
                [
                    InlineKeyboardButton("Read Article", url=article['url']),
                    InlineKeyboardButton("Save to RAG", callback_data=f"save_{article['id']}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message = (
                f"*{article['title']}*\n"
                f"By: {article['author']} · {engagement_info}\n"
                f"Published: {article['published_at'].split('T')[0]}\n\n"
                f"{article.get('summary', 'No summary available.')[:150]}...\n\n"
            )
            
            await update.message.reply_text(
                message, 
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
    
    async def search_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Search saved articles with the command /search <query>."""
        if not context.args:
            await update.message.reply_text("Please provide a search query. Example: /search machine learning")
            return
        
        query = " ".join(context.args)
        await update.message.reply_text(f"Searching for: {query}")
        
        results = self.vector_db.query_similar_articles(query, n_results=5)
        
        if not results:
            await update.message.reply_text("No matching articles found.")
            return
        
        await update.message.reply_text(f"Found {len(results)} relevant articles:")
        
        for article in results:
            # 獲取掌聲與回應數
            claps = article.get('claps', 0)
            responses = article.get('responses', 0)
            engagement_info = f"👏 {claps:,} · 💬 {responses}"
            
            keyboard = [
                [InlineKeyboardButton("Read Article", url=article['url'])]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message = (
                f"*{article['title']}*\n"
                f"By: {article['author']} · {engagement_info}\n"
                f"Published: {article['published_at'].split('T')[0]}\n\n"
                f"{article.get('summary', 'No summary available.')[:150]}...\n\n"
            )
            
            await update.message.reply_text(
                message, 
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
    
    async def fetch_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """主動獲取Medium上的熱門文章"""
        await update.message.reply_text("正在獲取Medium熱門文章，請稍等...")
        
        try:
            # 建立Medium服務
            medium_service = MediumService()
            
            # 獲取熱門文章
            count = TOP_ARTICLES_COUNT
            if context.args and context.args[0].isdigit():
                count = min(int(context.args[0]), 10)  # 限制最多10篇
            
            articles = medium_service.get_top_articles(count=count)
            
            if not articles:
                await update.message.reply_text("未找到任何文章，請稍後再試。")
                return
            
            await update.message.reply_text(f"已找到 {len(articles)} 篇熱門文章，開始處理...")
            
            # 使用共用方法處理並發送文章
            await self._process_and_send_articles(update, articles)
                
        except Exception as e:
            print(f"獲取文章時出錯: {e}")
            await update.message.reply_text(f"獲取文章時出錯: {e}")
    
    async def popular_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """獲取Medium平台上當前熱門文章"""
        await update.message.reply_text("正在獲取Medium熱門文章，請稍等...")
        
        try:
            # 獲取熱門文章
            count = 5  # 默認獲取5篇
            if context.args and context.args[0].isdigit():
                count = min(int(context.args[0]), 10)  # 限制最多10篇
            
            articles = self.medium_service.get_popular_articles(count=count)
            
            if not articles:
                await update.message.reply_text("未找到任何熱門文章，請稍後再試。")
                return
            
            await update.message.reply_text(f"已找到 {len(articles)} 篇熱門文章，開始處理...")
            
            # 處理並發送文章
            await self._process_and_send_articles(update, articles)
            
        except Exception as e:
            print(f"獲取熱門文章時出錯: {e}")
            await update.message.reply_text(f"獲取熱門文章時出錯: {e}")
    
    async def tag_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """根據標籤獲取Medium文章"""
        if not context.args:
            await update.message.reply_text("請提供標籤名稱。例如: /tag programming")
            return
        
        tag = " ".join(context.args)
        await update.message.reply_text(f"正在獲取標籤「{tag}」的文章，請稍等...")
        
        try:
            # 獲取指定標籤的文章
            articles = self.medium_service.get_articles_by_tag(tag, count=5)
            
            if not articles:
                await update.message.reply_text(f"未找到任何「{tag}」標籤的文章，請嘗試其他標籤。")
                return
            
            await update.message.reply_text(f"已找到 {len(articles)} 篇「{tag}」標籤的文章，開始處理...")
            
            # 處理並發送文章
            await self._process_and_send_articles(update, articles)
            
        except Exception as e:
            print(f"獲取標籤文章時出錯: {e}")
            await update.message.reply_text(f"獲取標籤文章時出錯: {e}")
    
    async def summary_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """生成Medium文章的摘要和詳細整理"""
        if not context.args:
            await update.message.reply_text("請提供Medium文章連結。例如: /summary https://medium.com/...")
            return
        
        url = context.args[0]
        
        # 驗證URL是否為Medium連結
        #if not url.startswith(("https://medium.com/", "https://towardsdatascience.com/", "https://betterhumans.pub/", "https://www.freecodecamp.org/")):
        #    await update.message.reply_text("請提供有效的Medium或Medium發布平台文章連結。")
        #    return
        
        await update.message.reply_text(f"正在處理文章連結，開始生成摘要，請稍等...")
        
        try:
            # 提取文章內容
            content, claps_count, responses_count = self.medium_service.extract_content_from_url(url)
            
            if not content:
                await update.message.reply_text("無法提取文章內容，請確認連結是否正確或重試。")
                return
            
            # 創建臨時文章對象
            article = {
                'id': str(uuid.uuid4()),
                'title': "Medium文章",  # 暫時標題，後續可能從內容中提取
                'author': "未知作者",
                'url': url,
                'published_at': datetime.now().isoformat(),
                'tags': None,
                'content': content,
                'summary': None,
                'claps': claps_count,
                'responses': responses_count
            }
            
            # 嘗試從頁面標題提取更好的標題
            try:
                response = requests.get(url, cookies=self.medium_service.cookies, headers=self.medium_service.headers)
                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, 'html.parser')
                    title_elem = soup.find('title')
                    if title_elem and title_elem.text:
                        # 清理標題字串（去除Medium後綴等）
                        title = title_elem.text.split('|')[0].strip()
                        article['title'] = title
                        
                    # 嘗試提取作者
                    author_elem = soup.find('meta', {'name': 'author'})
                    if author_elem and author_elem.get('content'):
                        article['author'] = author_elem.get('content')
            except Exception as e:
                print(f"提取標題時出錯: {e}")
                # 繼續使用默認標題
            
            # 在這裡直接處理文章摘要和詳細整理
            try:
                # 生成摘要和重點
                summary, bullet_points = self.summarization_service.summarize_article(article)
                formatted_summary = self.summarization_service.format_summary_with_bullets(summary, bullet_points)
                article['summary'] = formatted_summary
                
                # 生成詳細條列整理
                detailed_outline = self.summarization_service.create_detailed_outline(article)
                if not detailed_outline:
                    detailed_outline = article.get('summary', '無摘要可用')
                
                # 保存詳細條列整理
                article['detailed_summary'] = detailed_outline
                
                # 將文章保存到資料庫
                self.db.add_article(article)
            except Exception as e:
                print(f"處理文章摘要或詳細整理時出錯: {e}")
                await update.message.reply_text(f"處理文章摘要或詳細整理時出錯: {e}")
                return
            
            # 創建單篇文章的列表，使用與fetch命令相同的處理邏輯
            articles_list = [article]
            await self._process_and_send_articles(update, articles_list)
            
        except Exception as e:
            print(f"生成文章摘要時出錯: {e}")
            await update.message.reply_text(f"生成文章摘要時出錯: {e}")
    
    async def _process_and_send_articles(self, update, articles):
        """處理並發送文章列表 - 避免代碼重複"""
        try:
            processed_articles = []
            for article in articles:
                # 檢查文章是否已存在
                existing = self.db.get_article(article['id'])
                if existing:
                    processed_articles.append(existing)
                    continue
                
                # 確保 tags 欄位類型正確
                if 'tags' in article and isinstance(article['tags'], list):
                    article['tags'] = None
                
                # 如果文章還沒有摘要，則處理摘要
                if not article.get('summary'):
                    try:
                        summary, bullet_points = self.summarization_service.summarize_article(article)
                        if summary:
                            formatted_summary = self.summarization_service.format_summary_with_bullets(summary, bullet_points)
                            article['summary'] = formatted_summary
                    except Exception as e:
                        print(f"處理文章摘要時出錯: {e}")
                
                # 保存到資料庫
                self.db.add_article(article)
                processed_articles.append(article)
            
            # 發送文章
            if processed_articles:
                for article in processed_articles:
                    try:
                        # 如果文章還沒有詳細整理，則生成
                        if not article.get('detailed_summary'):
                            detailed_outline = self.summarization_service.create_detailed_outline(article)
                            if not detailed_outline:
                                detailed_outline = article.get('summary', 'No outline available.')
                            
                            # 保存到資料庫
                            self.db.update_article_with_details(article['id'], detailed_summary=detailed_outline)
                        else:
                            detailed_outline = article.get('detailed_summary')
                        
                        # 獲取掌聲與回應數
                        claps = article.get('claps', 0)
                        responses = article.get('responses', 0)
                        engagement_info = f"👏 {claps:,} · 💬 {responses}"
                        
                        # 準備顯示按鈕
                        if PUBLIC_URL_BASE:
                            # 使用公開URL
                            web_url = f"{PUBLIC_URL_BASE}/articles/{article['id']}/outline"
                            keyboard = [
                                [
                                    InlineKeyboardButton("閱讀原文", url=article['url']),
                                    InlineKeyboardButton("查看詳細整理", url=web_url)
                                ],
                                [
                                    InlineKeyboardButton("添加標籤並保存", callback_data=f"tag_{article['id']}")
                                ],
                                [
                                    InlineKeyboardButton("直接保存", callback_data=f"directsave_{article['id']}"),
                                    InlineKeyboardButton("取消", callback_data=f"cancel_{article['id']}")
                                ]
                            ]
                            
                            # 格式化消息 - 使用簡短摘要
                            summary = article.get('summary', '無摘要可用')
                            message_text = (
                                f"*{article['title']}*\n"
                                f"作者: {article['author']} · {engagement_info}\n\n"
                                f"{summary}\n\n"
                                f"點擊「查看詳細整理」按鈕在網頁上查看完整的條列式整理。"
                            )
                        else:
                            # 沒有公開URL，直接發送詳細整理
                            keyboard = [
                                [
                                    InlineKeyboardButton("閱讀原文", url=article['url'])
                                ],
                                [
                                    InlineKeyboardButton("添加標籤並保存", callback_data=f"tag_{article['id']}")
                                ],
                                [
                                    InlineKeyboardButton("直接保存", callback_data=f"directsave_{article['id']}"),
                                    InlineKeyboardButton("取消", callback_data=f"cancel_{article['id']}")
                                ]
                            ]
                            
                            # 限制訊息長度
                            max_length = 4000  # 留一些餘量
                            message_title = (
                                f"*{article['title']}*\n"
                                f"作者: {article['author']} · {engagement_info}\n\n"
                            )
                            
                            # 獲取摘要
                            summary = article.get('summary', '無摘要可用')
                            
                            if len(detailed_outline) > (max_length - len(message_title)):
                                truncated_outline = detailed_outline[:max_length - len(message_title) - 20] + "...(已截斷)"
                                message_text = message_title + truncated_outline
                            else:
                                message_text = message_title + detailed_outline
                        
                        reply_markup = InlineKeyboardMarkup(keyboard)
                        
                        # 發送消息
                        await update.message.reply_text(
                            message_text,
                            reply_markup=reply_markup,
                            parse_mode='Markdown'
                        )
                        
                    except Exception as e:
                        print(f"發送文章時出錯: {e}")
                
                await update.message.reply_text("文章處理完成！")
            else:
                await update.message.reply_text("沒有新文章需要處理。")
                
        except Exception as e:
            print(f"處理文章時出錯: {e}")
            await update.message.reply_text(f"處理文章時出錯: {e}")
    
    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle button callbacks."""
        query = update.callback_query
        data = query.data
        
        if data.startswith("save_"):
            article_id = data.replace("save_", "")
            user_id = str(update.effective_user.id)
            
            # 先回答回調，防止超時
            try:
                await query.answer()
            except (NetworkError, TimedOut, TelegramError) as e:
                print(f"警告：回答回調時遇到網絡問題，這可能是正常的: {e}")
            
            # 獲取文章數據
            article = self.db.get_article(article_id)
            if not article:
                try:
                    await query.message.reply_text("找不到此文章，請稍後再試。")
                except Exception as e:
                    print(f"發送錯誤消息失敗: {e}")
                return
            
            # 生成詳細整理
            try:
                await query.message.reply_text("正在生成詳細整理，請稍等...")
                detailed_outline = self.summarization_service.create_detailed_outline(article)
                
                if not detailed_outline:
                    await query.message.reply_text("無法生成詳細整理，使用簡短摘要代替。")
                    detailed_outline = article.get('summary', '無摘要可用')
                
                # 保存詳細整理到資料庫
                self.db.update_article_with_details(article_id, detailed_summary=detailed_outline)
                
                # 獲取掌聲與回應數
                claps = article.get('claps', 0)
                responses = article.get('responses', 0)
                engagement_info = f"👏 {claps:,} · 💬 {responses}"
                
                # 檢查是否有公開URL可用
                if PUBLIC_URL_BASE:
                    # 使用公開URL建立連結按鈕
                    web_url = f"{PUBLIC_URL_BASE}/articles/{article_id}/outline"
                    keyboard = [
                        [
                            InlineKeyboardButton("閱讀原文", url=article['url']),
                            InlineKeyboardButton("查看詳細整理", url=web_url)
                        ],
                        [
                            InlineKeyboardButton("添加標籤並保存", callback_data=f"tag_{article_id}")
                        ],
                        [
                            InlineKeyboardButton("直接保存", callback_data=f"directsave_{article_id}"),
                            InlineKeyboardButton("取消", callback_data=f"cancel_{article_id}")
                        ]
                    ]
                    
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    # 發送摘要和連結
                    summary = article.get('summary', '無摘要可用')
                    message_text = (
                        f"*{article['title']}*\n"
                        f"作者: {article['author']} · {engagement_info}\n\n"
                        f"{summary}\n\n"
                        f"點擊「查看詳細整理」按鈕在網頁上查看完整的條列式整理。"
                    )
                    
                    await query.message.reply_text(
                        message_text,
                        reply_markup=reply_markup,
                        parse_mode='Markdown'
                    )
                else:
                    # 沒有公開URL，直接在Telegram顯示詳細整理
                    keyboard = [
                        [
                            InlineKeyboardButton("閱讀原文", url=article['url'])
                        ],
                        [
                            InlineKeyboardButton("添加標籤並保存", callback_data=f"tag_{article_id}")
                        ],
                        [
                            InlineKeyboardButton("直接保存", callback_data=f"directsave_{article_id}"),
                            InlineKeyboardButton("取消", callback_data=f"cancel_{article_id}")
                        ]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    # 限制訊息長度，Telegram有限制(最多4096字符)
                    max_length = 4000  # 留一些餘量
                    message_title = (
                        f"*{article['title']}*\n"
                        f"作者: {article['author']} · {engagement_info}\n\n"
                    )
                    
                    if len(detailed_outline) > (max_length - len(message_title)):
                        truncated_outline = detailed_outline[:max_length - len(message_title) - 20] + "...(已截斷)"
                        await query.message.reply_text(
                            message_title + truncated_outline,
                            reply_markup=reply_markup,
                            parse_mode='Markdown'
                        )
                    else:
                        await query.message.reply_text(
                            message_title + detailed_outline,
                            reply_markup=reply_markup,
                            parse_mode='Markdown'
                        )
                
            except Exception as e:
                print(f"生成詳細整理時出錯: {e}")
                await query.message.reply_text(f"生成詳細整理時出錯: {e}")
        
        elif data.startswith("tag_"):
            # 用戶選擇添加標籤
            article_id = data.replace("tag_", "")
            user_id = str(update.effective_user.id)
            
            try:
                await query.answer()
            except Exception as e:
                print(f"回答回調時出錯: {e}")
            
            # 更新用戶狀態
            user_states[user_id] = {
                'state': UserState.WAITING_FOR_TAGS,
                'article_id': article_id
            }
            
            await query.message.reply_text(
                "請輸入標籤，多個標籤請用逗號分隔（例如：AI, 機器學習, 教程）："
            )
        
        elif data.startswith("directsave_"):
            # 用戶選擇直接保存，不添加標籤
            article_id = data.replace("directsave_", "")
            
            try:
                await query.answer()
            except Exception as e:
                print(f"回答回調時出錯: {e}")
            
            # 直接保存到 RAG
            success = self.vector_db.add_article_to_rag(article_id)
            
            if success:
                try:
                    await query.message.reply_text("文章已成功保存到知識庫！")
                    print(f"成功保存文章 ID {article_id} 到 RAG 數據庫")
                except Exception as e:
                    print(f"發送確認消息時出錯: {e}")
            else:
                try:
                    await query.message.reply_text("保存文章失敗，請稍後再試。")
                    print(f"無法保存文章 ID {article_id} 到 RAG 數據庫")
                except Exception as e:
                    print(f"發送錯誤消息時出錯: {e}")
        
        elif data.startswith("cancel_"):
            # 用戶取消操作
            article_id = data.replace("cancel_", "")
            user_id = str(update.effective_user.id)
            
            try:
                await query.answer()
            except Exception as e:
                print(f"回答回調時出錯: {e}")
            
            # 清除用戶狀態
            if user_id in user_states:
                del user_states[user_id]
            
            await query.message.reply_text("已取消保存操作。")
        
        # 新增資料庫管理相關的回調處理
        elif data.startswith("dbclean_"):
            user_id = update.effective_user.id
            
            # 檢查權限
            if not self._is_admin(user_id):
                await query.answer("您沒有權限執行此操作")
                return
            
            # 解析參數
            if data == "dbclean_cancel":
                await query.edit_message_text("已取消清理操作")
                return
            
            parts = data.split("_")
            if len(parts) >= 3:
                days = int(parts[1])
                keep_saved = parts[2].lower() in ('true', 'yes', '1')
                
                # 執行清理
                await query.edit_message_text("正在清理資料庫，請稍等...")
                
                try:
                    # 清理普通資料庫
                    deleted_count = self.db.clean_old_articles(days=days, keep_saved=keep_saved)
                    
                    # 清理向量資料庫中的孤立向量
                    cleaned_vectors = self.vector_db.clean_vector_database()
                    
                    # 回報結果
                    result_message = f"成功清理了 {deleted_count} 篇舊文章和 {cleaned_vectors} 個孤立向量嵌入"
                    await query.edit_message_text(result_message)
                except Exception as e:
                    error_message = f"清理資料庫時出錯: {e}"
                    await query.edit_message_text(error_message)
            else:
                await query.edit_message_text("指令格式錯誤，已取消操作")
                
        elif data.startswith("dbdelete_"):
            user_id = update.effective_user.id
            
            # 檢查權限
            if not self._is_admin(user_id):
                await query.answer("您沒有權限執行此操作")
                return
            
            # 解析參數
            if data == "dbdelete_cancel":
                await query.edit_message_text("已取消刪除操作")
                return
            
            article_id = data.replace("dbdelete_", "")
            
            # 執行刪除
            await query.edit_message_text("正在刪除文章，請稍等...")
            
            try:
                # 先刪除向量嵌入
                self.vector_db.delete_article_embedding(article_id)
                
                # 再刪除文章記錄
                success = self.db.delete_article(article_id)
                
                if success:
                    await query.edit_message_text("文章已成功刪除")
                else:
                    await query.edit_message_text("刪除文章失敗，可能文章不存在或已被刪除")
            except Exception as e:
                error_message = f"刪除文章時出錯: {e}"
                await query.edit_message_text(error_message)
    
    async def handle_text_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """處理用戶輸入的文本（標籤或備註）"""
        user_id = str(update.effective_user.id)
        text = update.message.text
        
        # 檢查用戶是否在等待輸入
        if user_id not in user_states:
            return
        
        user_state = user_states[user_id]
        
        if user_state['state'] == UserState.WAITING_FOR_TAGS:
            # 處理標籤輸入
            article_id = user_state['article_id']
            
            # 處理標籤
            tags = [tag.strip() for tag in text.split(',') if tag.strip()]
            
            # 更新文章標籤
            self.db.update_article_with_details(article_id, user_tags=tags)
            
            # 更新用戶狀態，等待備註
            user_states[user_id] = {
                'state': UserState.WAITING_FOR_NOTES,
                'article_id': article_id,
                'tags': tags
            }
            
            # 詢問用戶是否要添加備註
            keyboard = [
                [
                    InlineKeyboardButton("添加備註", callback_data=f"note_{article_id}"),
                    InlineKeyboardButton("完成保存", callback_data=f"finish_{article_id}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"標籤已添加：{', '.join(tags)}\n\n您想添加個人備註嗎？",
                reply_markup=reply_markup
            )
            
        elif user_state['state'] == UserState.WAITING_FOR_NOTES:
            # 處理備註輸入
            article_id = user_state['article_id']
            
            # 更新文章備註
            self.db.update_article_with_details(article_id, user_notes=text)
            
            # 保存到 RAG
            success = self.vector_db.add_article_to_rag(article_id)
            
            if success:
                await update.message.reply_text("備註已添加，文章已成功保存到知識庫！")
                print(f"成功保存文章 ID {article_id} 到 RAG 數據庫")
            else:
                await update.message.reply_text("備註已添加，但保存文章失敗，請稍後再試。")
                print(f"無法保存文章 ID {article_id} 到 RAG 數據庫")
            
            # 清除用戶狀態
            del user_states[user_id]
    
    async def send_articles_to_chat(self, articles):
        """Send articles to the specified chat_id."""
        if not self.application or not self.chat_id:
            print("Bot not initialized or chat_id not provided")
            return
        
        for article in articles:
            try:
                # 首先生成詳細outline
                detailed_outline = self.summarization_service.create_detailed_outline(article)
                if not detailed_outline:
                    detailed_outline = article.get('summary', 'No outline available.')
                
                # 保存到資料庫
                self.db.update_article_with_details(article['id'], detailed_summary=detailed_outline)
                
                # 獲取掌聲與回應數
                claps = article.get('claps', 0)
                responses = article.get('responses', 0)
                engagement_info = f"👏 {claps:,} · 💬 {responses}"
                
                # Create buttons for the article
                if PUBLIC_URL_BASE:
                    # 使用公開URL
                    web_url = f"{PUBLIC_URL_BASE}/articles/{article['id']}/outline"
                    keyboard = [
                        [
                            InlineKeyboardButton("Read Article", url=article['url']),
                            InlineKeyboardButton("View Outline", url=web_url)
                        ],
                        [
                            InlineKeyboardButton("Save to RAG", callback_data=f"save_{article['id']}")
                        ]
                    ]
                    
                    # Format with summary
                    summary = article.get('summary', 'No summary available.')
                    message = (
                        f"*{article['title']}*\n"
                        f"By: {article['author']} · {engagement_info}\n\n"
                        f"{summary}\n\n"
                    )
                else:
                    # 沒有公開URL，使用詳細outline
                    keyboard = [
                        [
                            InlineKeyboardButton("Read Article", url=article['url']),
                            InlineKeyboardButton("Save to RAG", callback_data=f"save_{article['id']}")
                        ]
                    ]
                    
                    # Format with detailed outline
                    message_title = (
                        f"*{article['title']}*\n"
                        f"By: {article['author']} · {engagement_info}\n\n"
                    )
                    
                    # 限制訊息長度，Telegram有限制(最多4096字符)
                    max_length = 4000  # 留一些餘量
                    
                    if len(detailed_outline) > (max_length - len(message_title)):
                        truncated_outline = detailed_outline[:max_length - len(message_title) - 20] + "...(已截斷)"
                        message = message_title + truncated_outline
                    else:
                        message = message_title + detailed_outline
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await self.application.bot.send_message(
                    chat_id=self.chat_id,
                    text=message,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
                print(f"Sent article to Telegram: {article['title']}")
            except Exception as e:
                print(f"Error sending article to Telegram: {e}")

    async def run_async(self):
        """Run the bot asynchronously."""
        if not self.application:
            print("Telegram bot not initialized. Cannot run.")
            # Return without error to allow other components to run
            return
            
        print("Starting Telegram bot polling...")
        try:
            # 正確啟動 Telegram bot
            await self.application.initialize()
            await self.application.start()
            await self.application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
            
            # 使用 signal handler 而不是 idle() 方法
            print("Telegram bot now polling for updates. Press Ctrl+C to stop.")
            
            # 使用簡單的無限循環來保持程序運行
            stop_signal = asyncio.Future()
            await stop_signal
            
        except Exception as e:
            print(f"Error in Telegram bot: {e}")
        finally:
            print("Shutting down Telegram bot...")
            # 嘗試正確關閉機器人
            try:
                if hasattr(self.application, 'updater') and self.application.updater:
                    await self.application.updater.stop()
                await self.application.stop()
                await self.application.shutdown()
            except Exception as e:
                print(f"Error during Telegram bot shutdown: {e}")
                # 即使關閉出錯，也繼續執行 

    # ---------- 資料庫管理命令 ----------
    
    def _is_admin(self, user_id):
        """檢查用戶是否為管理員"""
        return str(user_id) in ADMIN_USER_IDS
    
    async def db_stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """獲取資料庫統計資訊"""
        user_id = update.effective_user.id
        
        # 檢查權限
        if not self._is_admin(user_id):
            await update.message.reply_text("您沒有權限執行此命令，只有管理員可以管理資料庫。")
            return
        
        # 獲取資料庫統計資訊
        db_stats = self.db.get_database_stats()
        vector_stats = self.vector_db.get_vector_database_stats()
        
        # 格式化日期
        newest_date = db_stats.get('newest_article_date', 'N/A')
        if newest_date and newest_date != 'N/A':
            newest_date = newest_date.split('T')[0]
            
        oldest_date = db_stats.get('oldest_article_date', 'N/A')
        if oldest_date and oldest_date != 'N/A':
            oldest_date = oldest_date.split('T')[0]
        
        # 構建統計訊息
        stats_message = (
            "📊 *資料庫統計資訊*\n\n"
            f"- 總文章數: {db_stats.get('total_articles', 0)}\n"
            f"- 已儲存到 RAG 的文章數: {db_stats.get('saved_articles', 0)}\n"
            f"- 有詳細摘要的文章數: {db_stats.get('articles_with_summary', 0)}\n"
            f"- 向量嵌入數量: {vector_stats.get('vector_count', 0)}\n"
            f"- 最新文章日期: {newest_date}\n"
            f"- 最舊文章日期: {oldest_date}\n"
            f"- 主資料庫大小: {db_stats.get('database_size_mb', 0):.2f} MB\n"
            f"- 向量資料庫大小: {vector_stats.get('database_size_mb', 0):.2f} MB\n"
        )
        
        await update.message.reply_text(stats_message, parse_mode='Markdown')
    
    async def db_clean_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """清理舊文章"""
        user_id = update.effective_user.id
        
        # 檢查權限
        if not self._is_admin(user_id):
            await update.message.reply_text("您沒有權限執行此命令，只有管理員可以管理資料庫。")
            return
        
        # 解析參數
        days = 30
        keep_saved = True
        
        if context.args:
            if len(context.args) >= 1 and context.args[0].isdigit():
                days = int(context.args[0])
            if len(context.args) >= 2 and context.args[1].lower() in ('false', 'no', '0'):
                keep_saved = False
        
        # 確認操作
        confirm_message = (
            f"即將清理 {days} 天前的舊文章"
            f"{' (已儲存到 RAG 的文章將被保留)' if keep_saved else ' (包括已儲存到 RAG 的文章)'}"
            f"\n\n確定要執行此操作嗎？"
        )
        
        keyboard = [
            [
                InlineKeyboardButton("確認清理", callback_data=f"dbclean_{days}_{keep_saved}"),
                InlineKeyboardButton("取消", callback_data="dbclean_cancel")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(confirm_message, reply_markup=reply_markup)
    
    async def db_delete_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """刪除特定文章"""
        user_id = update.effective_user.id
        
        # 檢查權限
        if not self._is_admin(user_id):
            await update.message.reply_text("您沒有權限執行此命令，只有管理員可以管理資料庫。")
            return
        
        # 檢查參數
        if not context.args or not context.args[0]:
            await update.message.reply_text("請提供要刪除的文章 ID。例如: /db_delete article_id")
            return
        
        article_id = context.args[0]
        
        # 獲取文章資訊
        article = self.db.get_article(article_id)
        if not article:
            await update.message.reply_text(f"找不到 ID 為 {article_id} 的文章")
            return
        
        # 確認刪除
        confirm_message = (
            f"即將刪除文章:\n\n"
            f"標題: {article['title']}\n"
            f"作者: {article['author']}\n"
            f"發布日期: {article['published_at'].split('T')[0]}\n\n"
            f"確定要刪除此文章嗎？"
        )
        
        keyboard = [
            [
                InlineKeyboardButton("確認刪除", callback_data=f"dbdelete_{article_id}"),
                InlineKeyboardButton("取消", callback_data="dbdelete_cancel")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(confirm_message, reply_markup=reply_markup)
    
    async def db_find_tag_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """根據標籤查詢文章"""
        user_id = update.effective_user.id
        
        # 檢查權限
        if not self._is_admin(user_id):
            await update.message.reply_text("您沒有權限執行此命令，只有管理員可以管理資料庫。")
            return
        
        # 檢查參數
        if not context.args or not context.args[0]:
            await update.message.reply_text("請提供要查詢的標籤。例如: /db_find_tag programming")
            return
        
        tag = context.args[0]
        
        # 查詢文章
        articles = self.db.find_articles_by_tag(tag)
        
        if not articles:
            await update.message.reply_text(f"沒有找到包含標籤 '{tag}' 的文章")
            return
        
        # 限制最多顯示 10 篇，避免訊息過長
        max_display = min(len(articles), 10)
        articles = articles[:max_display]
        
        await update.message.reply_text(f"找到 {len(articles)} 篇包含標籤 '{tag}' 的文章:")
        
        for article in articles:
            # 創建按鈕
            keyboard = [
                [
                    InlineKeyboardButton("閱讀文章", url=article['url']),
                    InlineKeyboardButton("刪除文章", callback_data=f"dbdelete_{article['id']}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # 使用Markdown格式將標題轉換為帶有連結的格式
            title_with_link = f"[{article['title']}]({article['url']})"
            
            # 格式化訊息
            message = (
                f"*{title_with_link}*\n"
                f"作者: {article['author']}\n"
                f"發布日期: {article['published_at'].split('T')[0]}\n"
            )
            
            if article.get('user_tags'):
                if isinstance(article['user_tags'], list):
                    tags_str = ", ".join(article['user_tags'])
                else:
                    tags_str = article['user_tags']
                message += f"用戶標籤: {tags_str}\n"
            
            await update.message.reply_text(
                message,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        
        if len(articles) == max_display and max_display < len(articles):
            await update.message.reply_text(f"僅顯示前 {max_display} 篇結果") 