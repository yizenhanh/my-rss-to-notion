import feedparser
import requests
import os
import re
from html.parser import HTMLParser
from urllib.parse import urlparse
from datetime import datetime

# 1. 配置
NOTION_TOKEN = os.getenv('NOTION_TOKEN')
DATABASE_ID = os.getenv('NOTION_DATABASE_ID')
RSS_URL = os.getenv('RSS_URL')
REPO = os.getenv('GITHUB_REPOSITORY')

def download_image(url, date_str, post_index, img_index):
    """
    按照 20260226_01_01.jpg 格式重命名并下载
    date_str: YYYYMMDD
    post_index: 文章在当天的序号 (01, 02...)
    img_index: 图片在文章内的序号 (01, 02...)
    """
    if not url: return url
    try:
        # 强制高清
        hd_url = re.sub(r'/(s\d+[-h]*|w\d+)/', '/s0/', url)
        
        # 确保目录存在
        if not os.path.exists('images'):
            os.makedirs('images')

        # 获取后缀名
        path = urlparse(hd_url).path
        ext = os.path.splitext(path)[1] or ".jpg"
        if len(ext) > 5: ext = ".jpg" # 处理异常后缀
        
        # 构造新文件名: 20260226_01_01.jpg
        new_filename = f"{date_str}_{post_index:02d}_{img_index:02d}{ext}"
        local_path = f"images/{new_filename}"
        
        # 下载
        r = requests.get(hd_url, timeout=20)
        if r.status_code == 200:
            with open(local_path, 'wb') as f:
                f.write(r.content)
            
            # 生成 GitHub 引用地址
            github_url = f"https://raw.githubusercontent.com/{REPO}/main/{local_path}"
            print(f"✅ 已存大图: {new_filename}")
            return github_url
    except Exception as e:
        print(f"❌ 下载失败: {e}")
    return url

class NotionContentParser(HTMLParser):
    def __init__(self, date_str, post_idx):
        super().__init__()
        self.blocks = []
        self.current_text = ""
        self.last_link = ""
        self.img_count = 0  # 图片在该文章内的计数器
        self.date_str = date_str
        self.post_idx = post_idx

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
            
            # 传入计数器参数进行重命名
            new_url = download_image(target_url, self.date_str, self.post_idx, self.img_count)
            self.blocks.append({"object": "block", "type": "image", "image": {"type": "external", "external": {"url": new_url}}})

    def handle_data(self, data): self.current_text += data
    def handle_endtag(self, tag):
        if tag == 'a': self.last_link = ""
        elif tag in ['p', 'div', 'h1', 'h2', 'h3']: self.flush_text()

def add_to_notion(entry, post_idx):
    # 提取日期 YYYYMMDD
    published = entry.get('published_parsed') or entry.get('updated_parsed')
    date_str = datetime(*published[:6]).strftime('%Y%m%d') if published else datetime.now().strftime('%Y%m%d')
    
    content_html = entry.get('content', [{}])[0].get('value', entry.get('summary', ""))
    
    # 初始化解析器时传入日期和文章序号
    parser = NotionContentParser(date_str, post_idx)
    parser.feed(content_html)
    parser.flush_text()
    
    # 封面图逻辑 (同样使用重命名后的第一张图)
    first_img = re.search(r'<img [^>]*src="([^"]+)"', content_html)
    cover_url = None
    if first_img:
        # 封面图逻辑上是该文章的第1张图，但为了不重复下载，我们直接引用 parser 里的第一个结果即可
        # 这里简单化处理，重新算一次获取重命名后的地址
        cover_url = download_image(first_img.group(1), date_str, post_idx, 1)

    data = {
        "parent": {"database_id": DATABASE_ID},
        "properties": {
            "标题": {"title": [{"text": {"content": entry.title}}]},
            "链接": {"url": entry.link}
        },
        "children": parser.blocks[:100]
    }
    if cover_url: data["cover"] = {"type": "external", "external": {"url": cover_url}}
    
    res = requests.post("https://api.notion.com/v1/pages", 
                       headers={"Authorization": f"Bearer {NOTION_TOKEN}", "Content-Type": "application/json", "Notion-Version": "2022-06-28"}, 
                       json=data)
    return res

# 2. 执行
print("🚀 开始同步...")
feed = feedparser.parse(RSS_URL)

# 文章按发布日期从旧到新排序（或者你想要从新到旧，可以去掉 reverse）
# 这样同一天的文章序号 (01, 02) 才会固定
entries = sorted(feed.entries, key=lambda x: x.get('published_parsed', 0))

# 仅处理最近的 3 篇，或者你可以根据需求调整
for i, entry in enumerate(entries[-3:], start=1):
    print(f"📖 正在处理第 {i} 篇文章: {entry.title}")
    add_to_notion(entry, i)
