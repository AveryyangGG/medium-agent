import sqlite3
import json
import os
from datetime import datetime, timedelta
import sys
import threading
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config import DB_PATH

class Database:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.conn = None
        self.lock = threading.Lock()  # 添加線程鎖，確保資料庫操作的安全性
        self.init_db()
    
    def get_connection(self):
        if self.conn is None:
            # 設置 check_same_thread=False 允許跨線程使用連接
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
        return self.conn
    
    def init_db(self):
        conn = self.get_connection()
        with self.lock:  # 使用線程鎖
            cursor = conn.cursor()
            
            # 檢查並添加新列
            try:
                # 先檢查claps和responses列是否存在
                cursor.execute("PRAGMA table_info(articles)")
                columns = cursor.fetchall()
                column_names = [column[1] for column in columns]
                
                # 添加claps列（如果不存在）
                if 'claps' not in column_names:
                    cursor.execute('ALTER TABLE articles ADD COLUMN claps INTEGER DEFAULT 0')
                
                # 添加responses列（如果不存在）
                if 'responses' not in column_names:
                    cursor.execute('ALTER TABLE articles ADD COLUMN responses INTEGER DEFAULT 0')
            except sqlite3.Error as e:
                print(f"檢查或添加新列時出錯: {e}")
            
            # Create articles table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS articles (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                author TEXT NOT NULL,
                url TEXT NOT NULL,
                published_at TEXT NOT NULL,
                tags TEXT,
                content TEXT,
                summary TEXT,
                detailed_summary TEXT,  -- 新增：詳細條列式摘要
                user_tags TEXT,         -- 新增：用戶自定義標籤
                user_notes TEXT,        -- 新增：用戶備註
                is_saved BOOLEAN DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                claps INTEGER DEFAULT 0,
                responses INTEGER DEFAULT 0
            )
            ''')
            
            # Create vector_embeddings table for RAG
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS vector_embeddings (
                id TEXT PRIMARY KEY,
                article_id TEXT NOT NULL,
                embedding_path TEXT NOT NULL,
                FOREIGN KEY (article_id) REFERENCES articles (id)
            )
            ''')
            
            conn.commit()
    
    def add_article(self, article_data):
        conn = self.get_connection()
        with self.lock:  # 使用線程鎖
            cursor = conn.cursor()
            
            # Convert tags list to JSON string if it exists
            if 'tags' in article_data and article_data['tags']:
                article_data['tags'] = json.dumps(article_data['tags'])
            
            try:
                cursor.execute('''
                INSERT OR REPLACE INTO articles (id, title, author, url, published_at, tags, content, summary, claps, responses)
                VALUES (:id, :title, :author, :url, :published_at, :tags, :content, :summary, :claps, :responses)
                ''', article_data)
                conn.commit()
                return True
            except sqlite3.Error as e:
                print(f"Database error: {e}")
                return False
    
    def update_article_with_details(self, article_id, detailed_summary=None, user_tags=None, user_notes=None):
        """更新文章的詳細摘要、用戶標籤和備註"""
        conn = self.get_connection()
        with self.lock:
            cursor = conn.cursor()
            
            # 首先獲取當前文章資料
            cursor.execute('SELECT * FROM articles WHERE id = ?', (article_id,))
            article = cursor.fetchone()
            
            if not article:
                print(f"文章 ID {article_id} 不存在")
                return False
            
            # 準備更新參數
            update_params = {}
            update_fields = []
            
            if detailed_summary is not None:
                update_params['detailed_summary'] = detailed_summary
                update_fields.append("detailed_summary = :detailed_summary")
            
            if user_tags is not None:
                if isinstance(user_tags, list):
                    user_tags = json.dumps(user_tags)
                update_params['user_tags'] = user_tags
                update_fields.append("user_tags = :user_tags")
            
            if user_notes is not None:
                update_params['user_notes'] = user_notes
                update_fields.append("user_notes = :user_notes")
            
            if not update_fields:
                print("無需更新")
                return True
                
            # 構建 SQL 查詢
            update_sql = f"UPDATE articles SET {', '.join(update_fields)} WHERE id = :article_id"
            update_params['article_id'] = article_id
            
            try:
                cursor.execute(update_sql, update_params)
                conn.commit()
                return True
            except sqlite3.Error as e:
                print(f"更新文章詳細資訊時出錯: {e}")
                return False
    
    def save_article_to_rag(self, article_id):
        conn = self.get_connection()
        with self.lock:  # 使用線程鎖
            cursor = conn.cursor()
            
            try:
                cursor.execute('''
                UPDATE articles SET is_saved = 1 WHERE id = ?
                ''', (article_id,))
                conn.commit()
                return True
            except sqlite3.Error as e:
                print(f"Database error: {e}")
                return False
    
    def get_article(self, article_id):
        conn = self.get_connection()
        with self.lock:  # 使用線程鎖
            cursor = conn.cursor()
            
            cursor.execute('SELECT * FROM articles WHERE id = ?', (article_id,))
            row = cursor.fetchone()
            
            if row:
                article = dict(row)
                if 'tags' in article and article['tags']:
                    article['tags'] = json.loads(article['tags'])
                if 'user_tags' in article and article['user_tags']:
                    try:
                        article['user_tags'] = json.loads(article['user_tags'])
                    except:
                        # 如果不是 JSON 格式，保留原始字符串
                        pass
                return article
            return None
    
    def get_recent_articles(self, limit=10):
        conn = self.get_connection()
        with self.lock:  # 使用線程鎖
            cursor = conn.cursor()
            
            cursor.execute('''
            SELECT * FROM articles 
            ORDER BY published_at DESC 
            LIMIT ?
            ''', (limit,))
            
            rows = cursor.fetchall()
            articles = []
            for row in rows:
                article = dict(row)
                if 'tags' in article and article['tags']:
                    article['tags'] = json.loads(article['tags'])
                if 'user_tags' in article and article['user_tags']:
                    try:
                        article['user_tags'] = json.loads(article['user_tags'])
                    except:
                        # 如果不是 JSON 格式，保留原始字符串
                        pass
                articles.append(article)
            
            return articles
    
    def delete_article(self, article_id):
        """刪除指定ID的文章"""
        conn = self.get_connection()
        with self.lock:
            cursor = conn.cursor()
            
            try:
                # 首先檢查文章是否存在
                cursor.execute('SELECT id FROM articles WHERE id = ?', (article_id,))
                if not cursor.fetchone():
                    print(f"文章 ID {article_id} 不存在")
                    return False
                
                # 刪除相關的向量嵌入記錄
                cursor.execute('DELETE FROM vector_embeddings WHERE article_id = ?', (article_id,))
                
                # 刪除文章記錄
                cursor.execute('DELETE FROM articles WHERE id = ?', (article_id,))
                
                conn.commit()
                print(f"成功刪除文章 ID {article_id}")
                return True
            except sqlite3.Error as e:
                print(f"刪除文章時出錯: {e}")
                return False
    
    def clean_old_articles(self, days=30, keep_saved=True):
        """清理超過指定天數的舊文章
        
        參數:
            days: 要保留的天數，超過此天數的文章將被刪除
            keep_saved: 是否保留已儲存到 RAG 的文章
        
        返回:
            已刪除的文章數量
        """
        conn = self.get_connection()
        with self.lock:
            cursor = conn.cursor()
            
            try:
                # 計算截止日期 - 使用 timedelta 來正確計算
                threshold_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                threshold_date = threshold_date - timedelta(days=days)
                threshold_str = threshold_date.isoformat()
                
                # 獲取符合條件的文章 ID
                if keep_saved:
                    cursor.execute('''
                    SELECT id FROM articles 
                    WHERE published_at < ? AND is_saved = 0
                    ''', (threshold_str,))
                else:
                    cursor.execute('''
                    SELECT id FROM articles 
                    WHERE published_at < ?
                    ''', (threshold_str,))
                
                article_ids = [row[0] for row in cursor.fetchall()]
                
                if not article_ids:
                    print("沒有符合條件的舊文章需要清理")
                    return 0
                
                # 刪除相關的向量嵌入
                placeholders = ','.join(['?' for _ in article_ids])
                cursor.execute(f'''
                DELETE FROM vector_embeddings 
                WHERE article_id IN ({placeholders})
                ''', article_ids)
                
                # 刪除文章
                cursor.execute(f'''
                DELETE FROM articles 
                WHERE id IN ({placeholders})
                ''', article_ids)
                
                conn.commit()
                count = len(article_ids)
                print(f"已清理 {count} 篇舊文章")
                return count
            except sqlite3.Error as e:
                print(f"清理舊文章時出錯: {e}")
                return 0
    
    def get_database_stats(self):
        """獲取資料庫統計資訊"""
        conn = self.get_connection()
        with self.lock:
            cursor = conn.cursor()
            
            stats = {}
            
            try:
                # 獲取文章總數
                cursor.execute('SELECT COUNT(*) FROM articles')
                stats['total_articles'] = cursor.fetchone()[0]
                
                # 獲取已保存到 RAG 的文章數量
                cursor.execute('SELECT COUNT(*) FROM articles WHERE is_saved = 1')
                stats['saved_articles'] = cursor.fetchone()[0]
                
                # 獲取有詳細摘要的文章數量
                cursor.execute('SELECT COUNT(*) FROM articles WHERE detailed_summary IS NOT NULL')
                stats['articles_with_summary'] = cursor.fetchone()[0]
                
                # 獲取向量嵌入數量
                cursor.execute('SELECT COUNT(*) FROM vector_embeddings')
                stats['total_embeddings'] = cursor.fetchone()[0]
                
                # 獲取最近一篇文章的日期
                cursor.execute('SELECT published_at FROM articles ORDER BY published_at DESC LIMIT 1')
                result = cursor.fetchone()
                stats['newest_article_date'] = result[0] if result else None
                
                # 獲取最舊一篇文章的日期
                cursor.execute('SELECT published_at FROM articles ORDER BY published_at ASC LIMIT 1')
                result = cursor.fetchone()
                stats['oldest_article_date'] = result[0] if result else None
                
                # 獲取資料庫檔案大小 (以 MB 為單位)
                if os.path.exists(self.db_path):
                    stats['database_size_mb'] = os.path.getsize(self.db_path) / (1024 * 1024)
                else:
                    stats['database_size_mb'] = 0
                
                return stats
            except sqlite3.Error as e:
                print(f"獲取資料庫統計資訊時出錯: {e}")
                return {"error": str(e)}
    
    def find_articles_by_tag(self, tag):
        """根據標籤查詢文章"""
        conn = self.get_connection()
        with self.lock:
            cursor = conn.cursor()
            
            try:
                # 尋找原始標籤或用戶標籤包含指定標籤的文章
                # 由於標籤儲存為 JSON 字符串，需要使用 LIKE 進行模糊匹配
                cursor.execute('''
                SELECT * FROM articles 
                WHERE tags LIKE ? OR user_tags LIKE ?
                ORDER BY published_at DESC
                ''', (f'%{tag}%', f'%{tag}%'))
                
                rows = cursor.fetchall()
                articles = []
                for row in rows:
                    article = dict(row)
                    if 'tags' in article and article['tags']:
                        article['tags'] = json.loads(article['tags'])
                    if 'user_tags' in article and article['user_tags']:
                        try:
                            article['user_tags'] = json.loads(article['user_tags'])
                        except:
                            pass
                    articles.append(article)
                
                return articles
            except sqlite3.Error as e:
                print(f"根據標籤查詢文章時出錯: {e}")
                return []
    
    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None 

    def search_articles_by_keyword(self, query: str, limit: int = 10) -> list:
        """Search articles by keyword in title, tags, or user_tags."""
        conn = self.get_connection()
        with self.lock:
            cursor = conn.cursor()
            search_term = f'%{query}%'
            sql_query = """
                SELECT * FROM articles 
                WHERE title LIKE ? 
                   OR tags LIKE ? 
                   OR user_tags LIKE ?
                ORDER BY published_at DESC 
                LIMIT ?
            """
            params = (search_term, search_term, search_term, limit)

            # --- Debugging Log --- 
            # print(f"DEBUG: Executing SQL for keyword search:")
            # print(f"DEBUG: Query: {sql_query}")
            # print(f"DEBUG: Params: {params}")
            # ---------------------

            try:
                cursor.execute(sql_query, params)
                
                rows = cursor.fetchall()
                # --- Debugging Log --- 
                # print(f"DEBUG: Found {len(rows)} articles for query '{query}'")
                # ---------------------
                articles = []
                for row in rows:
                    article = dict(row)
                    # Deserialize JSON tags
                    if 'tags' in article and article['tags']:
                        try:
                            article['tags'] = json.loads(article['tags'])
                        except json.JSONDecodeError:
                            # Keep as string if not valid JSON (fallback)
                            pass 
                    if 'user_tags' in article and article['user_tags']:
                        try:
                            article['user_tags'] = json.loads(article['user_tags'])
                        except json.JSONDecodeError:
                            # Keep as string if not valid JSON (fallback)
                             pass
                    articles.append(article)
                
                return articles
            except sqlite3.Error as e:
                print(f"Error searching articles by keyword: {e}")
                return [] 