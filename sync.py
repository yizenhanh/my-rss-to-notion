import feedparser
import requests
import os

# 1. 从 GitHub Secrets 获取配置信息
NOTION_TOKEN = os.getenv('NOTION_TOKEN')
DATABASE_ID = os.getenv('NOTION_DATABASE_ID')
RSS_URL = os.getenv('RSS_URL')

def add_to_notion(title, url):
    """将单篇文章的信息发送到 Notion 数据库"""
    notion_url = "https://api.notion.com/v1/pages"
    
    # 设置请求头，用于身份验证
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }
    
    # 构建发送给 Notion 的数据结构
    # 注意：这里的 "标题" 和 "链接" 必须与您 Notion 数据库的列名完全一致
    data = {
        "parent": {"database_id": DATABASE_ID},
        "properties": {
            "标题": {
                "title": [
                    {
                        "text": {
                            "content": title
                        }
                    }
                ]
            },
            "链接": {
                "url": url
            }
        }
    }
    
    # 发送请求
    response = requests.post(notion_url, headers=headers, json=data)
    return response

# 2. 开始解析 RSS 源
print(f"正在尝试解析 RSS: {RSS_URL}")
feed = feedparser.parse(RSS_URL)

# 检查 RSS 是否解析成功
if not feed.entries:
    print("未能从 RSS 中获取到文章，请检查链接是否正确。")
else:
    # 3. 循环处理最近的 3 篇文章
    for entry in feed.entries[:3]:
        print(f"正在处理文章: {entry.title}")
        res = add_to_notion(entry.title, entry.link)
        
        # 4. 打印运行结果，方便我们在 GitHub Actions 日志中排查
        if res.status_code == 200:
            print(f"✅ 成功导入: {entry.title}")
        else:
            print(f"❌ 导入失败: {entry.title}")
            print(f"错误代码: {res.status_code}")
            print(f"错误详情: {res.text}")

print("任务执行完毕。")
