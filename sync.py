import feedparser
import requests
import os
import re
from html.parser import HTMLParser
from urllib.parse import urlparse

# 配置
NOTION_TOKEN = os.getenv('NOTION_TOKEN')
DATABASE_ID = os.getenv('NOTION_DATABASE_ID')
RSS_URL = os.getenv('RSS_URL')
REPO = os.getenv('GITHUB_REPOSITORY') # 格式: 用户名/仓库名

def download_image(url):
    """下载图片并返回它在 GitHub 上的新链接"""
    if not url: return None
    try:
        # 1. 转换高清链接
        hd_url = re.sub(r'/(s\d+[-h]*|w\d+)/', '/s1600/', url)
        
        # 2. 生成文件名 (取 URL 最后一段并去除特殊字符)
        path = urlparse(hd_url).path
        ext = os.path.splitext(path)[1] or ".jpg"
        filename = re.sub(r'[^a-zA-Z0-9]', '_', path.split('/')[-1]) + ext
        local_path = f"images/{filename}"
        
        # 3. 下载并保存
        r = requests.get(hd_url, timeout=10)
        if r.status_code == 200:
            with open(local_path, 'wb') as f:
                f.write(r.content)
            # 4. 返回 GitHub Raw 链接
            return f"https://raw.githubusercontent.com/{REPO}/main/images/{filename}"
    except Exception as e:
        print(f"下载失败: {e}")
    return url # 失败则返回原链接

class NotionContentParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.blocks = []
        self.current_text = ""

    def flush_text(self):
        if self.current_text.strip():
            text = self.current_text.strip()
            for i in range(0, len(text), 2000):
                self.blocks.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": text[i:i+2000]}}]}})
        self.current_text = ""

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag in ['p', 'div', 'br', 'h1', 'h2', 'h3']:
            self.flush_text()
        elif tag == 'img' and 'src' in attrs_dict:
            self.flush_text()
            new_url = download_image(attrs_dict['src'])
            self.blocks.append({"object": "block", "type": "image", "image": {"type": "external", "external": {"url": new_url}}})

    def handle_data(self, data): self.current_text += data
    def handle_endtag(self, tag):
        if tag in ['p', 'div', 'h1', 'h2', 'h3']: self.flush_text()

def add_to_notion(title, url, html_content):
    parser = NotionContentParser()
    parser.feed(html_content)
    parser.flush_text()
    
    # 封面也用 GitHub 备份图
    img_urls = re.findall(r'<img [^>]*src="([^"]+)"', html_content)
    cover_url = download_image(img_urls[0]) if img_urls else None

    data = {
        "parent": {"database_id": DATABASE_ID},
        "properties": {"标题": {"title": [{"text": {"content": title}}]}, "链接": {"url": url}},
        "children": parser.blocks[:100]
    }
    if cover_url: data["cover"] = {"type": "external", "external": {"url": cover_url}}
    
    requests.post("https://api.notion.com/v1/pages", headers={"Authorization": f"Bearer {NOTION_TOKEN}", "Content-Type": "application/json", "Notion-Version": "2022-06-28"}, json=data)

# 运行
feed = feedparser.parse(RSS_URL)
for entry in feed.entries[:3]:
    content = entry.get('content', [{}])[0].get('value', entry.get('summary', ""))
    add_to_notion(entry.title, entry.link, content)
