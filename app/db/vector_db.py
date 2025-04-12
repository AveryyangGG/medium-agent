import os
import sys
import json
from voyageai import get_embedding
import chromadb
from chromadb.config import Settings
import re
import uuid
import hashlib
import pickle
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional, Union

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config import VECTOR_DB_PATH, VOYAGE_API_KEY, VOYAGE_MODEL
from app.db.database import Database

# Remove the bypass embedding code - instead we'll properly handle large inputs
# BYPASS_EMBEDDING_API = os.getenv("BYPASS_EMBEDDING_API", "").lower() in ("true", "1", "yes")

# Model specific configurations
VOYAGE_MODEL_CONFIGS = {
    "voyage-large-2": {"max_chars": 16000, "dimensions": 1536},
    "voyage-2": {"max_chars": 4000, "dimensions": 1024},
    "voyage-3": {"max_chars": 16000, "dimensions": 1536},
    "voyage-3-lite": {"max_chars": 4000, "dimensions": 768},
    "voyage-3-large": {"max_chars": 16000, "dimensions": 1536},
    # Default for unknown models
    "default": {"max_chars": 4000, "dimensions": 1024}
}

# Global max chunk size - keep this smaller than model limits to avoid timeouts
# Some APIs may timeout on chunks that are technically within their token limits
MAX_CHUNK_SIZE = 3000
CHUNK_OVERLAP = 200  # Amount of text overlap between consecutive chunks

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
        
        # Get the model config based on the current model
        self.model_config = VOYAGE_MODEL_CONFIGS.get(
            VOYAGE_MODEL, 
            VOYAGE_MODEL_CONFIGS["default"]
        )
        print(f"Using embedding model {VOYAGE_MODEL} with config: {self.model_config}")
        
        # Initialize embedding cache
        self.cache_dir = os.path.join(db_path, "embedding_cache")
        os.makedirs(self.cache_dir, exist_ok=True)
        self.cache_ttl = timedelta(days=30)  # Cache expiration time
        
    def _get_cache_key(self, text: str) -> str:
        """Generate a cache key based on text content and model"""
        # Create hash based on text content and model name
        hash_input = f"{text}:{VOYAGE_MODEL}"
        return hashlib.md5(hash_input.encode('utf-8')).hexdigest()
    
    def _get_from_cache(self, text: str) -> Optional[List[float]]:
        """Try to get embedding from cache"""
        cache_key = self._get_cache_key(text)
        cache_file = os.path.join(self.cache_dir, f"{cache_key}.pkl")
        
        if os.path.exists(cache_file):
            try:
                # Check if cache entry is expired
                modification_time = datetime.fromtimestamp(os.path.getmtime(cache_file))
                if datetime.now() - modification_time > self.cache_ttl:
                    # Cache expired, remove it
                    os.remove(cache_file)
                    return None
                    
                # Load cached embedding
                with open(cache_file, 'rb') as f:
                    cache_data = pickle.load(f)
                    print(f"Using cached embedding for text of {len(text)} chars")
                    return cache_data['embedding']
            except Exception as e:
                print(f"Error reading from cache: {e}")
                # Remove corrupt cache file
                try:
                    os.remove(cache_file)
                except:
                    pass
        
        return None
    
    def _save_to_cache(self, text: str, embedding: List[float]) -> bool:
        """Save embedding to cache"""
        try:
            cache_key = self._get_cache_key(text)
            cache_file = os.path.join(self.cache_dir, f"{cache_key}.pkl")
            
            cache_data = {
                'text_length': len(text),
                'model': VOYAGE_MODEL,
                'embedding': embedding,
                'timestamp': datetime.now()
            }
            
            with open(cache_file, 'wb') as f:
                pickle.dump(cache_data, f)
            
            return True
        except Exception as e:
            print(f"Error saving to cache: {e}")
            return False
    
    def clean_embedding_cache(self, max_age_days: int = 30) -> int:
        """Clean expired entries from the embedding cache"""
        cleaned_count = 0
        max_age = timedelta(days=max_age_days)
        now = datetime.now()
        
        try:
            for cache_file in os.listdir(self.cache_dir):
                if cache_file.endswith('.pkl'):
                    file_path = os.path.join(self.cache_dir, cache_file)
                    modification_time = datetime.fromtimestamp(os.path.getmtime(file_path))
                    
                    if now - modification_time > max_age:
                        os.remove(file_path)
                        cleaned_count += 1
            
            print(f"Cleaned {cleaned_count} expired cache entries")
            return cleaned_count
        except Exception as e:
            print(f"Error cleaning cache: {e}")
            return 0
    
    def chunk_text(self, text: str, max_chars: int = None, overlap: int = None) -> List[str]:
        """
        Split text into semantically meaningful chunks that are under the max_chars limit.
        Uses a mixture of paragraph and sentence splitting to preserve meaning.
        
        Parameters:
            text: The text to chunk
            max_chars: Maximum characters per chunk (defaults to model's max_chars)
            overlap: Number of characters to overlap between chunks (defaults to CHUNK_OVERLAP)
            
        Returns:
            List of text chunks
        """
        if max_chars is None:
            # Use the smaller of model max and global max
            model_max = self.model_config["max_chars"]
            max_chars = min(model_max, MAX_CHUNK_SIZE)
            print(f"Using chunk size of {max_chars} (model max: {model_max})")
        
        if overlap is None:
            overlap = CHUNK_OVERLAP
            
        if len(text) <= max_chars:
            return [text]
        
        # Detect content type to select appropriate chunking strategy
        # Check for markdown-like structure
        has_markdown = bool(re.search(r'#{1,6}\s+|[*_]{1,2}[^*_]+[*_]{1,2}|\[.+?\]\(.+?\)', text))
        # Check for code blocks
        has_code_blocks = bool(re.search(r'```[\s\S]+?```|`[^`]+`', text))
        # Check for bullet points or numbered lists
        has_lists = bool(re.search(r'(?m)^(\s*[-*+]|\s*\d+\.)\s+\S+', text))
        
        chunking_strategy = "default"
        if has_code_blocks:
            chunking_strategy = "code_aware"
        elif has_markdown and has_lists:
            chunking_strategy = "markdown_aware"
            
        print(f"Selected chunking strategy: {chunking_strategy}")
        
        # Use strategy-specific chunking
        if chunking_strategy == "code_aware":
            return self._chunk_code_aware(text, max_chars, overlap)
        elif chunking_strategy == "markdown_aware":
            return self._chunk_markdown_aware(text, max_chars, overlap)
        else:
            return self._chunk_default(text, max_chars, overlap)
    
    def _chunk_default(self, text: str, max_chars: int, overlap: int) -> List[str]:
        """Default chunking strategy using paragraphs and sentences"""
        # First try to split by paragraphs (double newline)
        paragraphs = re.split(r'\n\s*\n', text)
        
        chunks = []
        current_chunk = ""
        
        for paragraph in paragraphs:
            # If a single paragraph is too long, we'll need to split it by sentences
            if len(paragraph) > max_chars:
                # Process this large paragraph separately
                if current_chunk:
                    chunks.append(current_chunk)
                    current_chunk = ""
                
                # Split the paragraph by sentences
                sentences = re.split(r'(?<=[.!?])\s+', paragraph)
                sentence_chunk = ""
                
                for sentence in sentences:
                    # Handle the case where a single sentence is too long
                    if len(sentence) > max_chars:
                        if sentence_chunk:
                            chunks.append(sentence_chunk)
                            sentence_chunk = ""
                        
                        # Split the sentence into parts
                        for i in range(0, len(sentence) - overlap, max_chars - overlap):
                            # For the last chunk, don't go beyond the end of the sentence
                            end = min(i + max_chars, len(sentence))
                            chunks.append(sentence[i:end])
                    
                    # Normal case - try to add the sentence to the current chunk
                    elif len(sentence_chunk) + len(sentence) + 1 <= max_chars:
                        if sentence_chunk:
                            sentence_chunk += " " + sentence
                        else:
                            sentence_chunk = sentence
                    else:
                        chunks.append(sentence_chunk)
                        sentence_chunk = sentence
                
                if sentence_chunk:
                    chunks.append(sentence_chunk)
            
            # Normal case - paragraph fits within limit
            elif len(current_chunk) + len(paragraph) + 2 <= max_chars:
                if current_chunk:
                    current_chunk += "\n\n" + paragraph
                else:
                    current_chunk = paragraph
            else:
                chunks.append(current_chunk)
                current_chunk = paragraph
        
        if current_chunk:
            chunks.append(current_chunk)
        
        # Add overlapping text between chunks
        if overlap > 0 and len(chunks) > 1:
            overlapped_chunks = [chunks[0]]
            
            for i in range(1, len(chunks)):
                prev_chunk = chunks[i-1]
                current_chunk = chunks[i]
                
                # Get overlap text from previous chunk (if possible)
                if len(prev_chunk) >= overlap:
                    overlap_text = prev_chunk[-overlap:]
                    overlapped_chunks.append(overlap_text + current_chunk)
                else:
                    overlapped_chunks.append(current_chunk)
            
            chunks = overlapped_chunks
            
        print(f"Split text of {len(text)} chars into {len(chunks)} chunks")
        return chunks
    
    def _chunk_markdown_aware(self, text: str, max_chars: int, overlap: int) -> List[str]:
        """
        Chunk text with awareness of markdown structures like headers, lists, etc.
        Tries to keep related markdown elements together.
        """
        # First identify markdown structural elements (headers, list items, etc.)
        # Headers
        header_positions = [(m.start(), m.end()) for m in re.finditer(r'(?m)^(#{1,6}\s+.+)$', text)]
        # List items
        list_item_positions = [(m.start(), m.end()) for m in re.finditer(r'(?m)^(\s*[-*+]|\s*\d+\.)\s+.+$', text)]
        
        # Combine all structural markers in order
        structure_markers = sorted(header_positions + list_item_positions)
        
        if not structure_markers:
            # No markdown structure detected, fall back to default
            return self._chunk_default(text, max_chars, overlap)
        
        # Use markdown structure to guide chunking
        chunks = []
        chunk_start = 0
        current_chunk = ""
        
        for i, (marker_start, marker_end) in enumerate(structure_markers):
            # Text from chunk_start to marker_start belongs to the previous section
            section_text = text[chunk_start:marker_start].strip()
            
            # The marker itself (header or list item)
            marker_text = text[marker_start:marker_end]
            
            # Find the end of the current section (next marker or end of text)
            next_section_start = structure_markers[i+1][0] if i < len(structure_markers)-1 else len(text)
            section_content = text[marker_end:next_section_start].strip()
            
            # Combine marker with its content
            full_section = f"{marker_text}\n{section_content}"
            
            # If adding this section exceeds max_chars, start a new chunk
            if len(current_chunk) + len(full_section) > max_chars:
                if current_chunk:
                    chunks.append(current_chunk)
                
                # If the section itself is too large, split it further
                if len(full_section) > max_chars:
                    # Split large sections by paragraphs or sentences
                    sub_chunks = self._chunk_default(full_section, max_chars, overlap)
                    chunks.extend(sub_chunks)
                    current_chunk = ""
                else:
                    current_chunk = full_section
            else:
                # Add section to current chunk
                if current_chunk:
                    current_chunk += "\n\n" + full_section
                else:
                    current_chunk = full_section
            
            chunk_start = next_section_start
        
        # Add the final chunk if there is one
        if current_chunk:
            chunks.append(current_chunk)
        
        # Add final text after the last marker
        if chunk_start < len(text):
            final_text = text[chunk_start:].strip()
            if final_text:
                if len(chunks) > 0 and len(chunks[-1]) + len(final_text) + 2 <= max_chars:
                    chunks[-1] += "\n\n" + final_text
                else:
                    if len(final_text) > max_chars:
                        final_chunks = self._chunk_default(final_text, max_chars, overlap)
                        chunks.extend(final_chunks)
                    else:
                        chunks.append(final_text)
        
        # Add overlapping text between chunks
        if overlap > 0 and len(chunks) > 1:
            overlapped_chunks = [chunks[0]]
            
            for i in range(1, len(chunks)):
                prev_chunk = chunks[i-1]
                current_chunk = chunks[i]
                
                # Get overlap text from previous chunk (if possible)
                if len(prev_chunk) >= overlap:
                    overlap_text = prev_chunk[-overlap:]
                    overlapped_chunks.append(overlap_text + current_chunk)
                else:
                    overlapped_chunks.append(current_chunk)
            
            chunks = overlapped_chunks
        
        print(f"Split markdown text of {len(text)} chars into {len(chunks)} chunks")
        return chunks
    
    def _chunk_code_aware(self, text: str, max_chars: int, overlap: int) -> List[str]:
        """
        Chunk text with awareness of code blocks.
        Tries to keep code blocks intact.
        """
        # Identify code blocks
        code_blocks = list(re.finditer(r'```[\s\S]+?```|`[^`]+`', text))
        
        if not code_blocks:
            # No code blocks detected, fall back to default
            return self._chunk_default(text, max_chars, overlap)
        
        # Use code block boundaries to guide chunking
        chunks = []
        chunk_start = 0
        current_chunk = ""
        
        for code_match in code_blocks:
            code_start, code_end = code_match.span()
            
            # Text before the code block
            pre_code_text = text[chunk_start:code_start].strip()
            
            # The code block itself
            code_block = text[code_start:code_end]
            
            # Check if adding pre-code text and code block would exceed limit
            if len(current_chunk) + len(pre_code_text) + len(code_block) + 4 <= max_chars:
                # Can fit both pre-code text and code block
                if current_chunk:
                    if pre_code_text:
                        current_chunk += "\n\n" + pre_code_text
                    current_chunk += "\n\n" + code_block
                else:
                    current_chunk = (pre_code_text + "\n\n" + code_block).strip()
            else:
                # Cannot fit both, need to create new chunks
                
                # First add current chunk if not empty
                if current_chunk:
                    chunks.append(current_chunk)
                    current_chunk = ""
                
                # Then handle pre-code text if it exists
                if pre_code_text:
                    if len(pre_code_text) > max_chars:
                        # Split pre-code text if too large
                        pre_chunks = self._chunk_default(pre_code_text, max_chars, overlap)
                        chunks.extend(pre_chunks[:-1])  # Add all but last pre-chunk
                        current_chunk = pre_chunks[-1]  # Start with last pre-chunk
                    else:
                        current_chunk = pre_code_text
                
                # Now handle the code block
                if len(current_chunk) + len(code_block) + 2 <= max_chars:
                    # Code block can be added to current chunk
                    if current_chunk:
                        current_chunk += "\n\n" + code_block
                    else:
                        current_chunk = code_block
                else:
                    # Code block needs to be in its own chunk
                    if current_chunk:
                        chunks.append(current_chunk)
                    
                    if len(code_block) > max_chars:
                        # Code block itself is too large, split it
                        # Try to preserve the code block markers
                        if code_block.startswith("```") and code_block.endswith("```"):
                            # Extract language and opening/closing markers
                            first_line_end = code_block.find("\n")
                            if first_line_end > 0:
                                opening = code_block[:first_line_end+1]  # Include newline
                                closing = "\n```"
                                code_content = code_block[first_line_end+1:-3].strip()
                                
                                # Split code content
                                code_chunks = []
                                for i in range(0, len(code_content), max_chars - len(opening) - len(closing)):
                                    chunk_end = min(i + max_chars - len(opening) - len(closing), len(code_content))
                                    code_chunks.append(opening + code_content[i:chunk_end] + closing)
                                
                                chunks.extend(code_chunks)
                            else:
                                # Can't parse code block properly, just split it
                                for i in range(0, len(code_block), max_chars):
                                    chunks.append(code_block[i:i+max_chars])
                        else:
                            # Simple code block, just split it
                            for i in range(0, len(code_block), max_chars):
                                chunks.append(code_block[i:i+max_chars])
                    else:
                        chunks.append(code_block)
                    
                    current_chunk = ""
            
            chunk_start = code_end
        
        # Handle text after the last code block
        if chunk_start < len(text):
            post_code_text = text[chunk_start:].strip()
            
            if post_code_text:
                if current_chunk and len(current_chunk) + len(post_code_text) + 2 <= max_chars:
                    # Can fit in current chunk
                    current_chunk += "\n\n" + post_code_text
                else:
                    # Add current chunk first if not empty
                    if current_chunk:
                        chunks.append(current_chunk)
                        current_chunk = ""
                    
                    # Split post-code text if needed
                    if len(post_code_text) > max_chars:
                        post_chunks = self._chunk_default(post_code_text, max_chars, overlap)
                        chunks.extend(post_chunks)
                    else:
                        chunks.append(post_code_text)
        
        # Add the final chunk if not empty
        if current_chunk:
            chunks.append(current_chunk)
        
        # Add overlapping text between chunks
        if overlap > 0 and len(chunks) > 1:
            overlapped_chunks = [chunks[0]]
            
            for i in range(1, len(chunks)):
                prev_chunk = chunks[i-1]
                current_chunk = chunks[i]
                
                # Get overlap text from previous chunk (if possible)
                if len(prev_chunk) >= overlap:
                    overlap_text = prev_chunk[-overlap:]
                    overlapped_chunks.append(overlap_text + current_chunk)
                else:
                    overlapped_chunks.append(current_chunk)
            
            chunks = overlapped_chunks
        
        print(f"Split code-aware text of {len(text)} chars into {len(chunks)} chunks")
        return chunks
        
    def get_embedding_for_large_text(self, text: str) -> List[float]:
        """
        Get embedding for potentially large text by chunking and averaging embeddings.
        
        Parameters:
            text: The text to embed
            
        Returns:
            The final embedding vector
        """
        if not text:
            print("ERROR: Empty text provided for embedding")
            return []
            
        # Split text into smaller chunks
        chunks = self.chunk_text(text)
        
        if not chunks:
            print("ERROR: Failed to create text chunks")
            return []
            
        # If there's only one chunk, just get its embedding directly
        if len(chunks) == 1:
            return self.get_embedding_for_chunk(chunks[0])
            
        # For multiple chunks, get embeddings for each and average them
        # We'll start with a small number of chunks to test API responsiveness
        print(f"Getting embeddings for {len(chunks)} chunks")
        embeddings = []
        
        # Process chunks in batches to avoid overwhelming the API
        for i, chunk in enumerate(chunks):
            print(f"Processing chunk {i+1}/{len(chunks)} ({len(chunk)} chars)")
            
            # Add a delay between API calls to avoid rate limiting
            if i > 0:
                import time
                print("Pausing between API calls to avoid rate limits...")
                time.sleep(2)  # 2 second pause between API calls
                
            emb = self.get_embedding_for_chunk(chunk)
            if emb:
                embeddings.append(emb)
                print(f"Successfully processed chunk {i+1}/{len(chunks)}")
            else:
                print(f"WARNING: Failed to get embedding for chunk {i+1}. Continuing with remaining chunks.")
                
        if not embeddings:
            print("ERROR: Failed to get embeddings for any chunks")
            return []
            
        # Average the embeddings
        import numpy as np
        avg_embedding = np.mean(embeddings, axis=0).tolist()
        print(f"Created averaged embedding from {len(embeddings)}/{len(chunks)} chunks")
        
        # Check if we got at least 50% of chunks embedded
        success_rate = len(embeddings) / len(chunks)
        if success_rate < 0.5:
            print(f"WARNING: Only embedded {success_rate:.0%} of the text chunks. Embedding may be less accurate.")
        
        return avg_embedding
        
    def get_embedding_for_chunk(self, text: str) -> List[float]:
        """Get embedding from Voyage AI for a single chunk of text"""
        if not text:
            print("ERROR: Empty text provided for embedding")
            return []
        
        # Check text is under limit
        max_chars = min(self.model_config["max_chars"], MAX_CHUNK_SIZE)
        if len(text) > max_chars:
            print(f"WARNING: Text length {len(text)} exceeds limit of {max_chars}, truncating")
            text = text[:max_chars]
        
        # Try to get embedding from cache first
        cached_embedding = self._get_from_cache(text)
        if cached_embedding is not None:
            return cached_embedding
        
        # Retry logic
        max_retries = 3
        for attempt in range(max_retries):
            try:
                print(f"Attempting to get embedding (attempt {attempt+1}/{max_retries}) for {len(text)} chars")
                
                # Use a separate thread with timeout to catch hanging API calls
                import threading
                import queue
                import time
                start_time = time.time()

                def api_call():
                    try:
                        result = get_embedding(
                    text, 
                    model=VOYAGE_MODEL, 
                    api_key=VOYAGE_API_KEY,
                            timeout=30
                        )
                        result_queue.put(("success", result))
                    except Exception as e:
                        result_queue.put(("error", str(e)))

                result_queue = queue.Queue()
                api_thread = threading.Thread(target=api_call)
                api_thread.daemon = True
                api_thread.start()
                
                # Wait for the thread to complete or timeout
                # Reduced timeout to fail faster when API is unresponsive
                api_thread.join(timeout=40)  # Wait for 40 seconds
                elapsed = time.time() - start_time
                
                if api_thread.is_alive():
                    # If the thread is still running, it's likely hung
                    print(f"ERROR: Embedding API call timed out after {elapsed:.1f} seconds")
                    # We'll continue to the next attempt
                    continue
                
                if not result_queue.empty():
                    status, result = result_queue.get()
                    if status == "success":
                        print(f"Successfully received embedding response in {elapsed:.1f} seconds")
                        print(f"Embedding dimensions: {len(result)}")
                        
                        # Save successful embedding to cache
                        self._save_to_cache(text, result)
                        
                        return result
                    else:
                        # Error was caught in the thread
                        raise Exception(result)
                else:
                    print("ERROR: API call thread completed but no result was returned")
                    continue
                
            except Exception as e:
                print(f"Error getting embedding (attempt {attempt+1}/{max_retries}): {str(e)}")
                # Print more detailed error information
                import traceback
                print(f"Error details: {traceback.format_exc()}")
                
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
    
    def get_embedding(self, text):
        """Get embedding from Voyage AI - this is a wrapper around the chunking approach"""
        return self.get_embedding_for_large_text(text)
    
    def add_article_to_rag(self, article_id, retry_without_embedding=False):
        """Add an article to the RAG database
        
        Parameters:
            article_id: The ID of the article to add
            retry_without_embedding: If True, skip embedding and just mark as saved in the database
        """
        # Get article from the regular database
        article = self.database.get_article(article_id)
        
        if not article:
            print(f"Article {article_id} not found")
            return False
        
        # Debug: Print article keys to verify we have all required data
        print(f"Article data for ID {article_id}: Keys = {list(article.keys())}")
        if 'title' not in article or 'content' not in article:
            print(f"ERROR: Article {article_id} is missing required fields (title or content)")
            return False
        
        # If retrying without embedding or explicitly asked to skip embedding, just mark as saved
        if retry_without_embedding:
            print(f"Marking article {article_id} as saved without embedding")
            db_update_success = self.database.save_article_to_rag(article_id)
            return db_update_success
        
        # Prepare text for embedding - combine title and content
        title = article["title"]
        content = article["content"]
        text_to_embed = f"{title} {content}"
        
        # Debug: Print text length
        print(f"Text length for embedding: {len(text_to_embed)} characters")
        
        # First, make sure we save the article to the database regardless of embedding success
        # This ensures we don't lose the article if embedding fails
        try:
            db_update_success = self.database.save_article_to_rag(article_id)
            if db_update_success:
                print(f"Successfully marked article {article_id} as saved in the database")
            else:
                print(f"WARNING: Failed to mark article {article_id} as saved in the database")
        except Exception as db_error:
            print(f"ERROR: Failed to update article status in database: {db_error}")
        
        # For very long articles, we'll try a multi-section approach first
        if len(text_to_embed) > 20000:
            success = self._add_very_long_article(article_id, title, content, article)
            if success:
                return True
            print("Failed with multi-section approach, trying standard approach")
            
        # Now try to get the embedding and add to vector database
        try:
            # Get embedding using our chunking approach
            embedding = self.get_embedding(text_to_embed)
            
            if not embedding:
                print(f"Failed to get embedding for article {article_id}, but article is saved in the database")
                return True  # Return success since article is saved in regular database
            
            # Debug: Print embedding info
            print(f"Successfully created embedding with length: {len(embedding)}")
            
            # Add to ChromaDB
            self.collection.add(
                ids=[article_id],
                embeddings=[embedding],
                metadatas=[{
                    "title": article["title"],
                    "author": article["author"],
                    "url": article["url"],
                    "published_at": article["published_at"],
                    "summary": article["summary"],
                    "is_section": False
                }],
                documents=[text_to_embed]
            )
            
            print(f"Successfully added article {article_id} to vector database")
            return True
            
        except Exception as e:
            import traceback
            print(f"ERROR adding article to vector database: {e}")
            print(f"Error details: {traceback.format_exc()}")
            print(f"Article {article_id} is saved in the regular database but not in the vector database")
            return True  # Return success since article is saved in regular database
            
    def _extract_major_sections(self, title: str, content: str) -> List[Tuple[str, str]]:
        """
        Extract major sections from article content.
        Returns a list of (section_title, section_content) tuples.
        """
        # Start with the title and full content as one section
        sections = [(title, content)]
        
        # Try multiple section extraction strategies
        
        # 1. First try to split by markdown-style headers
        header_matches = list(re.finditer(r'(?m)^(#{1,3})\s+(.+)$', content))
        
        if not header_matches:
            # 2. Try to find other header patterns (capitalized lines that look like headers)
            header_matches = list(re.finditer(r'(?m)^([A-Z][A-Za-z0-9\s:,]{10,60})$', content))
            
        if header_matches:
            sections = []
            
            # Add the first section (before the first header)
            if header_matches[0].start() > 0:
                intro_content = content[:header_matches[0].start()].strip()
                if intro_content:
                    sections.append(("Introduction", intro_content))
            
            # Process each header and its content
            for i, match in enumerate(header_matches):
                section_title = match.group(2) if len(match.groups()) > 1 else match.group(1)
                start_pos = match.end()
                
                # Find the end of this section (start of next section or end of content)
                end_pos = header_matches[i+1].start() if i < len(header_matches)-1 else len(content)
                
                section_content = content[start_pos:end_pos].strip()
                if section_content:
                    sections.append((section_title, section_content))
        
        # 3. If we couldn't find headers, try to split by significant paragraph breaks
        if len(sections) <= 1 and len(content) > 10000:
            # Look for triple line breaks or horizontal rules as section dividers
            divider_matches = list(re.finditer(r'\n\s*\n\s*\n|\n\s*---+\s*\n|\n\s*\*\*\*+\s*\n', content))
            
            if len(divider_matches) >= 2:  # Need at least a couple of dividers to make sections
                sections = []
                start_pos = 0
                
                for i, match in enumerate(divider_matches):
                    # Extract content up to this divider
                    section_content = content[start_pos:match.start()].strip()
                    
                    # Generate a title from the first sentence or first few words
                    first_sentence_match = re.search(r'^([^.!?]+[.!?])', section_content)
                    if first_sentence_match:
                        # Use first sentence if it's reasonably short
                        first_sentence = first_sentence_match.group(1).strip()
                        if len(first_sentence) <= 100:
                            section_title = first_sentence
                        else:
                            section_title = f"Section {i+1}: {first_sentence[:50]}..."
                    else:
                        # Use first 50 chars as the title
                        section_title = f"Section {i+1}: {section_content[:50]}..."
                    
                    if section_content:
                        sections.append((section_title, section_content))
                    
                    # Update start position for next section
                    start_pos = match.end()
                
                # Add the final section after the last divider
                if start_pos < len(content):
                    final_content = content[start_pos:].strip()
                    if final_content:
                        sections.append((f"Section {len(divider_matches)+1}", final_content))
        
        # 4. If still no sections found, use a length-based approach as last resort
        if len(sections) <= 1 and len(content) > 6000:
            # Calculate optimal section size based on content length
            # For longer content, create more sections
            section_count = max(3, min(8, len(content) // 4000))
            target_size = len(content) // section_count
            
            # Try to split on sentence boundaries near the target size
            paragraphs = re.split(r'\n\s*\n', content)
            sections = []
            current_section = []
            current_size = 0
            
            for para in paragraphs:
                current_section.append(para)
                current_size += len(para) + 2  # +2 for paragraph break
                
                # When we reach target size, create a section
                if current_size >= target_size and len(current_section) > 0:
                    section_content = "\n\n".join(current_section)
                    
                    # Generate title from first paragraph or start of section
                    first_words = current_section[0][:100].strip()
                    section_title = f"Section {len(sections)+1}: {first_words[:30]}..."
                    
                    sections.append((section_title, section_content))
                    current_section = []
                    current_size = 0
            
            # Add any remaining content as the final section
            if current_section:
                section_content = "\n\n".join(current_section)
                section_title = f"Section {len(sections)+1}: {current_section[0][:30]}..."
                sections.append((section_title, section_content))
        
        # If we still have only 1 section but the content is very long,
        # forcibly split it into roughly equal parts
        if len(sections) <= 1 and len(content) > 10000:
            sections = []
            section_count = min(5, max(3, len(content) // 5000))
            section_size = len(content) // section_count
            
            for i in range(section_count):
                start = i * section_size
                end = min((i + 1) * section_size, len(content))
                
                # Try to find sentence boundary near the calculated position
                if i > 0:  # No need to adjust start position for first section
                    sentence_boundary = re.search(r'[.!?]\s+', content[max(0, start-100):min(start+100, len(content))])
                    if sentence_boundary:
                        # Adjust start position to sentence boundary
                        offset = sentence_boundary.end() - 1
                        start = max(0, start-100) + offset
                
                if i < section_count - 1:  # No need to adjust end position for last section
                    sentence_boundary = re.search(r'[.!?]\s+', content[max(0, end-100):min(end+100, len(content))])
                    if sentence_boundary:
                        # Adjust end position to sentence boundary
                        offset = sentence_boundary.end() - 1
                        end = max(0, end-100) + offset
                
                section_content = content[start:end].strip()
                if section_content:
                    # Create title from first words of section
                    words = section_content.split()[:10]
                    title_text = " ".join(words)
                    section_title = f"Part {i+1}: {title_text}..."
                    sections.append((section_title, section_content))
        
        return sections

    def _add_very_long_article(self, article_id: str, title: str, content: str, article: Dict) -> bool:
        """
        For very long articles, split into sections and create separate embeddings.
        This is more effective than trying to average many chunks for extremely long content.
        
        Returns:
            bool: True if successful, False if failed
        """
        print(f"Article is very long ({len(content)} chars). Using section-based approach.")
        
        # Get major sections from the content
        sections = self._extract_major_sections(title, content)
        print(f"Split article into {len(sections)} major sections")
        
        if len(sections) <= 1:
            print("Could not split article into sections, falling back to standard approach")
            return False
            
        # Try to embed each section
        successful_sections = 0
        
        # Process sections in parallel to improve performance for very long articles
        max_workers = min(len(sections), 4)  # Limit to 4 parallel workers
        import concurrent.futures
        
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                # Create function for processing a single section
                def process_section(section_data):
                    i, (section_title, section_content) = section_data
                    section_id = f"{article_id}_section_{i}"
                    section_text = f"{title} - {section_title}: {section_content}"
                    
                    print(f"Processing section {i+1}/{len(sections)}: '{section_title}' ({len(section_text)} chars)")
                    
                    try:
                        # Get embedding for this section
                        embedding = self.get_embedding(section_text)
                        
                        if not embedding:
                            print(f"Failed to get embedding for section {i+1}")
                            return False
                            
                        # Add section to ChromaDB
                        self.collection.add(
                            ids=[section_id],
                            embeddings=[embedding],
                            metadatas=[{
                                "title": f"{article['title']} - {section_title}",
                                "author": article["author"],
                                "url": article["url"],
                                "published_at": article["published_at"],
                                "summary": f"Section {i+1} of article: {section_title}",
                                "parent_id": article_id,
                                "is_section": True,
                                "section_index": i  # Store section order for reconstruction
                            }],
                            documents=[section_text]
                        )
                        
                        print(f"Successfully added section {i+1}/{len(sections)}")
                        return True
                        
                    except Exception as e:
                        print(f"Error adding section {i+1}: {e}")
                        return False
                
                # Submit all sections for processing
                section_futures = {
                    executor.submit(process_section, (i, section)): i 
                    for i, section in enumerate(sections)
                }
                
                # Process results as they complete
                for future in concurrent.futures.as_completed(section_futures):
                    if future.result():
                        successful_sections += 1
        
        except Exception as e:
            print(f"Error in parallel section processing: {e}")
            # If parallel processing fails, fall back to sequential processing
            for i, (section_title, section_content) in enumerate(sections):
                section_id = f"{article_id}_section_{i}"
                section_text = f"{title} - {section_title}: {section_content}"
                
                try:
                    # Get embedding for this section
                    embedding = self.get_embedding(section_text)
                    
                    if not embedding:
                        continue
                        
                    # Add section to ChromaDB
                    self.collection.add(
                        ids=[section_id],
                        embeddings=[embedding],
                        metadatas=[{
                            "title": f"{article['title']} - {section_title}",
                            "author": article["author"],
                            "url": article["url"],
                            "published_at": article["published_at"],
                            "summary": f"Section {i+1} of article: {section_title}",
                            "parent_id": article_id,
                            "is_section": True,
                            "section_index": i
                        }],
                        documents=[section_text]
                    )
                    
                    successful_sections += 1
                    
                    # Add a delay between API calls
                    import time
                    time.sleep(1)
                    
                except Exception as e:
                    print(f"Error adding section {i+1}: {e}")
        
        success_rate = successful_sections / len(sections)
        print(f"Added {successful_sections}/{len(sections)} sections ({success_rate:.0%})")
        
        return successful_sections > 0
    
    def query_similar_articles(self, query_text, n_results=5):
        """Query the vector database for articles similar to the query"""
        # Check if there are any articles in the collection first
        all_results = self.collection.get(include=[])
        if not all_results["ids"]:
            print("No articles found in the vector database")
            return []
        
        # Get embedding using our improved chunking approach
        query_embedding = self.get_embedding(query_text)
        
        if not query_embedding:
            print("Failed to get embedding for query")
            # Fallback: return most recent articles from the database
            print("Fallback: Returning most recent articles instead")
            return self._get_recent_articles_formatted(n_results)
        
        try:
            # Query the vector database
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=n_results * 2,  # Get more results initially to account for sections
                include=["metadatas", "distances"]
            )
            
            if not results["ids"] or not results["ids"][0]:
                print("No similar articles found in the vector database")
                return self._get_recent_articles_formatted(n_results)
            
            # Process the results
            return self._process_query_results(results, n_results)
            
        except Exception as e:
            print(f"Error querying ChromaDB: {e}")
            # Print more detailed error information
            import traceback
            print(f"Error details: {traceback.format_exc()}")
            
            # Fallback: return most recent articles from the database
            print("Fallback: Returning most recent articles instead")
            return self._get_recent_articles_formatted(n_results)
            
    def _process_query_results(self, results, n_results=5):
        """
        Process query results, handling both regular articles and section-based results.
        Consolidates sections from the same article and formats the final results.
        """
        all_ids = results["ids"][0]
        all_metadatas = results["metadatas"][0]
        all_distances = results["distances"][0] if "distances" in results else [None] * len(all_ids)
        
        # Group results by parent_id (for sections) or by direct id (for regular articles)
        grouped_results = {}
        
        for i, doc_id in enumerate(all_ids):
            metadata = all_metadatas[i]
            distance = all_distances[i]
            
            # Check if this is a section
            is_section = metadata.get("is_section", False)
            
            if is_section:
                # Get the parent article id
                parent_id = metadata.get("parent_id")
                if not parent_id:
                    continue
                
                # Add or update the parent article entry
                if parent_id not in grouped_results:
                    # Try to get the parent article from the database
                    parent_article = self.database.get_article(parent_id)
                    if not parent_article:
                        continue
                        
                    grouped_results[parent_id] = {
                        "id": parent_id,
                        "title": parent_article["title"],
                        "author": parent_article["author"],
                        "url": parent_article["url"],
                        "published_at": parent_article["published_at"],
                        "summary": parent_article["summary"],
                        "matching_sections": [],
                        "best_distance": distance
                    }
                elif distance < grouped_results[parent_id]["best_distance"]:
                    grouped_results[parent_id]["best_distance"] = distance
                
                # Add this section to the matching sections
                section_title = metadata["title"].split(" - ", 1)[1] if " - " in metadata["title"] else metadata["title"]
                grouped_results[parent_id]["matching_sections"].append({
                    "title": section_title,
                    "summary": metadata["summary"],
                    "distance": distance
                })
            else:
                # Regular article (not a section)
                article_id = doc_id
                
                if article_id not in grouped_results:
                    grouped_results[article_id] = {
                        "id": article_id,
                    "title": metadata["title"],
                    "author": metadata["author"],
                    "url": metadata["url"],
                    "published_at": metadata["published_at"],
                    "summary": metadata["summary"],
                        "best_distance": distance,
                        "matching_sections": []
                    }
        
        # Convert to a list and sort by similarity
        results_list = list(grouped_results.values())
        results_list.sort(key=lambda x: x["best_distance"])
        
        # Format the final results (limit to n_results)
        formatted_results = []
        for result in results_list[:n_results]:
            formatted_result = {
                "id": result["id"],
                "title": result["title"],
                "author": result["author"],
                "url": result["url"],
                "published_at": result["published_at"],
                "summary": result["summary"],
                "similarity_score": result["best_distance"]
            }
            
            # Add matching sections if any
            if result["matching_sections"]:
                matching_sections = sorted(result["matching_sections"], key=lambda x: x["distance"])
                formatted_result["matching_sections"] = matching_sections[:3]  # Limit to top 3 sections
            
            formatted_results.append(formatted_result)
        
        return formatted_results
    
    def _get_recent_articles_formatted(self, limit=5):
        """Get recent articles directly from the database"""
        recent_articles = self.database.get_recent_articles(limit=limit)
        formatted_results = []
        
        for article in recent_articles:
            formatted_results.append({
                "id": article["id"],
                "title": article["title"],
                "author": article["author"],
                "url": article["url"],
                "published_at": article["published_at"],
                "summary": article["summary"],
                "similarity_score": None,  # No similarity score for fallback results
                "is_fallback": True  # Indicate this is a fallback result
            })
            
            return formatted_results
    
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
        """清理向量資料庫中的孤立嵌入（其對應文章已從資料庫中刪除）及過期的快取"""
        try:
            # 1. 清理孤立的嵌入向量
            # 獲取向量資料庫中所有文章的 ID
            all_results = self.collection.get(include=[])
            vector_article_ids = all_results["ids"]
            
            if not vector_article_ids:
                print("向量資料庫中沒有任何嵌入向量")
                return {"deleted_vectors": 0, "cleaned_cache": 0}
            
            # 獲取普通資料庫中存在的文章 ID
            existing_ids = []
            conn = self.database.get_connection()
            cursor = conn.cursor()
            
            placeholders = ','.join(['?' for _ in vector_article_ids])
            cursor.execute(f"SELECT id FROM articles WHERE id IN ({placeholders})", vector_article_ids)
            
            existing_ids = [row[0] for row in cursor.fetchall()]
            
            # 找出需要刪除的 ID（存在於向量資料庫但不存在於普通資料庫的 ID）
            ids_to_delete = [id for id in vector_article_ids if id not in existing_ids]
            
            deleted_vectors = 0
            if ids_to_delete:
                # 從向量資料庫中刪除
                self.collection.delete(ids=ids_to_delete)
                deleted_vectors = len(ids_to_delete)
                print(f"清理了 {deleted_vectors} 個孤立的嵌入向量")
            else:
                print("沒有需要清理的孤立嵌入向量")
            
            # 2. 清理過期的嵌入快取（超過30天的快取）
            cleaned_cache = self.clean_embedding_cache(max_age_days=30)
            
            # 3. 返回清理結果
            return {
                "deleted_vectors": deleted_vectors,
                "cleaned_cache": cleaned_cache
            }
            
        except Exception as e:
            print(f"清理向量資料庫時出錯: {e}")
            return {"error": str(e)}
    
    def get_vector_database_stats(self):
        """獲取向量資料庫的統計資訊"""
        try:
            # 獲取向量資料庫中的文章數量
            all_results = self.collection.get(include=[])
            vector_count = len(all_results["ids"])
            
            # 計算不同類型的向量數量（文章與章節）
            section_count = 0
            article_count = 0
            
            if vector_count > 0:
                # 獲取元數據以區分文章與章節
                metadatas = self.collection.get(
                    ids=all_results["ids"],
                    include=["metadatas"]
                )["metadatas"]
                
                for metadata in metadatas:
                    if metadata.get("is_section", False):
                        section_count += 1
                    else:
                        article_count += 1
            
            # 獲取向量資料庫的大小
            db_size_mb = 0
            if os.path.exists(self.db_path):
                # 遍歷資料夾計算總大小
                for dirpath, dirnames, filenames in os.walk(self.db_path):
                    for f in filenames:
                        fp = os.path.join(dirpath, f)
                        db_size_mb += os.path.getsize(fp)
                db_size_mb = db_size_mb / (1024 * 1024)  # 轉換為 MB
            
            # 獲取快取統計資訊
            cache_count = 0
            cache_size_mb = 0
            newest_cache = None
            oldest_cache = None
            
            if os.path.exists(self.cache_dir):
                cache_files = [f for f in os.listdir(self.cache_dir) if f.endswith('.pkl')]
                cache_count = len(cache_files)
                
                if cache_count > 0:
                    cache_timestamps = []
                    
                    for f in cache_files:
                        fp = os.path.join(self.cache_dir, f)
                        file_size = os.path.getsize(fp)
                        cache_size_mb += file_size
                        
                        # 記錄檔案的修改時間
                        mtime = os.path.getmtime(fp)
                        cache_timestamps.append(mtime)
                    
                    # 轉換為 MB
                    cache_size_mb = cache_size_mb / (1024 * 1024)
                    
                    # 找出最新與最舊的快取
                    if cache_timestamps:
                        newest_cache = datetime.fromtimestamp(max(cache_timestamps)).strftime('%Y-%m-%d %H:%M:%S')
                        oldest_cache = datetime.fromtimestamp(min(cache_timestamps)).strftime('%Y-%m-%d %H:%M:%S')
            
            return {
                "vector_count": vector_count,
                "article_count": article_count,
                "section_count": section_count,
                "database_size_mb": round(db_size_mb, 2),
                "cache_stats": {
                    "count": cache_count,
                    "size_mb": round(cache_size_mb, 2),
                    "newest_cache": newest_cache,
                    "oldest_cache": oldest_cache
                }
            }
        except Exception as e:
            print(f"獲取向量資料庫統計資訊時出錯: {e}")
            import traceback
            print(traceback.format_exc())
            return {"error": str(e)} 