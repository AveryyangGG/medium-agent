"""
HTML templates for the Medium Agent web application.
This module contains all the HTML templates used in the web application.
"""

def get_home_page():
    """Return the home page HTML template."""
    return """
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
            <p><a href="/search">/search</a> - Search saved articles</p>
            <p><a href="/generate-summary">/generate-summary</a> - Generate summary from Medium URL</p>
        </div>
    </body>
    </html>
    """

def get_search_page():
    """Return the search page HTML template."""
    return """
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
                                <a href="/articles/${article.id}/outline" target="_blank">View Detailed Summary</a>
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

def get_detailed_summary_page(article_id, title, author, detailed_summary):
    """Return the detailed summary page HTML template."""
    # Format the detailed summary with proper line breaks
    formatted_summary = detailed_summary.replace('\n', '<br>')
    
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>{title} - Detailed Summary</title>
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
            .summary-content {{
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
        
        <div class="summary-content">
            {formatted_summary}
        </div>
        
        <p><a href="/articles/{article_id}">Back to Article</a></p>
    </body>
    </html>
    """

def get_summary_form():
    """Return the summary generation form HTML template."""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Generate Medium Article Summary</title>
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
            input[type="url"] {
                width: 70%;
                padding: 10px;
                font-size: 16px;
                border: 1px solid #ddd;
                border-radius: 4px;
                margin-bottom: 10px;
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
            #status {
                margin-top: 20px;
                padding: 15px;
                border-radius: 5px;
                display: none;
            }
            .loading {
                background-color: #f9f9f9;
                border-left: 4px solid #0066cc;
            }
            .error {
                background-color: #ffe6e6;
                border-left: 4px solid #cc0000;
            }
            .article {
                background-color: #f9f9f9;
                padding: 20px;
                margin-top: 20px;
                border-radius: 5px;
                border-left: 4px solid #0066cc;
            }
            .article h2 {
                margin-top: 0;
                color: #333;
            }
            .article .meta {
                color: #666;
                font-size: 14px;
                margin-bottom: 15px;
            }
            .article .summary, .article .detailed-summary {
                margin-top: 15px;
            }
            .article h3 {
                color: #444;
                border-bottom: 1px solid #eee;
                padding-bottom: 5px;
            }
            .action-buttons {
                margin-top: 20px;
                display: flex;
                gap: 10px;
            }
            .action-buttons button, .action-buttons a {
                padding: 8px 15px;
                border-radius: 4px;
                border: none;
                cursor: pointer;
                font-size: 14px;
                text-decoration: none;
                display: inline-block;
                text-align: center;
            }
            .primary-btn {
                background-color: #0066cc;
                color: white;
            }
            .secondary-btn {
                background-color: #f0f0f0;
                color: #333;
                border: 1px solid #ddd;
            }
            .success-message {
                background-color: #e6ffe6;
                color: #006600;
                padding: 10px;
                border-radius: 4px;
                margin-top: 10px;
                display: none;
            }
        </style>
        <script>
            async function generateSummary() {
                const url = document.getElementById('url-input').value;
                if (!url) {
                    alert('Please enter a Medium article URL');
                    return;
                }
                
                // Validate URL format
                if (!url.startsWith('https://medium.com/') && 
                    !url.startsWith('https://towardsdatascience.com/') && 
                    !url.startsWith('https://betterhumans.pub/') &&
                    !url.startsWith('https://www.freecodecamp.org/')) {
                    alert('Please enter a valid Medium article URL');
                    return;
                }
                
                const statusDiv = document.getElementById('status');
                const resultDiv = document.getElementById('result');
                
                // Show loading status
                statusDiv.className = 'loading';
                statusDiv.style.display = 'block';
                statusDiv.innerHTML = '<p>Generating summary, please wait. This may take 1-2 minutes...</p>';
                
                document.getElementById('generate-button').disabled = true;
                
                try {
                    const response = await fetch('/api/generate-summary', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify({ url: url }),
                    });
                    
                    if (!response.ok) {
                        const errorData = await response.json();
                        throw new Error(errorData.detail || 'Failed to generate summary');
                    }
                    
                    const data = await response.json();
                    
                    // Hide status div and show result
                    statusDiv.style.display = 'none';
                    
                    // Display the generated summary
                    resultDiv.innerHTML = `
                        <div class="article">
                            <h2>${data.title}</h2>
                            <div class="meta">
                                By ${data.author} · 👏 ${data.claps.toLocaleString()} · 💬 ${data.responses}
                            </div>
                            
                            <h3>Summary</h3>
                            <div class="summary">${data.summary.replace(/\n/g, '<br>')}</div>
                            
                            <h3>Detailed Summary</h3>
                            <div class="detailed-summary">${data.detailed_summary.replace(/\n/g, '<br>')}</div>
                            
                            <div class="action-buttons">
                                <a href="${data.url}" target="_blank" class="primary-btn">Read Original Article</a>
                                <button onclick="saveToRag('${data.id}')" class="secondary-btn">Save to RAG Database</button>
                            </div>
                            <div id="save-result" class="success-message"></div>
                        </div>
                    `;
                } catch (error) {
                    statusDiv.className = 'error';
                    statusDiv.innerHTML = `<p>Error: ${error.message}</p>`;
                } finally {
                    document.getElementById('generate-button').disabled = false;
                }
            }
            
            async function saveToRag(articleId) {
                const saveResult = document.getElementById('save-result');
                try {
                    const response = await fetch(`/articles/${articleId}/save`, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        }
                    });
                    
                    if (!response.ok) {
                        const errorData = await response.json();
                        throw new Error(errorData.detail || 'Failed to save article');
                    }
                    
                    saveResult.textContent = 'Article successfully saved to RAG database!';
                    saveResult.style.display = 'block';
                    
                    // Disable the save button
                    const saveButton = document.querySelector('.action-buttons button');
                    if (saveButton) {
                        saveButton.disabled = true;
                        saveButton.textContent = 'Saved to RAG';
                    }
                    
                    // Hide the message after 5 seconds
                    setTimeout(() => {
                        saveResult.style.display = 'none';
                    }, 5000);
                    
                } catch (error) {
                    saveResult.textContent = `Error: ${error.message}`;
                    saveResult.style.backgroundColor = '#ffe6e6';
                    saveResult.style.color = '#cc0000';
                    saveResult.style.display = 'block';
                }
            }
        </script>
    </head>
    <body>
        <h1>Generate Medium Article Summary</h1>
        <p>Enter a Medium article URL to generate a detailed summary:</p>
        
        <form onsubmit="event.preventDefault(); generateSummary();">
            <input type="url" id="url-input" placeholder="https://medium.com/...">
            <button type="submit" id="generate-button">Generate Summary</button>
        </form>
        
        <div id="status"></div>
        <div id="result"></div>
        
        <p><a href="/">Back to Home</a></p>
    </body>
    </html>
    """ 