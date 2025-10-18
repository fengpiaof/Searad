import requests
import json
import os
import time
from datetime import datetime

def load_accounts():
    """从环境变量加载账号列表"""
    try:
        accounts_json = os.getenv("SEARCADE_ACCOUNTS", "[]")
        accounts = json.loads(accounts_json)
        return accounts
    except json.JSONDecodeError:
        print("❌ 无法解析账号JSON")
        return []

def login_via_api(username, password):
    """尝试通过 API 登录"""
    print(f"\n🔐 正在登录账号: {username}")
    
    try:
        session = requests.Session()
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Referer": "https://searcade.userveria.com/login"
        }
        
        # 尝试多个可能的API端点
        api_endpoints = [
            "https://searcade.userveria.com/api/login",
            "https://searcade.userveria.com/api/auth/login",
            "https://searcade.userveria.com/login",
            "https://api.searcade.com/login",
            "https://api.searcade.com/auth/login",
        ]
        
        login_data = {
            "username": username,
            "password": password,
            "email": username,  # 有些系统用email代替username
        }
        
        for endpoint in api_endpoints:
            try:
                print(f"  🔗 尝试 API 端点: {endpoint}")
                
                # 尝试 POST JSON
                resp = session.post(
                    endpoint,
                    json=login_data,
                    headers=headers,
                    timeout=10,
                    allow_redirects=True
                )
                
                print(f"    状态码: {resp.status_code}")
                
                # 检查响应
                if resp.status_code == 200:
                    try:
                        resp_json = resp.json()
                        if "token" in resp_json or "success" in resp_json or "user" in resp_json:
                            print(f"✅ 账号 {username} 通过 {endpoint} 登录成功")
                            return True
                    except:
                        pass
                    
                    # 即使不是JSON，200也可能是成功
                    if "error" not in resp.text.lower() and "invalid" not in resp.text.lower():
                        print(f"✅ 账号 {username} 通过 {endpoint} 登录成功")
                        return True
                
                # 尝试 POST form-data
                if resp.status_code >= 400:
                    print(f"    尝试 form-data 格式...")
                    form_headers = headers.copy()
                    form_headers["Content-Type"] = "application/x-www-form-urlencoded"
                    
                    form_data = {
                        "username": username,
                        "password": password,
                    }
                    
                    resp = session.post(
                        endpoint,
                        data=form_data,
                        headers=form_headers,
                        timeout=10,
                        allow_redirects=True
                    )
                    
                    print(f"    状态码: {resp.status_code}")
                    
                    if resp.status_code == 200:
                        print(f"✅ 账号 {username} 通过 {endpoint} 登录成功")
                        return True
                
            except requests.exceptions.Timeout:
                print(f"    ⏱️  超时")
                continue
            except Exception as e:
                print(f"    ❌ 错误: {str(e)[:50]}")
                continue
        
        print(f"❌ 账号 {username} 所有API端点都失败了")
        return False
        
    except Exception as e:
        print(f"❌ 账号 {username} 登录出错: {str(e)}")
        return False

def main():
    print(f"🚀 Searcade API 登录脚本 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    accounts = load_accounts()
    
    if not accounts:
        print("❌ 未找到任何账号")
        return
    
    print(f"📊 共找到 {len(accounts)} 个账号\n")
    
    success_count = 0
    fail_count = 0
    
    for i, account in enumerate(accounts, 1):
        username = account.get("username")
        password = account.get("password")
        
        if not username or not password:
            print(f"⚠️  账号 {i} 信息不完整")
            fail_count += 1
            continue
        
        if login_via_api(username, password):
            success_count += 1
        else:
            fail_count += 1
        
        if i < len(accounts):
            time.sleep(2)
    
    print(f"\n{'='*50}")
    print(f"📈 成功: {success_count}, 失败: {fail_count}")
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}")
    
    if fail_count > 0 and success_count == 0:
        exit(1)

if __name__ == "__main__":
    main()
