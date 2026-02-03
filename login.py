import asyncio
import json
import os
import random
import re
from datetime import datetime
from pathlib import Path
import requests
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async

# 配置
SCREENSHOT_DIR = Path("screenshots")
SCREENSHOT_DIR.mkdir(exist_ok=True)
AUTH_STATE_FILE = Path("searcade_auth_state.json")

async def load_accounts():
    try:
        accounts_json = os.getenv("SEARCADE_ACCOUNTS", "[]")
        accounts = json.loads(accounts_json)
        print(f"🚀 加载账号数量: {len(accounts)}")
        return accounts
    except Exception as e:
        print(f"❌ 账号解析错误: {e}")
        return []

async def save_screenshot(page, name_prefix: str, username: str) -> str:
    timestamp = datetime.now().strftime("%H%M%S")
    safe_user = "".join([c if c.isalnum() else "_" for c in username])
    path = SCREENSHOT_DIR / f"{name_prefix}_{safe_user}_{timestamp}.png"
    await page.screenshot(path=str(path), full_page=True)
    return str(path)

async def handle_turnstile(page):
    """尝试穿透 Cloudflare Turnstile 复选框"""
    try:
        # 等待 iframe 加载
        iframe_selector = "iframe[src*='challenges.cloudflare.com']"
        await page.wait_for_selector(iframe_selector, timeout=10000)
        
        print("  🔘 发现验证框，尝试点击...")
        # 定位并点击复选框中心点
        cf_frame = page.frame_locator(iframe_selector)
        # 尝试通过选择器点击，如果不行则点击物理中心点
        checkbox = cf_frame.locator("#challenge-stage, .mark, input[type='checkbox']")
        if await checkbox.count() > 0:
            await checkbox.click()
        else:
            # 物理点击位置
            box = await page.locator(iframe_selector).bounding_box()
            if box:
                await page.mouse.click(box['x'] + 30, box['y'] + box['height'] / 2)
        
        # 等待验证通过（通常通过后 iframe 会消失或页面跳转）
        await asyncio.sleep(5)
    except:
        print("  ℹ️ 未检测到验证框或验证已自动完成")

async def login_with_playwright(username, password):
    print(f"\n🔐 任务启动: {username}")
    screenshots = []
    
    async with async_playwright() as p:
        # 启动浏览器
        browser = await p.chromium.launch(headless=True, args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-blink-features=AutomationControlled"
        ])
        
        # 创建上下文，模拟正常浏览器环境
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
        )
        
        page = await context.new_page()
        await stealth_async(page)

        try:
            # 1. 访问首页（这是建立信任的第一步）
            print("  🌐 访问首页中...")
            await page.goto("https://searcade.com/", wait_until="networkidle", timeout=60000)
            
            # 2. 处理首页可能出现的 CF 验证
            await asyncio.sleep(5) 
            await handle_turnstile(page)

            # 3. 检查是否需要登录
            content = await page.content()
            if any(kw in content.lower() for kw in ["logout", "profile", "dashboard"]):
                print("  ✅ 检测到已登录状态")
                success = True
            else:
                # 4. 前往登录页
                print("  🖱️ 跳转登录界面...")
                # 优先点击页面上的 Login 按钮
                login_btn = page.get_by_role("link", name=re.compile("Login|Sign In", re.I)).first
                if await login_btn.is_visible():
                    await login_btn.click()
                else:
                    # 如果找不到按钮，直接跳转（使用你原先成功的路径逻辑）
                    await page.goto("https://searcade.com/login", wait_until="networkidle")

                # 5. 等待表单并填写
                print("  📝 填写凭据...")
                # 使用正则表达式适配多种可能的 input name/placeholder
                user_input = page.get_by_placeholder(re.compile("username|email", re.I))
                if await user_input.count() == 0:
                    user_input = page.locator('input[name="username"], input[name="email"]')
                
                await user_input.fill(username)
                await page.get_by_placeholder(re.compile("password", re.I)).fill(password)
                
                # 截图：提交前
                screenshots.append(await save_screenshot(page, "01_before_submit", username))
                
                # 提交（模拟回车比点击按钮更难被检测）
                await page.keyboard.press("Enter")
                
                # 6. 等待结果并验证
                print("  ⏳ 等待跳转结果...")
                await asyncio.sleep(10)
                final_content = await page.content()
                success = any(kw in final_content.lower() for kw in ["logout", "profile", "dashboard", "settings"])

            if success:
                print("  🎉 登录成功！")
                # 保存 Session 供下次使用
                await context.storage_state(path=str(AUTH_STATE_FILE))
            else:
                print("  ❌ 登录最终确认失败")
                screenshots.append(await save_screenshot(page, "02_fail_result", username))

            await browser.close()
            return success, screenshots

        except Exception as e:
            print(f"  ❌ 运行异常: {e}")
            screenshots.append(await save_screenshot(page, "00_crash", username))
            await browser.close()
            return False, screenshots

def send_tg(message, success, fail):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id: return
    
    text = f"<b>Searcade 自动登录报告</b>\n\n{message}\n\n📊 成功: {success} | 失败: {fail}"
    requests.post(f"https://api.telegram.org/bot{token}/sendMessage", 
                  data={"chat_id": chat_id, "text": text, "parse_mode": "HTML"})

async def main():
    accounts = await load_accounts()
    if not accounts: return

    results = []
    s_count = f_count = 0

    for acc in accounts:
        user = acc.get("username") or acc.get("email")
        pwd = acc.get("password")
        
        ok, _ = await login_with_playwright(user, pwd)
        
        if ok:
            s_count += 1
            results.append(f"✅ {user}")
        else:
            f_count += 1
            results.append(f"❌ {user}")
        
        await asyncio.sleep(random.uniform(5, 10))

    send_tg("\n".join(results), s_count, f_count)

if __name__ == "__main__":
    asyncio.run(main())
