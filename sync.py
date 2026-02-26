import feedparser
import requests
import os
import re

# 1. 获取配置信息
NOTION_TOKEN = os.getenv('NOTION_TOKEN')
DATABASE_ID = os.getenv('NOTION_DATABASE_ID')
RSS_URL = os.getenv('RSS_URL')

def clean_html(html_string):
    """清理 HTML 标签，并处理 Notion 单个区块 2000 字符的限制"""
    if not html_string: return ""
    clean = re.compile('<.*?>')
    # 过滤标签并截取前 2000 字
    return re.sub(clean, '', html_string)[:2000]

def add_to_notion(title, url, content):
    notion_url = "https://api.notion.com/v1/pages"
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }
    
    # 提取 HTML 中的所有图片链接
    img_urls = re.findall(r'<img [^>]*src="([^"]+)"', content)
    
    # A. 定义页面属性（数据库表格里的列）
    data = {
        "parent": {"database_id": DATABASE_ID},
        "properties": {
            "标题": {"title": [{"text": {"content": title}}]},
            "链接": {"url": url}
        },
        "children": [] # 这里定义页面内部显示的内容
    }

    # B. 处理图片：设为封面，并插入到页面顶端
    if img_urls:
        # 将第一张图设为 Notion 页面封面
        data["cover"] = {"type": "external", "external": {"url": img_urls[0]}}
        
        # 将前 3 张图作为图片块插入页面内部
        for img in img_urls[:3]:
            data["children"].append({
                "object": "block",
                "type": "image",
                "image": {
                    "type": "external",
                    "external": {"url": img}
                }
            })

    # C. 处理文字：作为段落插入页面内部
    data["children"].append({
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [{"text": {"content": clean_html(content)}}]
        }
    })

    # 发送请求创建页面
    response = requests.post(notion_url, headers=headers, json=data)
    return response

# 2. 运行脚本
print(f"正在读取 RSS 源: {RSS_URL}")
feed = feedparser.parse(RSS_URL)

if not feed.entries:
    print("未发现新文章。")
else:
    for entry in feed.entries[:3]:
        # 提取正文内容（适配 Blogspot 格式）
        content_body = entry.get('content', [{}])[0].get('value', entry.get('summary', ""))
        
        print(f"正在同步: {entry.title}")
        res = add_to_notion(entry.title, entry.link, content_body)
        
        if res.status_code == 200:
            print(f"✅ 成功！请点击 Notion 标题查看页面内部内容")
        else:
            print(f"❌ 失败: {res.status_code}, {res.text}")
