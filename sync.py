import feedparser
import requests
import os
import re
from html.parser import HTMLParser
from urllib.parse import urlparse
from datetime import datetime
from collections import defaultdict

# 1. 配置
NOTION_TOKEN = os.getenv('NOTION_TOKEN')
DATABASE_ID = os.getenv('NOTION_DATABASE_ID')
RSS_URL = os.getenv('RSS_URL')
REPO = os.getenv('GITHUB_REPOSITORY')

def get_real_high_res(url):
    """强制转换高清原图链接"""
    if not url: return None
    # 将 /sXXX/ 或 /wXXX/ 替换为 /s0/ (原始尺寸)
    return re.sub(r'/(s\d+[-h]*|w\d+)/', '/s0/', url)

def download_image(url, date_str, post_seq, img_index):
    """下载并重命名大图"""
    if not url: return url
    try:
        hd_url = get_real_high_res(url)
        
        if not os.path.exists('images'):
            os.makedirs('images')

        path = urlparse(hd_url).path
        ext = os.path.splitext(path)[1] or ".jpg"
        if len(ext) > 5: ext = ".jpg"
        
        new_filename = f"{date_str}_{post_seq:02d}_{img_index:02d}{ext}"
        local_path = f"images/{new_filename}"
        
        # 执行下载
        r = requests.get(hd_url, timeout=20)
        if r.status_code == 200:
            with open(local_path, 'wb') as f:
                f.write(r.content)
            
            github_url = f"https://raw.githubusercontent.com/{REPO}/main/{local_path}"
            return github_url
    except Exception as e:
        print(f"❌ 图片处理失败: {e}")
    return url

class NotionContentParser(HTMLParser):
    def __init__(self, date_str, post_seq):
        super().__init__()
        self.blocks = []
        self.current_text = ""
        self.last_link = ""
        self.img_count = 0 
        self.date_str = date_str
        self.post_seq = post_seq
        self.first_img_url = None # 记录第一张图的高清地址给封面使用

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
            self.img_count += 1
            img_src = attrs_dict['src']
            
            # 优先使用链接中的地址
            target_url = self.last_link if (self.last_link and any(x in self.last_link.lower() for x in ['.jpg','.png','.jpeg','.webp'])) else img_src
            
            # 下载并获取 GitHub 地址
            new_url = download_image(target_url, self.date_str, self.post_seq, self.img_count)
            
            # 如果是第一张图，保存下来作为封面地址
            if self.img_count == 1:
                self.first_img_url = new_url
                
            self.blocks.append({"object": "block", "type": "image", "image": {"type": "external", "external": {"url": new_url}}})

    def handle_data(self, data): self.current_text += data
    def handle_endtag(self, tag):
        if tag == 'a': self.last_link = ""
        elif tag in ['p', 'div', 'h1', 'h2', 'h3']: self.flush_text()

def add_to_notion(entry, date_str, post_seq):
    content_html = entry.get('content', [{}])[0].get('value', entry.get('summary', ""))
    
    # 核心：先解析正文，在此过程中会自动下载并重命名所有图片
    parser = NotionContentParser(date_str, post_seq)
    parser.feed(content_html)
    parser.flush_text()
    
    # 属性设置
    data = {
        "parent": {"database_id": DATABASE_ID},
        "properties": {
            "标题": {"title": [{"text": {"content": entry.title}}]},
            "链接": {"url": entry.link}
        },
        "children": parser.blocks[:100]
    }
    
    # 关键修复：直接使用解析过程中抓取到的第一张图（已经是高清且已重命名的 GitHub 地址）
    if parser.first_img_url:
        data["cover"] = {"type": "external", "external": {"url": parser.first_img_url}}

    res = requests.post("https://api.notion.com/v1/pages", 
                       headers={"Authorization": f"Bearer {NOTION_TOKEN}", "Content-Type": "application/json", "Notion-Version": "2022-06-28"}, 
                       json=data)
    return res

# 2. 运行
feed = feedparser.parse(RSS_URL)
date_groups = defaultdict(list)
for entry in feed.entries:
    published = entry.get('published_parsed') or entry.get('updated_parsed')
    d_str = datetime(*published[:6]).strftime('%Y%m%d') if published else datetime.now().strftime('%Y%m%d')
    date_groups[d_str].append(entry)

sorted_dates = sorted(date_groups.keys())
for d_str in sorted_dates:
    daily_posts = sorted(date_groups[d_str], key=lambda x: x.get('published_parsed', 0))
    for seq, entry in enumerate(daily_posts, start=1):
        print(f"📖 正在高清同步: {d_str} 文章 {seq}")
        add_to_notion(entry, d_str, seq)
