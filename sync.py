import feedparser
import requests
import os
import re
from html.parser import HTMLParser
from urllib.parse import urlparse
from datetime import datetime
from collections import defaultdict

# 1. 配置信息
NOTION_TOKEN = os.getenv('NOTION_TOKEN')
DATABASE_ID = os.getenv('NOTION_DATABASE_ID')
RSS_URL = os.getenv('RSS_URL')
REPO = os.getenv('GITHUB_REPOSITORY')

def get_real_high_res(url):
    """强制转换高清原图链接"""
    if not url: return None
    return re.sub(r'/(s\d+[-h]*|w\d+)/', '/s0/', url)

def download_image(url, date_str, post_seq, img_index):
    """下载图片到本地并返回其在 GitHub 中的地址"""
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
        
        r = requests.get(hd_url, timeout=15)
        if r.status_code == 200:
            with open(local_path, 'wb') as f:
                f.write(r.content)
            
            github_url = f"https://raw.githubusercontent.com/{REPO}/main/{local_path}"
            return github_url
    except Exception as e:
        print(f"  ⚠️ 图片下载失败: {e}")
    return url

class NotionContentParser(HTMLParser):
    """HTML 解析器"""
    def __init__(self, date_str, post_seq):
        super().__init__()
        self.blocks = []
        self.current_text = ""
        self.last_link = ""
        self.img_count = 0 
        self.date_str = date_str
        self.post_seq = post_seq
        self.first_img_backup_url = None

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
            target_url = self.last_link if (self.last_link and any(x in self.last_link.lower() for x in ['.jpg','.png','.jpeg','.webp'])) else img_src
            new_url = download_image(target_url, self.date_str, self.post_seq, self.img_count)
            if self.img_count == 1:
                self.first_img_backup_url = new_url
            self.blocks.append({"object": "block", "type": "image", "image": {"type": "external", "external": {"url": new_url}}})

    def handle_data(self, data): self.current_text += data
    def handle_endtag(self, tag):
        if tag == 'a': self.last_link = ""
        elif tag in ['p', 'div', 'h1', 'h2', 'h3']: self.flush_text()

def add_to_notion(entry, date_str, post_seq, iso_date):
    """创建 Notion 页面，包含日期和自动分类"""
    content_html = entry.get('content', [{}])[0].get('value', entry.get('summary', ""))
    
    parser = NotionContentParser(date_str, post_seq)
    parser.feed(content_html)
    parser.flush_text()
    
    # 构造 Notion 属性
    data = {
        "parent": {"database_id": DATABASE_ID},
        "properties": {
            "标题": {"title": [{"text": {"content": entry.title}}]},
            "链接": {"url": entry.link},
            # 新增：发布日期 (ISO 8601 格式)
            "发布日期": {"date": {"start": iso_date}},
            # 新增：自动分类
            "分类": {"select": {"name": "Sermons Lam"}}
        },
        "children": parser.blocks[:100]
    }
    
    if parser.first_img_backup_url:
        data["cover"] = {"type": "external", "external": {"url": parser.first_img_backup_url}}

    res = requests.post("https://api.notion.com/v1/pages", 
                       headers={"Authorization": f"Bearer {NOTION_TOKEN}", "Content-Type": "application/json", "Notion-Version": "2022-06-28"}, 
                       json=data)
    return res

# 2. 执行流程
if __name__ == "__main__":
    print(f"🔍 正在读取 RSS: {RSS_URL}")
    feed = feedparser.parse(RSS_URL)

    if not feed.entries:
        print("⚠️ 未发现文章")
    else:
        # 按发布日期分组
        date_groups = defaultdict(list)
        for entry in feed.entries:
            # 提取时间对象
            dt_obj = entry.get('published_parsed') or entry.get('updated_parsed')
            if dt_obj:
                dt = datetime(*dt_obj[:6])
            else:
                dt = datetime.now()
            
            # 存储 YYYYMMDD 用于图片命名
            d_str = dt.strftime('%Y%m%d')
            # 存储 ISO 格式用于 Notion 日期属性 (24小时制)
            iso_date = dt.isoformat()
            
            date_groups[d_str].append((entry, iso_date))

        # 按日期顺序处理
        sorted_dates = sorted(date_groups.keys())
        for d_str in sorted_dates:
            # 同一天的文章按时间先后排序
            daily_posts = sorted(date_groups[d_str], key=lambda x: x[0].get('published_parsed', 0))
            
            for seq, (entry, iso_date) in enumerate(daily_posts, start=1):
                print(f"📖 同步文章: [{d_str}] {entry.title}")
                add_to_notion(entry, d_str, seq, iso_date)
