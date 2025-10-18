import requests
import json
import os
import time
from datetime import datetime
from bs4 import BeautifulSoup
import re

# 配置
LOGIN_PAGE_URL = "https://searcade.userveria.com/login"
HOME_URL = "https://searcade.com"

def load_accounts():
    """从环境变量加载账号列表"""
    try:
        accounts_json = os.getenv("SEARCADE_ACCOUNTS", "[]")
        accounts = json.loads(accounts_json)
        return accounts
    except json.JSONDecodeError:
        print("❌ 无法解析账号JSON，请检查环境变量格式")
        return []

def login(username, password):
    """登录单个账号"""
    print(f"\n🔐 正在登录账号: {username}")
    
    try:
        session = requests.Session()
        
        # 自定义headers，模拟真实浏览器
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1"
        }
        
        # 第一步：获取登录页面
        print(f"  📄 获取登录页面...")
        resp = session.get(LOGIN_PAGE_URL, headers=headers, timeout=15, allow_redirects=True)
        print(f"  状态码: {resp.status_code}")
        
        if resp.status_code != 200:
            print(f"  ⚠️  获取登录页面失败，状态码: {resp.status_code}")
        
        # 解析HTML获取form信息
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # 尝试找到CSRF token或其他隐藏字段
        csrf_token = None
        form = soup.find('form')
        
        if form:
            # 尝试多种常见的token字段名
            token_names = ['_token', 'csrf_token', 'token', 'authenticity_token', '_csrf']
            for token_name in token_names:
                csrf_input = form.find('input', {'name': token_name})
                if csrf_input:
                    csrf_token = csrf_input.get('value')
                    print(f"  🔑 找到 {token_name}: {csrf_token[:20]}...")
                    break
        
        # 获取form的action属性
        form_action = None
        if form:
            form_action = form.get('action')
            if form_action and not form_action.startswith('http'):
                form_action = LOGIN_PAGE_URL.rsplit('/', 1)[0] + '/' + form_action.lstrip('/')
            print(f"  📍 Form action: {form_action}")
        
        # 准备登录数据
        login_data = {
            "username": username,
            "password": password,
        }
        
        if csrf_token:
            login_data["_token"] = csrf_token
        
        # 尝试找到其他可能的字段
        if form:
            for input_field in form.find_all('input', {'type': 'hidden'}):
                field_name = input_field.get('name')
                field_value = input_field.get('value')
                if field_name and field_value:
                    login_data[field_name] = field_value
                    print(f"  📝 发现隐藏字段: {field_name}")
        
        # 第二步：提交登录
        print(f"  🚀 发送登录请求...")
        login_url = form_action if form_action else LOGIN_PAGE_URL
        
        login_resp = session.post(
            login_url,
            data=login_data,
            headers=headers,
            timeout=15,
            allow_redirects=True,
            verify=True
        )
        
        print(f"  响应状态码: {login_resp.status_code}")
        print(f"  最终URL: {login_resp.url}")
        
        # 检查是否有重定向（登录成功的标志）
        if login_resp.history:
            print(f"  ✅ 检测到重定向: {login_resp.history[0].status_code} -> {login_resp.status_code}")
        
        # 判断登录是否成功
        success_indicators = [
            "login" not in login_resp.url.lower(),  # 不在登录页
            "dashboard" in login_resp.text.lower(),  # 页面包含dashboard
            "logout" in login_resp.text.lower(),    # 页面包含logout
            "profile" in login_resp.text.lower(),   # 页面包含profile
        ]
        
        if any(success_indicators):
            print(f"✅ 账号 {username} 登录成功")
            return True
        
        # 检查错误信息
        error_keywords = ["invalid", "incorrect", "error", "failed", "unauthorized"]
        if any(keyword in login_resp.text.lower() for keyword in error_keywords):
            print(f"❌ 账号 {username} 登录失败: 可能是用户名或密码错误")
            return False
        
        print(f"⚠️  账号 {username} 登录状态不确定，但未发现明显错误")
        return True
        
    except requests.exceptions.Timeout:
        print(f"❌ 账号 {username} 登录失败: 请求超时")
        return False
    except requests.exceptions.RequestException as e:
        print(f"❌ 账号 {username} 登录失败: {str(e)}")
        return False
    except Exception as e:
        print(f"❌ 账号 {username} 出错: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """主函数"""
    print(f"🚀 Searcade 登录脚本开始运行 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📍 登录地址: {LOGIN_PAGE_URL}\n")
    
    accounts = load_accounts()
    
    if not accounts:
        print("❌ 未找到任何账号信息")
        return
    
    print(f"📊 共找到 {len(accounts)} 个账号\n")
    
    success_count = 0
    fail_count = 0
    
    for i, account in enumerate(accounts, 1):
        username = account.get("username")
        password = account.get("password")
        
        if not username or not password:
            print(f"⚠️  账号 {i} 信息不完整，跳过")
            fail_count += 1
            continue
        
        if login(username, password):
            success_count += 1
        else:
            fail_count += 1
        
        # 两个登录之间稍作延迟
        if i < len(accounts):
            print(f"  ⏳ 等待2秒...")
            time.sleep(2)
    
    print(f"\n" + "="*50)
    print(f"📈 运行完成 - 成功: {success_count}, 失败: {fail_count}")
    print(f"⏰ 完成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*50)
    
    if fail_count > 0 and success_count == 0:
        exit(1)

if __name__ == "__main__":
    main()
