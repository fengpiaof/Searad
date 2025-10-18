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
API_LOGIN_URL = "https://searcade.userveria.com/api/login"  # 可能的API端点

def load_accounts():
    """从环境变量加载账号列表"""
    try:
        accounts_json = os.getenv("SEARCADE_ACCOUNTS", "[]")
        accounts = json.loads(accounts_json)
        return accounts
    except json.JSONDecodeError:
        print("❌ 无法解析账号JSON，请检查环境变量格式")
        return []

def login_with_requests(username, password):
    """使用requests库登录"""
    print(f"\n🔐 正在登录账号: {username}")
    
    try:
        session = requests.Session()
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        
        # 第一步：获取登录页面，获取可能的token或form信息
        print(f"  📄 获取登录页面...")
        resp = session.get(LOGIN_PAGE_URL, headers=headers, timeout=15)
        print(f"  状态码: {resp.status_code}")
        
        # 解析HTML获取form信息
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # 尝试找到CSRF token或其他隐藏字段
        csrf_token = None
        form = soup.find('form')
        if form:
            csrf_input = form.find('input', {'name': '_token'}) or form.find('input', {'name': 'csrf_token'})
            if csrf_input:
                csrf_token = csrf_input.get('value')
                print(f"  🔑 找到CSRF token")
        
        # 准备登录数据
        login_data = {
            "username": username,
            "password": password,
        }
        
        if csrf_token:
            login_data["_token"] = csrf_token
        
        # 第二步：尝试登录
        print(f"  🚀 发送登录请求...")
        login_resp = session.post(
            LOGIN_PAGE_URL,
            data=login_data,
            headers=headers,
            timeout=15,
            allow_redirects=True
        )
        
        print(f"  响应状态码: {login_resp.status_code}")
        print(f"  最终URL: {login_resp.url}")
        
        # 判断登录是否成功
        if "login" in login_resp.url.lower() and login_resp.status_code == 200:
            # 检查是否有错误信息
            if "error" in login_resp.text.lower() or "invalid" in login_resp.text.lower():
                print(f"❌ 账号 {username} 登录失败: 用户名或密码错误")
                return False
        
        # 检查关键词判断是否登录成功
        success_keywords = ["dashboard", "profile", "logout", "account", "panel"]
        if any(keyword in login_resp.text.lower() for keyword in success_keywords):
            print(f"✅ 账号 {username} 登录成功")
            return True
        elif login_resp.status_code == 200 and "login" not in login_resp.url.lower():
            print(f"✅ 账号 {username} 登录可能成功 (已重定向)")
            return True
        else:
            print(f"⚠️  账号 {username} 登录状态不确定")
            return False
        
    except requests.exceptions.Timeout:
        print(f"❌ 账号 {username} 登录失败: 请求超时")
        return False
    except requests.exceptions.RequestException as e:
        print(f"❌ 账号 {username} 登录失败: {str(e)}")
        return False
    except Exception as e:
        print(f"❌ 账号 {username} 出错: {str(e)}")
        return False

def login_with_selenium(username, password):
    """使用Selenium登录（如果requests失败）"""
    try:
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.chrome.options import Options
        
        print(f"\n🔐 使用Selenium登录账号: {username}")
        
        # 配置Chrome选项
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        
        driver = webdriver.Chrome(options=chrome_options)
        
        try:
            # 打开登录页面
            driver.get(LOGIN_PAGE_URL)
            time.sleep(2)
            
            # 查找输入框
            username_input = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.NAME, "username"))
            )
            
            password_input = driver.find_element(By.NAME, "password")
            
            # 输入凭证
            username_input.send_keys(username)
            password_input.send_keys(password)
            
            # 查找并点击登录按钮
            login_button = driver.find_element(By.XPATH, "//button[contains(text(), 'Login') or contains(text(), 'Sign in')]")
            login_button.click()
            
            # 等待登录完成
            time.sleep(3)
            
            current_url = driver.current_url
            print(f"  最终URL: {current_url}")
            
            if "login" not in current_url.lower():
                print(f"✅ 账号 {username} 登录成功")
                return True
            else:
                print(f"❌ 账号 {username} 登录失败")
                return False
                
        finally:
            driver.quit()
            
    except ImportError:
        print(f"⚠️  Selenium未安装，跳过该登录方法")
        return False
    except Exception as e:
        print(f"❌ Selenium登录失败: {str(e)}")
        return False

def main():
    """主函数"""
    print(f"🚀 Searcade 登录脚本开始运行 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    accounts = load_accounts()
    
    if not accounts:
        print("❌ 未找到任何账号信息")
        return
    
    print(f"📊 共找到 {len(accounts)} 个账号\n")
    
    success_count = 0
    fail_count = 0
    
    for account in accounts:
        username = account.get("username")
        password = account.get("password")
        
        if not username or not password:
            print(f"⚠️  跳过不完整的账号信息")
            fail_count += 1
            continue
        
        # 先尝试用requests
        if login_with_requests(username, password):
            success_count += 1
        else:
            # 如果失败，尝试用Selenium
            if login_with_selenium(username, password):
                success_count += 1
            else:
                fail_count += 1
        
        # 两个登录之间稍作延迟
        time.sleep(2)
    
    print(f"\n" + "="*50)
    print(f"📈 运行完成 - 成功: {success_count}, 失败: {fail_count}")
    print(f"⏰ 完成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*50)
    
    if fail_count > 0 and success_count == 0:
        exit(1)

if __name__ == "__main__":
    main()
