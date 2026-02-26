import feedparser
import requests
import os

# 从 GitHub Secrets 获取配置
NOTION_TOKEN = os.getenv('NOTION_TOKEN')
DATABASE_ID = os.getenv('NOTION_DATABASE_ID')
RSS_URL = os.getenv('RSS_URL')

def add_to_notion(title, url):
    notion_url = "https://api.notion.com/v1/pages"
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }
    # 注意这里：我们将 "名称" 改为了 "标题"
    data = {
        "parent": {"database_id": DATABASE_ID},
        "properties": {
            "标题": {"title": [{"text": {"content": title}}]},
            "链接": {"url": url}
        }
    }
    response = requests.post(notion_url, headers=headers, json=data)
    return response.status_code

# 解析 RSS 并上传
feed = feedparser.parse(RSS_URL)
# 遍历最近的 3 篇文章
for entry in feed.entries[:3]:
    status = add_to_notion(entry.title, entry.link)
    print(f"Title: {entry.title}, Status: {status}")
