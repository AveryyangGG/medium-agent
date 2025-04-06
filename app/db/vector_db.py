import os
import sys
import json
from voyageai import get_embedding
import chromadb
from chromadb.config import Settings

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config import VECTOR_DB_PATH, VOYAGE_API_KEY, VOYAGE_MODEL
from app.db.database import Database

class VectorDatabase:
    def __init__(self, db_path=VECTOR_DB_PATH):
        self.db_path = db_path
        os.makedirs(db_path, exist_ok=True)
        self.client = chromadb.PersistentClient(path=db_path)
        self.collection = self.client.get_or_create_collection(
            name="medium_articles",
            metadata={"hnsw:space": "cosine"}
        )
        self.database = Database()
        
    def get_embedding(self, text):
        """Get embedding from Voyage AI"""
        if not text:
            return []
        
        # 簡化文本長度以避免 API 限制問題
        # Voyage API 通常有字符限制，這裡限制為 8000 字符
        max_chars = 8000
        if len(text) > max_chars:
            text = text[:max_chars]
        
        # 簡單的重試邏輯
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = get_embedding(
                    text, 
                    model=VOYAGE_MODEL, 
                    api_key=VOYAGE_API_KEY,
                    timeout=30  # 增加超時時間避免請求中斷
                )
                return response
            except Exception as e:
                print(f"Error getting embedding (attempt {attempt+1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    import time
                    # 指數退避重試，每次等待時間為 2^attempt 秒
                    wait_time = 2 ** attempt
                    print(f"Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
                else:
                    print("Failed all embedding attempts")
                    # 如果所有嘗試都失敗，返回空列表
                    return []
    
    def add_article_to_rag(self, article_id):
        """Add an article to the RAG database"""
        # Get article from the regular database
        article = self.database.get_article(article_id)
        
        if not article:
            print(f"Article {article_id} not found")
            return False
        
        # Prepare text for embedding - combine title and content
        text_to_embed = f"{article['title']} {article['content']}"
        
        # Get embedding
        embedding = self.get_embedding(text_to_embed)
        
        if not embedding:
            print(f"Failed to get embedding for article {article_id}")
            return False
        
        # Add to ChromaDB
        try:
            self.collection.add(
                ids=[article_id],
                embeddings=[embedding],
                metadatas=[{
                    "title": article["title"],
                    "author": article["author"],
                    "url": article["url"],
                    "published_at": article["published_at"],
                    "summary": article["summary"]
                }],
                documents=[text_to_embed]
            )
            
            # Update the article as saved in the regular database
            self.database.save_article_to_rag(article_id)
            
            return True
        except Exception as e:
            print(f"Error adding to ChromaDB: {e}")
            return False
    
    def query_similar_articles(self, query_text, n_results=5):
        """Query the vector database for articles similar to the query"""
        query_embedding = self.get_embedding(query_text)
        
        if not query_embedding:
            print("Failed to get embedding for query")
            return []
        
        try:
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=n_results
            )
            
            # Format results
            formatted_results = []
            for i, doc_id in enumerate(results["ids"][0]):
                metadata = results["metadatas"][0][i]
                formatted_results.append({
                    "id": doc_id,
                    "title": metadata["title"],
                    "author": metadata["author"],
                    "url": metadata["url"],
                    "published_at": metadata["published_at"],
                    "summary": metadata["summary"],
                    "similarity_score": results["distances"][0][i] if "distances" in results else None
                })
            
            return formatted_results
        except Exception as e:
            print(f"Error querying ChromaDB: {e}")
            return []
    
    def delete_article_embedding(self, article_id):
        """從向量資料庫中刪除文章的嵌入向量"""
        try:
            # 檢查文章是否在向量資料庫中
            results = self.collection.get(
                ids=[article_id],
                include=[]
            )
            
            if article_id not in results["ids"]:
                print(f"向量資料庫中沒有文章 ID {article_id} 的嵌入向量")
                return False
            
            # 從向量資料庫中刪除
            self.collection.delete(ids=[article_id])
            
            # 同時更新文章在普通資料庫中的狀態
            self.database.get_connection().execute(
                "UPDATE articles SET is_saved = 0 WHERE id = ?",
                (article_id,)
            )
            self.database.get_connection().commit()
            
            print(f"成功從向量資料庫中刪除文章 ID {article_id} 的嵌入向量")
            return True
        except Exception as e:
            print(f"從向量資料庫刪除文章時出錯: {e}")
            return False
    
    def clean_vector_database(self):
        """清理向量資料庫中的孤立嵌入（其對應文章已從資料庫中刪除）"""
        try:
            # 獲取向量資料庫中所有文章的 ID
            all_results = self.collection.get(include=[])
            vector_article_ids = all_results["ids"]
            
            if not vector_article_ids:
                print("向量資料庫中沒有任何嵌入向量")
                return 0
            
            # 獲取普通資料庫中存在的文章 ID
            existing_ids = []
            conn = self.database.get_connection()
            cursor = conn.cursor()
            
            placeholders = ','.join(['?' for _ in vector_article_ids])
            cursor.execute(f"SELECT id FROM articles WHERE id IN ({placeholders})", vector_article_ids)
            
            existing_ids = [row[0] for row in cursor.fetchall()]
            
            # 找出需要刪除的 ID（存在於向量資料庫但不存在於普通資料庫的 ID）
            ids_to_delete = [id for id in vector_article_ids if id not in existing_ids]
            
            if not ids_to_delete:
                print("沒有需要清理的孤立嵌入向量")
                return 0
                
            # 從向量資料庫中刪除
            self.collection.delete(ids=ids_to_delete)
            
            print(f"清理了 {len(ids_to_delete)} 個孤立的嵌入向量")
            return len(ids_to_delete)
        except Exception as e:
            print(f"清理向量資料庫時出錯: {e}")
            return 0
    
    def get_vector_database_stats(self):
        """獲取向量資料庫的統計資訊"""
        try:
            # 獲取向量資料庫中的文章數量
            all_results = self.collection.get(include=[])
            vector_count = len(all_results["ids"])
            
            # 獲取向量資料庫的大小
            db_size_mb = 0
            if os.path.exists(self.db_path):
                # 遍歷資料夾計算總大小
                for dirpath, dirnames, filenames in os.walk(self.db_path):
                    for f in filenames:
                        fp = os.path.join(dirpath, f)
                        db_size_mb += os.path.getsize(fp)
                db_size_mb = db_size_mb / (1024 * 1024)  # 轉換為 MB
            
            return {
                "vector_count": vector_count,
                "database_size_mb": db_size_mb
            }
        except Exception as e:
            print(f"獲取向量資料庫統計資訊時出錯: {e}")
            return {"error": str(e)} 