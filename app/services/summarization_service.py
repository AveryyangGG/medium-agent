import os
import sys
import anthropic
import asyncio

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL

class SummarizationService:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    
    def summarize_article(self, article):
        """
        使用 Anthropic Claude 3.7 對文章內容進行摘要
        返回摘要和重點清單
        """
        if not article or not article.get('content'):
            return None, None
        
        content = article['content']
        title = article['title']
        
        # 如果內容太長則進行截斷
        max_content_length = 100000  # Claude 的限制比 OpenAI 高很多
        if len(content) > max_content_length:
            content = content[:max_content_length]
        
        try:
            # 創建中文 prompt
            prompt = f"""
            文章標題：{title}
            
            文章內容：{content}
            
            請提供：
            1. 一段簡潔的文章摘要（2-3句話）
            2. 3-5個要點，突出文章的主要觀點
            
            請使用以下格式回答：
            摘要：[摘要內容]
            
            重點：
            - [第一點]
            - [第二點]
            - [依此類推...]
            """
            
            # 設置系統提示
            system_prompt = "你是一位專業的文章分析師，擅長整理和總結文章內容。請提供清晰、簡潔、結構化的摘要和重點。"
            
            # 調用 Anthropic Claude API，正確啟用 thinking 模式
            # 注意：max_tokens 必須大於 thinking.budget_tokens
            thinking_budget = 10000  # 從 6000 提高至 10000
            response = self.client.messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=20000,  # 從 6400 提高至 20000
                temperature=1,  # 從動態值設置為固定值 1
                system=system_prompt,
                thinking={"type": "enabled", "budget_tokens": thinking_budget},
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            
            # 提取摘要文本 - 安全處理回應
            summary_text = ""
            for content_block in response.content:
                # 只處理文本類型的內容塊
                if hasattr(content_block, 'text') and content_block.text:
                    summary_text += content_block.text
            
            # 解析摘要
            summary_part = ""
            bullet_points = []
            
            if "摘要：" in summary_text and "重點：" in summary_text:
                # 按區域分割文本
                parts = summary_text.split("重點：")
                summary_part = parts[0].replace("摘要：", "").strip()
                
                # 提取重點
                bullets_text = parts[1].strip()
                bullet_points = [
                    point.strip()[2:].strip()  # 移除 "- " 前綴
                    for point in bullets_text.split("\n")
                    if point.strip().startswith("-")
                ]
            else:
                summary_part = summary_text
            
            return summary_part, bullet_points
            
        except Exception as e:
            print(f"摘要生成錯誤: {e}")
            return None, None
    
    def create_detailed_outline(self, article):
        """
        為文章生成詳細的條列式整理，包含主要內容、觀點和洞見
        
        返回：格式化的詳細條列整理
        """
        if not article or not article.get('content'):
            return None
        
        content = article['content']
        title = article['title']
        
        # 如果內容太長則進行截斷
        max_content_length = 100000
        if len(content) > max_content_length:
            content = content[:max_content_length]
        
        try:
            # 創建用於詳細條列式整理的 prompt
            prompt = f"""
            文章標題：{title}
            
            文章內容：{content}
            
            請對這篇文章進行詳細的條列式整理，包含：
            1. 文章主旨和背景（1-2 段）
            2. 主要論點和觀點（詳細條列）
            3. 關鍵事實和數據（如果有）
            4. 實用建議或應用（如果適用）
            5. 文章結論和啟示
            
            請使用層次結構的條列格式，使整理易於閱讀和理解。確保保留文章的關鍵信息和觀點。
            
            格式範例：
            # 文章主旨
            [簡要說明文章的主要主題和寫作目的]
            
            # 主要論點
            1. [第一個主要論點]
               - [支持細節或子觀點]
               - [更多支持細節]
            2. [第二個主要論點]
               - [相關細節]
            
            # 關鍵數據與事實
            - [重要數據 1]
            - [重要數據 2]
            
            # 實用建議
            1. [建議 1]
            2. [建議 2]
            
            # 結論與啟示
            [文章的結論和可能的啟示]
            """
            
            # 設置系統提示
            system_prompt = "你是一位專業的文章分析師，專長於製作詳細的條列式文章整理。請提供全面、結構化且易於閱讀的整理結果。"
            
            # 調用 API 生成詳細整理
            thinking_budget = 10000  # 從 6000 提高至 10000
            response = self.client.messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=20000,  # 從 6400 提高至 20000
                temperature=1,  # 從 0.7 改為 1
                system=system_prompt,
                thinking={"type": "enabled", "budget_tokens": thinking_budget},
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            
            # 提取回應文本
            detailed_outline = ""
            for content_block in response.content:
                if hasattr(content_block, 'text') and content_block.text:
                    detailed_outline += content_block.text
            
            return detailed_outline
            
        except Exception as e:
            print(f"生成詳細整理時出錯: {e}")
            return None
    
    async def summarize_article_stream(self, article, debug=False, stream_callback=None):
        """
        使用流式輸出模式獲取文章摘要，可同時獲取思考過程
        
        參數:
        - article: 文章資訊字典
        - debug: 是否顯示思考過程指示器
        - stream_callback: 處理流式文本的回調函數
        
        返回:
        - 完整的回應文本
        """
        if not article or not article.get('content'):
            return None, None
        
        content = article['content']
        title = article['title']
        
        # 如果內容太長則進行截斷
        max_content_length = 100000
        if len(content) > max_content_length:
            content = content[:max_content_length]
        
        try:
            # 創建中文 prompt
            prompt = f"""
            文章標題：{title}
            
            文章內容：{content}
            
            請提供：
            1. 一段簡潔的文章摘要（2-3句話）
            2. 3-5個要點，突出文章的主要觀點
            
            請使用以下格式回答：
            摘要：[摘要內容]
            
            重點：
            - [第一點]
            - [第二點]
            - [依此類推...]
            """
            
            # 設置系統提示
            system_prompt = "你是一位專業的文章分析師，擅長整理和總結文章內容。請提供清晰、簡潔、結構化的摘要和重點。"
            
            # 調用 Claude API (串流模式)
            # 注意：max_tokens 必須大於 thinking.budget_tokens
            thinking_budget = 10000  # 從 6000 提高至 10000
            response_text = ""
            
            stream = self.client.messages.create(
                model=ANTHROPIC_MODEL,
                thinking={"type": "enabled", "budget_tokens": thinking_budget},
                max_tokens=20000,  # 從 6400 提高至 20000
                temperature=1,  # 從 0.2 改為 1
                system=system_prompt,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                stream=True
            )
            
            print("\n開始分析文章內容...\n")
            for event in stream:
                if event.type == 'content_block_delta' and hasattr(event.delta, 'text'):
                    text_chunk = event.delta.text
                    print(text_chunk, end="", flush=True)  # 即時打印
                    response_text += text_chunk  # 儲存完整內容
                    
                    # 如果提供了回調函數，發送新文本片段
                    if stream_callback:
                        await stream_callback(text_chunk)
                elif event.type == 'message_delta':
                    # 處理消息級別的更新
                    continue
                elif event.type == 'thinking_delta':
                    # 處理思考過程的更新
                    if debug:
                        print("⚙️ ", end="", flush=True)  # 可選：顯示思考中的指示器
                elif event.type == 'content_block_start':
                    # 檢查內容類型，確保是文本
                    if hasattr(event.content_block, 'type') and event.content_block.type == 'text':
                        continue
                    elif debug:
                        print(f"[開始非文本內容塊: {event.content_block.type}]", flush=True)
                elif event.type == 'content_block_stop':
                    # 處理內容塊結束
                    continue
                elif event.type == 'message_start':
                    # 處理消息開始
                    print("\n[開始生成分析]\n", flush=True)
                    if stream_callback:
                        await stream_callback("\n[開始生成分析]\n")
                elif event.type == 'message_stop':
                    # 處理消息結束
                    print("\n\n[分析生成完成]", flush=True)
                    if stream_callback:
                        await stream_callback("\n\n[分析生成完成]")
            
            print("\n\n文章分析已完成")
            
            # 解析摘要
            summary_part = ""
            bullet_points = []
            
            if "摘要：" in response_text and "重點：" in response_text:
                parts = response_text.split("重點：")
                summary_part = parts[0].replace("摘要：", "").strip()
                
                bullets_text = parts[1].strip()
                bullet_points = [
                    point.strip()[2:].strip()
                    for point in bullets_text.split("\n")
                    if point.strip().startswith("-")
                ]
                
                return summary_part, bullet_points
            else:
                return response_text, []
            
        except Exception as e:
            print(f"摘要生成錯誤: {e}")
            return None, None
    
    def format_summary_with_bullets(self, summary, bullet_points):
        """將摘要和重點格式化為顯示文本"""
        if not summary:
            return "沒有可用的摘要。"
        
        formatted_text = f"{summary}\n\n"
        
        if bullet_points and len(bullet_points) > 0:
            formatted_text += "重點：\n"
            for point in bullet_points:
                formatted_text += f"• {point}\n"
        
        return formatted_text 