import asyncio
import json
import os
import random
from datetime import datetime
from pathlib import Path
import requests
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async

# 截图保存目录
SCREENSHOT_DIR = Path("screenshots")
SCREENSHOT_DIR.mkdir(exist_ok=True)

# 认证状态文件
AUTH_STATE_FILE = Path("searcade_auth_state.json")

async def load_accounts():
    try:
        accounts_json = os.getenv("SEARCADE_ACCOUNTS", "[]")
        accounts = json.loads(accounts_json)
        print(f"🚀 成功加载 {len(accounts)} 个账号")
        return accounts
    except json.JSONDecodeError as e:
        print(f"❌ 账号解析失败: {e}")
        return []

async def save_screenshot(page, name_prefix: str, username: str) -> str:
    timestamp = datetime.now().strftime("%H%M%S")
    safe_username = username.replace("@", "_").replace(".", "_")
    path = SCREENSHOT_DIR / f"{name_prefix}_{safe_username}_{timestamp}.png"
    await page.screenshot(path=str(path), full_page=True)
    return str(path)

async def handle_turnstile(page, username: str) -> bool:
    """专为 Cloudflare Turnstile 设计的突破逻辑"""
    try:
        print("  🔍 正在扫描 Cloudflare 验证框...")
        # 等待验证框出现（可能是 iframe 或特定的 div）
        turnstile_selector = "iframe[src*='challenges.cloudflare.com']"
        
        try:
            # 等待 10 秒看是否出现验证码
            await page.wait_for_selector(turnstile_selector, timeout=10000)
            print("  ⚠️ 发现 Cloudflare 验证，尝试破解...")
        except:
            print("  ✅ 未发现验证码或已自动通过")
            return True

        # 1. 尝试进入 iframe 点击复选框
        try:
            # Cloudflare 的复选框通常在 iframe 里的这个位置
            # 有时是一个 span 或者是 input
            cf_frame = page.frame_locator(turnstile_selector)
            checkbox = cf_frame.locator("input[type='checkbox'], #challenge-stage, .mark")
            
            if await checkbox.count() > 0:
                print("  🔘 找到复选框，模拟点击...")
                await asyncio.sleep(random.uniform(1, 2))
                await checkbox.click()
            else:
                # 如果没找到具体元素，尝试点击 iframe 的中心点
                box = await page.locator(turnstile_selector).bounding_box()
                if box:
                    await page.mouse.click(box['x'] + box['width']/2, box['y'] + box['height']/2)
                    print("  🔘 点击了验证框中心区域")
        except Exception as e:
            print(f"  ℹ️ 辅助点击未生效 (可能已开始自动验证): {e}")

        # 2. 轮询检查验证结果
        for i in range(20):
            # 检查验证 token 是否已填入
            token = await page.evaluate('''() => document.querySelector("input[name='cf-turnstile-response']")?.value || ""''')
            if token and len(token) > 30:
                print(f"  ✅ 验证通过！(耗时 {i}s)")
                return True
            
            # 检查验证框是否已经消失
            if await page.locator(turnstile_selector).count() == 0:
                print("  🎉 验证框已关闭，通过")
                return True
            
            await asyncio.sleep(1.5)

        print("  ❌ 验证超时")
        await save_screenshot(page, "turnstile_timeout", username)
        return False
    except Exception as e:
        print(f"  ⚠️ 验证处理异常: {e}")
        return True

async def login_with_playwright(username: str, password: str) -> tuple[bool, list[str]]:
    print(f"\n🔐 正在处理: {username}")
    screenshots = []

    async with async_playwright() as p:
        # 增强版启动参数
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--ignore-certificate-errors",
                "--window-size=1920,1080"
            ]
        )
        
        # 注入真实的 User-Agent
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        
        page = await context.new_page()
        await stealth_async(page)

        try:
            # 1. 尝试使用 Session 登录
            if AUTH_STATE_FILE.exists():
                print("  🔑 加载已存 Session...")
                with open(AUTH_STATE_FILE, 'r') as f:
                    storage_state = json.load(f)
                await context.add_cookies(storage_state.get('cookies', []))

            # 2. 访问首页
            print("  🌐 正在打开首页...")
            await page.goto("https://searcade.com/", wait_until="domcontentloaded", timeout=60000)
            
            # 处理首页可能存在的验证
            await handle_turnstile(page, username)

            # 3. 检查是否已经登录成功（通过 Session）
            content = await page.content()
            if any(kw in content.lower() for kw in ["logout", "profile", "dashboard"]):
                print("  ✅ Session 有效，自动登录成功")
                success = True
            else:
                # 4. 执行完整登录
                print("  🔄 Session 失效，执行表单登录...")
                await page.goto("https://searcade.userveria.com/login", wait_until="networkidle")
                
                await handle_turnstile(page, username)
                
                print("  📝 填写表单...")
                await page.fill('input[name="username"], input[name="email"]', username)
                await page.fill('input[name="password"]', password)
                
                # 截图记录表单填写状态
                screenshots.append(await save_screenshot(page, "02_before_submit", username))
                
                await page.click('button[type="submit"]')
                
                # 登录提交后可能还有一次验证
                await asyncio.sleep(5)
                await handle_turnstile(page, username)
                
                # 最终检查
                await page.wait_for_load_state("networkidle")
                final_content = await page.content()
                success = any(kw in final_content.lower() for kw in ["logout", "profile", "dashboard"])

            if success:
                print("  🎉 登录确认成功！")
                state = await context.storage_state()
                with open(AUTH_STATE_FILE, 'w') as f:
                    json.dump(state, f)
            else:
                print("  ❌ 登录失败，检查截图")
                screenshots.append(await save_screenshot(page, "fail_final", username))

            await browser.close()
            return success, screenshots

        except Exception as e:
            print(f"  ❌ 运行异常: {str(e)}")
            screenshots.append(await save_screenshot(page, "exception", username))
            await browser.close()
            return False, screenshots

def send_telegram_notification(title, message, success_count, fail_count):
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id: return

    status_icon = "✅" if fail_count == 0 else "⚠️"
    text = f"{status_icon} <b>{title}</b>\n\n{message}\n\n📊 成功: {success_count} | 失败: {fail_count}\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    
    try:
        requests.post(f"https://api.telegram.org/bot{bot_token}/sendMessage",
                      data={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=10)
    except: pass

async def main():
    accounts = await load_accounts()
    if not accounts: return

    success_count = fail_count = 0
    results = []

    for i, acc in enumerate(accounts, 1):
        username = acc.get("username") or acc.get("email")
        password = acc.get("password")

        success, _ = await login_with_playwright(username, password)
        
        if success:
            success_count += 1
            results.append(f"✅ {username}")
        else:
            fail_count += 1
            results.append(f"❌ {username}")

        if i < len(accounts):
            await asyncio.sleep(random.uniform(5, 10))

    send_telegram_notification("Searcade 自动登录结果", "\n".join(results), success_count, fail_count)

if __name__ == "__main__":
    asyncio.run(main())
