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
    """强制转换高清原图链接，将缩略图标签替换为原始尺寸标识 /s0/"""
    if not url: return None
    # 针对 Google/Blogspot 图片服务器，将 /s320/, /w400/ 等替换为 /s0/
    return re.sub(r'/(s\d+[-h]*|w\d+)/', '/s0/', url)

def download_image(url, date_str, post_seq, img_index):
    """下载图片到本地并返回其在 GitHub 仓库中的公开 Raw 链接"""
    if not url: return url
    try:
        # 转换至高清地址
        hd_url = get_real_high_res(url)
        
        # 确保存储目录存在
        if not os.path.exists('images'):
            os.makedirs('images')

        # 提取并验证后缀名
        path = urlparse(hd_url).path
        ext = os.path.splitext(path)[1] or ".jpg"
        if len(ext) > 5: ext = ".jpg"
        
        # 构造唯一文件名：日期_文章序号_图片序号.后缀
        new_filename = f"{date_str}_{post_seq:02d}_{img_index:02d}{ext}"
        local_path = f"images/{new_filename}"
        
        # 执行下载并写入本地
        r = requests.get(hd_url, timeout=25)
        if r.status_code == 200:
            with open(local_path, 'wb') as f:
                f.write(r.content)
            
            # 返回 GitHub 仓库中的图片地址 (需确保仓库已设为 Public)
            github_url = f"https://raw.githubusercontent.com/{REPO}/main/{local_path}"
            print(f"✅ 已备份大图: {new_filename}")
            return github_url
    except Exception as e:
        print(f"❌ 图片处理失败 ({url}): {e}")
    return url

class NotionContentParser(HTMLParser):
    """HTML 解析器：将文章内容转为 Notion Blocks，并触发图片备份命名逻辑"""
    def __init__(self, date_str, post_seq):
        super().__init__()
        self.blocks = []
        self.current_text = ""
        self.last_link = ""
        self.img_count = 0 
        self.date_str = date_str
        self.post_seq = post_seq
        self.first_img_backup_url = None # 用于存储该文章第一张图备份后的地址

    def flush_text(self):
        """将积累的文本刷新为 Notion 的段落块"""
        if self.current_text.strip():
            text = self.current_text.strip()
            # Notion 单个 Text Block 限制为 2000 字符，此处进行切分
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
        # 记录超链接，用于寻找原图
        if tag == 'a':
            self.last_link = attrs_dict.get('href', '')
        # 遇到换行或分段标签则刷新文字
        elif tag in ['p', 'div', 'br', 'h1', 'h2', 'h3']:
            self.flush_text()
        # 处理图片
        elif tag == 'img' and 'src' in attrs_dict:
            self.flush_text()
            self.img_count += 1
            img_src = attrs_dict['src']
            
            # 如果图片外层有链接且链接指向图片，优先抓取该链接（通常是高清原图）
            target_url = self.last_link if (self.last_link and any(x in self.last_link.lower() for x in ['.jpg','.png','.jpeg','.webp'])) else img_src
            
            # 下载并获取备份后的 GitHub 地址
            new_url = download_image(target_url, self.date_str, self.post_seq, self.img_count)
            
            # 记录第一张图作为封面
            if self.img_count == 1:
                self.first_img_backup_url = new_url
                
            self.blocks.append({
                "object": "block",
                "type": "image",
                "image": {
                    "type": "external",
                    "external": {"url": new_url}
                }
            })

    def handle_data(self, data):
        self.current_text += data

    def handle_endtag(self, tag):
        if tag == 'a':
            self.last_link = ""
        elif tag in ['p', 'div', 'h1', 'h2', 'h3']:
            self.flush_text()

def add_to_notion(entry, date_str, post_seq):
    """创建 Notion 页面并设置属性与内容"""
    content_html = entry.get('content', [{}])[0].get('value', entry.get('summary', ""))
    
    # 解析 HTML 内容并自动备份图片
    parser = NotionContentParser(date_str, post_seq)
    parser.feed(content_html)
    parser.flush_text()
    
    # 构造 Notion API 请求数据
    data = {
        "parent": {"database_id": DATABASE_ID},
        "properties": {
            "标题": {"title": [{"text": {"content": entry.title}}]},
            "链接": {"url": entry.link}
        },
        "children": parser.blocks[:100] # Notion 一次性创建页面的 Blocks 上限
    }
    
    # 设置封面图 (使用解析器中已经处理好的高清 GitHub 地址)
    if parser.first_img_backup_url:
        data["cover"] = {
            "type": "external", 
            "external": {"url": parser.first_img_backup_url}
        }

    # 发送请求
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

# 2. 主执行流程
if __name__ == "__main__":
    print(f"🚀 开始同步任务: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    feed = feedparser.parse(RSS_URL)

    if not feed.entries:
        print("⚠️ 未能在 RSS 中发现任何文章，请检查链接。")
    else:
        # 第一步：按发布日期对文章进行分组计数
        date_groups = defaultdict(list)
        for entry in feed.entries:
            published = entry.get('published_parsed') or entry.get('updated_parsed')
            d_str = datetime(*published[:6]).strftime('%Y%m%d') if published else datetime.now().strftime('%Y%m%d')
            date_groups[d_str].append(entry)

        # 第二步：按日期顺序（从小到大）处理文章
        sorted_dates = sorted(date_groups.keys())
        for d_str in sorted_dates:
            # 同一天的文章按时间先后排序，分配 01, 02 序号
            daily_posts = sorted(date_groups[d_str], key=lambda x: x.get('published_parsed', 0))
            
            for seq, entry in enumerate(daily_posts, start=1):
                print(f"📖 正在高清备份并同步: {d_str} (序号:{seq:02d}) -> {entry.title}")
                response = add_to_notion(entry, d_str, seq)
                
                if response.status_code == 200:
                    print(f"✅ 同步成功")
                else:
                    print(f"❌ 同步失败: {response.status_code} - {response.text}")

    print("🏁 所有任务处理完毕。")
