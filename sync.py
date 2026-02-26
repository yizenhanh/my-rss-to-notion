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
REPO = os.getenv('GITHUB_REPOSITORY')

def get_real_high_res(url):
    """强力转换：将各种 Google 缩略图格式强制转为原始大图"""
    if not url: return None
    # 移除类似 -h (thumbnail) 的标记，并将 /sXXX/ 或 /wXXX/ 替换为 /s0/ (s0代表原图尺寸)
    high_res = re.sub(r'/(s\d+[-h]*|w\d+)/', '/s0/', url)
    return high_res

def download_image(url):
    """下载图片并强制返回 GitHub 链接，增加详细日志"""
    if not url: return url
    try:
        # 转换高清链接
        hd_url = re.sub(r'/(s\d+[-h]*|w\d+)/', '/s0/', url)
        
        # 确保 images 目录存在
        if not os.path.exists('images'):
            os.makedirs('images')

        # 生成文件名
        path = urlparse(hd_url).path
        filename = path.split('/')[-1]
        if not filename or '.' not in filename:
            filename = re.sub(r'[^a-zA-Z0-9]', '_', hd_url[-15:]) + ".jpg"
        
        local_path = f"images/{filename}"
        
        # 下载
        r = requests.get(hd_url, timeout=20)
        if r.status_code == 200:
            with open(local_path, 'wb') as f:
                f.write(r.content)
            
            # 【关键修改】确保这里生成的地址是你自己的 GitHub 地址
            # 格式：https://raw.githubusercontent.com/用户名/仓库名/main/images/文件名
            github_url = f"https://raw.githubusercontent.com/{REPO}/main/{local_path}"
            print(f"DEBUG: 成功下载图片 {filename}, 新地址: {github_url}")
            return github_url
        else:
            print(f"DEBUG: 下载失败，状态码: {r.status_code}")
    except Exception as e:
        print(f"DEBUG: 下载异常: {e}")
    
    return url # 实在不行才返回原图

class NotionContentParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.blocks = []
        self.current_text = ""
        self.last_link = "" # 记录上一个 <a> 标签的链接

    def flush_text(self):
        if self.current_text.strip():
            text = self.current_text.strip()
            for i in range(0, len(text), 2000):
                self.blocks.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": text[i:i+2000]}}]}})
        self.current_text = ""

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == 'a':
            self.last_link = attrs_dict.get('href', '')
        elif tag in ['p', 'div', 'br', 'h1', 'h2', 'h3']:
            self.flush_text()
        elif tag == 'img' and 'src' in attrs_dict:
            self.flush_text()
            # 策略：如果图片被 <a> 包裹，且 <a> 链接是图片，优先用 <a> 的链接
            img_src = attrs_dict['src']
            if self.last_link and any(ext in self.last_link.lower() for ext in ['.jpg', '.jpeg', '.png', '.webp']):
                target_url = self.last_link
            else:
                target_url = img_src
            
            new_url = download_image(target_url)
            self.blocks.append({"object": "block", "type": "image", "image": {"type": "external", "external": {"url": new_url}}})

    def handle_data(self, data): self.current_text += data
    def handle_endtag(self, tag):
        if tag == 'a': self.last_link = ""
        elif tag in ['p', 'div', 'h1', 'h2', 'h3']: self.flush_text()

def add_to_notion(title, url, html_content):
    parser = NotionContentParser()
    parser.feed(html_content)
    parser.flush_text()
    
    # 封面图逻辑
    img_match = re.search(r'<img [^>]*src="([^"]+)"', html_content)
    cover_url = download_image(img_match.group(1)) if img_match else None

    data = {
        "parent": {"database_id": DATABASE_ID},
        "properties": {"标题": {"title": [{"text": {"content": title}}]}, "链接": {"url": url}},
        "children": parser.blocks[:100]
    }
    if cover_url: data["cover"] = {"type": "external", "external": {"url": cover_url}}
    
    requests.post("https://api.notion.com/v1/pages", headers={"Authorization": f"Bearer {NOTION_TOKEN}", "Content-Type": "application/json", "Notion-Version": "2022-06-28"}, json=data)

# 执行
feed = feedparser.parse(RSS_URL)
for entry in feed.entries[:3]:
    content = entry.get('content', [{}])[0].get('value', entry.get('summary', ""))
    add_to_notion(entry.title, entry.link, content)
