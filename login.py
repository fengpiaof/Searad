import asyncio
import json
import os
from datetime import datetime
import requests

async def load_accounts():
    """从环境变量加载账号列表"""
    try:
        accounts_json = os.getenv("SEARCADE_ACCOUNTS", "[]")
        accounts = json.loads(accounts_json)
        return accounts
    except json.JSONDecodeError:
        print("❌ 无法解析账号JSON")
        return []

async def login_with_playwright(username, password):
    """使用 Playwright 登录"""
    print(f"\n🔐 正在登录账号: {username}")
    
    try:
        from playwright.async_api import async_playwright
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            
            try:
                # 设置超时
                page.set_default_timeout(30000)
                page.set_default_navigation_timeout(30000)
                
                print(f"  🌐 打开主站点...")
                await page.goto("https://searcade.com/", wait_until="networkidle")
                
                print(f"  🔍 查找登录按钮...")
                # 点击右上方的登录按钮
                login_button_selectors = [
                    'a:has-text("Login")',
                    'a:has-text("Sign in")',
                    'button:has-text("Login")',
                    'button:has-text("Sign in")',
                    '[class*="login"]',
                    '[id*="login"]',
                ]
                
                login_button_found = False
                for selector in login_button_selectors:
                    try:
                        login_button = page.locator(selector).first
                        if await login_button.is_visible():
                            print(f"  ✓ 找到登录按钮，点击...")
                            await login_button.click()
                            login_button_found = True
                            break
                    except:
                        continue
                
                if not login_button_found:
                    print(f"  ⚠️  未找到登录按钮，尝试直接访问登录页面...")
                    await page.goto("https://searcade.userveria.com/login", wait_until="networkidle")
                else:
                    # 等待重定向到登录页面
                    print(f"  ⏳ 等待登录页面加载...")
                    await asyncio.sleep(2)
                
                print(f"  📝 填写用户名...")
                # 尝试多种可能的选择器
                username_selectors = [
                    'input[name="username"]',
                    'input[name="email"]',
                    'input[type="text"]',
                    'input[id*="username"]',
                    'input[id*="email"]',
                ]
                
                username_input = None
                for selector in username_selectors:
                    try:
                        username_input = page.locator(selector).first
                        if await username_input.is_visible():
                            break
                    except:
                        continue
                
                if not username_input:
                    print(f"  ❌ 找不到用户名输入框")
                    await browser.close()
                    return False
                
                await username_input.fill(username)
                
                print(f"  🔐 填写密码...")
                password_selectors = [
                    'input[name="password"]',
                    'input[type="password"]',
                    'input[id*="password"]',
                ]
                
                password_input = None
                for selector in password_selectors:
                    try:
                        password_input = page.locator(selector).first
                        if await password_input.is_visible():
                            break
                    except:
                        continue
                
                if not password_input:
                    print(f"  ❌ 找不到密码输入框")
                    await browser.close()
                    return False
                
                await password_input.fill(password)
                
                print(f"  🚀 点击登录按钮...")
                # 查找登录按钮
                button_selectors = [
                    'button:has-text("Login")',
                    'button:has-text("Sign in")',
                    'button:has-text("登录")',
                    'button[type="submit"]',
                    'button:nth-child(1)',
                ]
                
                button_clicked = False
                for selector in button_selectors:
                    try:
                        button = page.locator(selector).first
                        if await button.is_visible():
                            await button.click()
                            button_clicked = True
                            print(f"  ✓ 已点击登录按钮")
                            break
                    except:
                        continue
                
                if not button_clicked:
                    print(f"  ⚠️  未找到登录按钮，尝试回车...")
                    await password_input.press("Enter")
                
                # 等待页面加载
                print(f"  ⏳ 等待页面响应...")
                await asyncio.sleep(3)
                
                # 检查是否登录成功
                current_url = page.url
                print(f"  📍 当前URL: {current_url}")
                
                # 获取页面内容用于判断
                content = await page.content()
                
                # 验证登录成功的多个指标
                success_checks = []
                
                # 检查1：URL是否离开了登录页面
                if "login" not in current_url.lower():
                    print(f"  ✓ 检查1: URL 已离开登录页面")
                    success_checks.append(True)
                else:
                    print(f"  ✗ 检查1: 仍在登录页面")
                    success_checks.append(False)
                
                # 检查2：页面是否包含 logout/profile/admin 等登录后才有的内容
                logout_keywords = ["logout", "profile", "admin", "dashboard", "account", "settings"]
                has_logout = any(keyword in content.lower() for keyword in logout_keywords)
                if has_logout:
                    print(f"  ✓ 检查2: 页面包含登录后的内容")
                    success_checks.append(True)
                else:
                    print(f"  ✗ 检查2: 未发现登录后的内容")
                    success_checks.append(False)
                
                # 检查3：检查页面是否包含错误信息
                error_keywords = ["invalid", "incorrect", "error", "failed", "unauthorized", "403", "404"]
                has_error = any(keyword in content.lower() for keyword in error_keywords)
                if has_error:
                    print(f"  ✗ 检查3: 页面包含错误信息")
                    success_checks.append(False)
                else:
                    print(f"  ✓ 检查3: 页面无错误信息")
                    success_checks.append(True)
                
                # 检查4：保存页面截图用于调试
                screenshot_path = f"login_screenshot_{username}.png"
                await page.screenshot(path=screenshot_path)
                print(f"  📸 已保存截图: {screenshot_path}")
                
                # 检查5：打印页面标题
                page_title = await page.title()
                print(f"  📄 页面标题: {page_title}")
                
                if all(success_checks):
                    print(f"✅ 账号 {username} 登录成功（通过所有验证）")
                    await browser.close()
                    return True
                elif any(success_checks):
                    print(f"⚠️  账号 {username} 可能登录成功（通过部分验证）")
                    await browser.close()
                    return True
                else:
                    print(f"❌ 账号 {username} 登录失败（未通过验证）")
                    await browser.close()
                    return False
                
            except Exception as e:
                print(f"  ❌ 错误: {str(e)}")
                await browser.close()
                return False
            
    except ImportError:
        print(f"❌ Playwright 未安装")
        return False
    except Exception as e:
        print(f"❌ 登录出错: {str(e)}")
        return False

async def main():
    print(f"🚀 Searcade Playwright 登录脚本 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    accounts = await load_accounts()
    
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
        
        if await login_with_playwright(username, password):
            success_count += 1
        else:
            fail_count += 1
        
        if i < len(accounts):
            await asyncio.sleep(2)
    
    print(f"\n{'='*50}")
    print(f"📈 成功: {success_count}, 失败: {fail_count}")
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}")
    
    if fail_count > 0 and success_count == 0:
        exit(1)

if __name__ == "__main__":
    asyncio.run(main())
