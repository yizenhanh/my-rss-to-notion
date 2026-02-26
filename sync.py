import feedparser
import requests
import os
import re
from html.parser import HTMLParser

# 1. 配置信息
NOTION_TOKEN = os.getenv('NOTION_TOKEN')
DATABASE_ID = os.getenv('NOTION_DATABASE_ID')
RSS_URL = os.getenv('RSS_URL')

class NotionContentParser(HTMLParser):
    """自定义 HTML 解析器，将网页结构转换为 Notion 的 Blocks 格式"""
    def __init__(self):
        super().__init__()
        self.blocks = []
        self.current_text = ""

    def flush_text(self):
        if self.current_text.strip():
            # 将长文本拆分为每段不超过 2000 字符的块
            text = self.current_text.strip()
            for i in range(0, len(text), 2000):
                self.blocks.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"text": {"content": text[i:i+2000]}}]
                    }
                })
        self.current_text = ""

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag in ['p', 'div', 'br', 'h1', 'h2', 'h3']:
            self.flush_text()
        elif tag == 'img' and 'src' in attrs_dict:
            self.flush_text()
            self.blocks.append({
                "object": "block",
                "type": "image",
                "image": {
                    "type": "external",
                    "external": {"url": attrs_dict['src']}
                }
            })

    def handle_data(self, data):
        self.current_text += data

    def handle_endtag(self, tag):
        if tag in ['p', 'div', 'h1', 'h2', 'h3']:
            self.flush_text()

def add_to_notion(title, url, html_content):
    notion_url = "https://api.notion.com/v1/pages"
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }
    
    # 解析 HTML 内容生成 Blocks
    parser = NotionContentParser()
    parser.feed(html_content)
    parser.flush_text()
    
    # 提取第一张图做封面
    img_urls = re.findall(r'<img [^>]*src="([^"]+)"', html_content)
    
    data = {
        "parent": {"database_id": DATABASE_ID},
        "properties": {
            "标题": {"title": [{"text": {"content": title}}]},
            "链接": {"url": url}
        },
        "children": parser.blocks[:100] # Notion 一次性创建页面最多支持 100 个 Block
    }

    if img_urls:
        data["cover"] = {"type": "external", "external": {"url": img_urls[0]}}

    response = requests.post(notion_url, headers=headers, json=data)
    return response

# 2. 执行同步
print(f"开始深度同步: {RSS_URL}")
feed = feedparser.parse(RSS_URL)

for entry in feed.entries[:3]:
    content_body = entry.get('content', [{}])[0].get('value', entry.get('summary', ""))
    print(f"解析并排版: {entry.title}")
    res = add_to_notion(entry.title, entry.link, content_body)
    
    if res.status_code == 200:
        print(f"✅ 成功！完整排版已同步")
    else:
        print(f"❌ 失败: {res.status_code}, {res.text}")
