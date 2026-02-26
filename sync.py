import feedparser
import requests
import os
import re
from html.parser import HTMLParser
from urllib.parse import urlparse
from datetime import datetime
from collections import defaultdict

# 1. 配置信息 (从 GitHub Secrets 获取)
NOTION_TOKEN = os.getenv('NOTION_TOKEN')
DATABASE_ID = os.getenv('NOTION_DATABASE_ID')
RSS_URL = os.getenv('RSS_URL')
REPO = os.getenv('GITHUB_REPOSITORY')

def get_real_high_res(url):
    """强制转换高清原图链接，将 Google/Blogspot 的缩略图标签替换为原始尺寸标识 /s0/"""
    if not url: return None
    # 匹配并替换 /s320/, /w400/ 等尺寸标记为 /s0/
    return re.sub(r'/(s\d+[-h]*|w\d+)/', '/s0/', url)

def download_image(url, date_str, post_seq, img_index):
    """下载图片并重命名为：日期_文章序号_图片序号.后缀"""
    if not url: return url
    try:
        hd_url = get_real_high_res(url)
        if not os.path.exists('images'):
            os.makedirs('images')

        path = urlparse(hd_url).path
        ext = os.path.splitext(path)[1] or ".jpg"
        if len(ext) > 5: ext = ".jpg" # 修正异常后缀
        
        # 构造唯一文件名: 例如 20260225_01_01.jpg
        new_filename = f"{date_str}_{post_seq:02d}_{img_index:02d}{ext}"
        local_path = f"images/{new_filename}"
        
        # 下载图片
        r = requests.get(hd_url, timeout=20)
        if r.status_code == 200:
            with open(local_path, 'wb') as f:
                f.write(r.content)
            # 返回该图片在 GitHub 仓库中的公开 Raw 链接
            github_url = f"https://raw.githubusercontent.com/{REPO}/main/{local_path}"
            return github_url
    except Exception as e:
        print(f"  ⚠️ 图片处理失败: {e}")
    return url

class NotionContentParser(HTMLParser):
    """HTML 解析器：将文章转为 Notion Blocks 并备份图片"""
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
        """将文字段落切分为 Notion 支持的 2000 字符以内的 Block"""
        if self.current_text.strip():
            text = self.current_text.strip()
            for i in range(0, len(text), 2000):
                self.blocks.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": [{"text": {"content": text[i:i+2000]}}]}
                })
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
            # 优先从包裹图片的链接中提取原图
            target_url = self.last_link if (self.last_link and any(x in self.last_link.lower() for x in ['.jpg','.png','.jpeg','.webp'])) else img_src
            
            new_url = download_image(target_url, self.date_str, self.post_seq, self.img_count)
            if self.img_count == 1: 
                self.first_img_backup_url = new_url
                
            self.blocks.append({
                "object": "block",
                "type": "image",
                "image": {"type": "external", "external": {"url": new_url}}
            })

    def handle_data(self, data): self.current_text += data
    def handle_endtag(self, tag):
        if tag == 'a': self.last_link = ""
        elif tag in ['p', 'div', 'h1', 'h2', 'h3']: self.flush_text()

def add_to_notion(entry, date_str, post_seq, iso_date):
    """创建包含日期和分类属性的 Notion 页面"""
    content_html = entry.get('content', [{}])[0].get('value', entry.get('summary', ""))
    parser = NotionContentParser(date_str, post_seq)
    parser.feed(content_html)
    parser.flush_text()
    
    # 构造页面属性
    data = {
        "parent": {"database_id": DATABASE_ID},
        "properties": {
            "标题": {"title": [{"text": {"content": entry.title}}]},
            "链接": {"url": entry.link},
            "发布日期": {"date": {"start": iso_date}}, # ISO 格式包含 24 小时制时间
            "分类": {"select": {"name": "Sermons Lam"}}
        },
        "children": parser.blocks[:100]
    }
    
    # 设置封面图
    if parser.first_img_backup_url:
        data["cover"] = {"type": "external", "external": {"url": parser.first_img_backup_url}}

    res = requests.post(
        "https://api.notion.com/v1/pages", 
        headers={
            "Authorization": f"Bearer {NOTION_TOKEN}", 
            "Content-Type": "application/json", 
            "Notion-Version": "2022-06-28"
        }, 
        json=data
    )
    return res

# 2. 执行流程
if __name__ == "__main__":
    print(f"🔍 正在连接 RSS 源: {RSS_URL}")
    feed = feedparser.parse(RSS_URL)

    if not feed.entries:
        print("❌ 错误：未发现文章。")
    else:
        # 第一步：按发布日期对所有文章进行排序
        all_entries_with_date = []
        for entry in feed.entries:
            dt_obj = entry.get('published_parsed') or entry.get('updated_parsed')
            dt = datetime(*dt_obj[:6]) if dt_obj else datetime.now()
            all_entries_with_date.append((dt, entry))

        # 按时间升序排列，并取最新的 3 篇
        all_entries_with_date.sort(key=lambda x: x[0])
        latest_entries = all_entries_with_date[-3:] 

        # 第二步：针对这 3 篇按日期分组（确保同一天的序号分配正确）
        final_groups = defaultdict(list)
        for dt, entry in latest_entries:
            d_str = dt.strftime('%Y%m%d')
            iso_date = dt.isoformat()
            final_groups[d_str].append((entry, iso_date))

        # 第三步：按日期顺序同步到 Notion
        sorted_dates = sorted(final_groups.keys())
        for d_str in sorted_dates:
            daily_posts = sorted(final_groups[d_str], key=lambda x: x[0].get('published_parsed', 0))
            for seq, (entry, iso_date) in enumerate(daily_posts, start=1):
                print(f"📖 正在高清同步: [{d_str}] 文章{seq:02d} -> {entry.title}")
                response = add_to_notion(entry, d_str, seq, iso_date)
                if response.status_code == 200:
                    print(f"✅ 同步成功")
                else:
                    print(f"❌ 失败: {response.status_code} - {response.text}")

    print("🏁 最近3篇文章处理完毕。")
