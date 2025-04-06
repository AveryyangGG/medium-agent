# Medium 助手

一個 Python 應用程式，用於獲取 Medium 上的熱門文章、對其進行摘要，並通過 Telegram 或網頁界面進行傳送。它還支援將文章保存到 RAG（檢索增強生成）資料庫中以便日後查詢。

## 功能特點

- 每日從 Medium 多個主題中獲取熱門文章
- 基於 Cookie 的身份驗證，以訪問 Medium 內容（包括會員專屬文章）
- 使用 Anthropic Claude 3.7 自動生成文章摘要和詳細條列式整理（支援 thinking 模式）
- 通過 Telegram 機器人傳送文章摘要和條列式整理
- 顯示文章的掌聲數（claps）和回應數（responses）
- 提供網頁界面用於查看和搜尋文章
- 使用 Voyage AI 進行語義搜尋的 RAG 資料庫
- 使用簡單的 SQLite 資料庫存儲文章
- 資料庫管理功能（清理舊文章、查看統計資訊等）

## 系統需求

- Python 3.8+
- 所需的 Python 套件（見 `requirements.txt`）
- Medium 帳戶的 Cookie 以訪問內容
- Telegram 機器人令牌（使用 [BotFather](https://core.telegram.org/bots#botfather) 創建）
- Anthropic API 金鑰（用於摘要生成）
- Voyage AI API 金鑰（用於向量嵌入）

## 安裝步驟

1. 複製代碼庫：
   ```
   git clone https://github.com/yourusername/medium-agent.git
   cd medium-agent
   ```

2. 創建並啟動虛擬環境：
   ```
   python -m venv venv
   source venv/bin/activate  # 在 Windows 上: venv\Scripts\activate
   ```

3. 安裝所需套件：
   ```
   pip install -r requirements.txt
   ```

4. 複製環境變數範例檔案並編輯您的憑證：
   ```
   cp .env.example .env
   ```
   
   然後編輯 `.env` 文件，填入您的 API 金鑰和設定。

## 設置 Medium Cookies

要訪問 Medium 內容（特別是會員專屬文章），您需要提供已登入的 Medium 帳戶的 Cookies：

1. 在網頁瀏覽器中登入您的 Medium 帳戶
2. 打開瀏覽器的開發者工具（F12 或右鍵點擊並選擇"檢查"）
3. 切換到"網絡"（Network）標籤
4. 加載或重新加載一個 Medium 頁面
5. 點擊頁面請求（通常是第一個）
6. 在 Headers 區域中，找到"Cookie"標頭
7. 複製整個 Cookie 字串並將其粘貼到您的 `.env` 文件中的 `MEDIUM_COOKIES` 變數

Cookie 字串應該看起來類似於：
```
sid=1:xxxxxxxx.xxxxxxxx; uid=xxxxxxxx; optimizelyEndUserId=xxxxxxxx; __cfruid=xxxxxxxx
```

**注意**：Cookies 會在一段時間後過期，因此您可能需要定期更新。

## 使用方法

### 運行應用程式

要啟動 Medium 助手：

```
python main.py
```

這將：
- 啟動 Telegram 機器人
- 啟動網頁應用程式（預設可通過 http://localhost:8000 訪問）
- 安排每日文章獲取
- 立即執行首次文章獲取

### 使用 Telegram 機器人

一旦機器人運行，您可以使用以下指令與之互動：
- `/start` - 啟動機器人
- `/help` - 顯示幫助訊息
- `/today` - 獲取今日熱門文章
- `/recent [數量]` - 顯示最近的文章（可選數量參數）
- `/search <查詢>` - 搜尋已儲存的文章
- `/fetch [數量]` - 立即獲取最新的熱門文章
- `/popular [數量]` - 獲取 Medium 平台上的熱門文章
- `/tag <標籤>` - 根據標籤查詢文章

**管理員命令**：
- `/db_stats` - 獲取資料庫統計資訊
- `/db_clean [天數]` - 清理超過指定天數的舊文章
- `/db_delete <文章ID>` - 刪除特定文章
- `/db_find_tag <標籤>` - 根據標籤查詢已儲存的文章

### 使用網頁界面

通過 `http://localhost:8000`（或您配置的主機/端口）訪問網頁界面。它提供：
- 最近文章列表
- 文章詳情和詳細條列式整理
- RAG 資料庫的搜尋功能

### 將文章保存到 RAG

在 Telegram 或網頁界面查看文章時，您可以將文章保存到 RAG 資料庫中以便日後進行語義搜尋。
保存時，您可以：
- 添加自訂標籤
- 添加個人備註
- 查看詳細的條列式整理

## 配置選項

所有配置選項都在 `.env` 文件中：

- `MEDIUM_COOKIES` - 您的 Medium 帳戶認證 Cookies
- `TELEGRAM_BOT_TOKEN` - 您的 Telegram 機器人令牌
- `TELEGRAM_CHAT_ID` - 您的 Telegram 聊天 ID，用於接收每日更新
- `ADMIN_USER_IDS` - 管理員 Telegram 用戶 ID，用逗號分隔
- `ANTHROPIC_API_KEY` - 您的 Anthropic API 金鑰
- `ANTHROPIC_MODEL` - 用於摘要生成的 Anthropic 模型
- `VOYAGE_API_KEY` - 您的 Voyage AI API 金鑰
- `VOYAGE_MODEL` - 用於嵌入的 Voyage 模型
- `TOP_ARTICLES_COUNT` - 每日獲取的文章數量
- `PUBLIC_URL_BASE` - 可公開訪問的 URL 基礎路徑（用於 Telegram 連結按鈕）
- 網頁應用和資料庫設定

## 架構

該應用程式由以下幾個組件組成：

1. **Medium 服務** - 使用 Cookie 認證獲取 Medium 文章（包括掌聲數和回應數）
2. **摘要服務** - 使用 Anthropic Claude 3.7 對文章進行摘要和生成詳細條列式整理
3. **資料庫** - 儲存文章數據和用戶標記
4. **向量資料庫** - 使用 Voyage AI 管理 RAG 功能
5. **Telegram 機器人** - 通過 Telegram 傳送文章
6. **網頁應用** - 提供網頁界面和詳細條列內容查看

## 授權

MIT

## 貢獻

歡迎貢獻！請隨時提交 Pull Request。 