import asyncio
import json
import os
import random
from datetime import datetime
from pathlib import Path
import requests
from playwright.async_api import async_playwright, TimeoutError
from playwright_stealth import stealth_async

# 截图保存目录
SCREENSHOT_DIR = Path("screenshots")
SCREENSHOT_DIR.mkdir(exist_ok=True)

# 认证状态文件
AUTH_STATE_FILE = Path("searcade_auth_state.json")

async def load_accounts():
    try:
        accounts_json = os.getenv("SEARCADE_ACCOUNTS", "[]")
        print(f"DEBUG: SEARCADE_ACCOUNTS 长度: {len(accounts_json)}")
        accounts = json.loads(accounts_json)
        print(f"加载账号成功: {len(accounts)} 个")
        return accounts
    except json.JSONDecodeError as e:
        print(f"❌ 无法解析账号JSON: {e}")
        return []


async def save_screenshot(page, name_prefix: str, username: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_username = username.replace("@", "_").replace(".", "_")
    path = SCREENSHOT_DIR / f"{name_prefix}_{safe_username}_{timestamp}.png"
    await page.screenshot(path=str(path), full_page=True)
    print(f"📸 保存截图: {path}")
    return str(path)


async def is_already_logged_in(page):
    content_lower = (await page.content()).lower()
    url_lower = page.url.lower()
    return (
        "login" not in url_lower and
        any(kw in content_lower for kw in ["logout", "sign out", "profile", "dashboard", "account", "settings", "my server"])
    )


async def try_load_state_and_check_login(context, page, username: str) -> bool:
    if not AUTH_STATE_FILE.exists():
        print("  ⚠️ 无 auth state 文件，需要完整登录")
        return False

    try:
        print(f"  🔑 加载 state: {AUTH_STATE_FILE}")
        await context.storage_state(path=str(AUTH_STATE_FILE))

        await page.goto("https://searcade.com/", wait_until="networkidle", timeout=45000)
        if await is_already_logged_in(page):
            print(f"  ✅ state 有效，已登录 ({username})")
            await save_screenshot(page, "state_logged_in", username)
            return True
        else:
            print("  ⚠️ state 失效，需要重新登录")
            return False
    except Exception as e:
        print(f"  ❌ 加载 state 失败: {str(e)}")
        return False


async def handle_turnstile(page, username: str) -> bool:
    try:
        await asyncio.sleep(random.uniform(3, 5))

        iframe_locator = page.frame_locator('iframe[title*="challenge"], iframe[title*="turnstile"], iframe[src*="turnstile"]')
        try:
            await iframe_locator.locator("body").wait_for(state="visible", timeout=25000)
            print("  ✓ 定位到 Turnstile iframe")
        except PlaywrightTimeoutError:
            print("  ✓ 无 Turnstile iframe，视为通过")
            return True

        checkbox_locator = iframe_locator.locator(
            'input[type="checkbox"], div[class*="checkbox"], label[for*="cf-"], [role="checkbox"], [aria-label*="verify"]'
        )
        await checkbox_locator.wait_for(state="visible", timeout=20000)
        print("  ✓ 找到 checkbox")

        await checkbox_locator.hover()
        await asyncio.sleep(random.uniform(0.5, 1.5))
        await checkbox_locator.click(delay=random.uniform(100, 300))
        print("  🖱️ 已点击 iframe 内 checkbox")

        validated = False
        for _ in range(40):
            token = await page.evaluate('''() => document.querySelector("input[name='cf-turnstile-response']")?.value.trim() || ""''')
            if len(token) > 20:
                print(f"  ✅ token 生成 (长度: {len(token)})")
                validated = True
                break
            await asyncio.sleep(1)

        if not validated:
            print("  ❌ token 未生成")
            await save_screenshot(page, "turnstile_failed", username)

        return validated
    except Exception as e:
        print(f"  ❌ Turnstile 异常: {str(e)}")
        await save_screenshot(page, "turnstile_error", username)
        return True  # 不卡死


async def login_with_playwright(username: str, password: str) -> tuple[bool, list[str]]:
    print(f"\n🔐 处理账号: {username}")
    screenshots = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--window-size=1920,1080",
                "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ]
        )
        context = await browser.new_context(viewport={"width": 1920, "height": 1080})
        page = await context.new_page()
        await stealth_async(page)
        page.set_default_timeout(60000)

        try:
            # 优先 state
            if await try_load_state_and_check_login(context, page, username):
                screenshots.append(await save_screenshot(page, "state_logged_in", username))
                await browser.close()
                return True, screenshots

            # 完整登录
            print("  🔄 开始完整登录...")
            await page.goto("https://searcade.com/", wait_until="networkidle")
            screenshots.append(await save_screenshot(page, "01_home", username))

            if await is_already_logged_in(page):
                print("  🎉 首页已登录，保存 state")
                await context.storage_state(path=str(AUTH_STATE_FILE))
                await browser.close()
                return True, screenshots

            # 尝试登录按钮
            login_selectors = [
                'a:has-text("Login")', 'a:has-text("Sign in")', 'a:has-text("Log in")',
                'button:has-text("Login")', 'button:has-text("Sign in")',
                'a[href*="/login"]', 'a[href*="/signin"]', 'a[href*="/auth/login"]',
                '[class*="login-btn"]', '[id*="login"]', '[aria-label*="Log in"]'
            ]

            login_clicked = False
            for sel in login_selectors:
                try:
                    element = page.locator(sel).first
                    if await element.is_visible(timeout=10000):
                        print(f"  ✓ 匹配到登录入口: {sel}")
                        await element.click()
                        login_clicked = True
                        await asyncio.sleep(4)
                        break
                except:
                    continue

            if not login_clicked:
                print("  ⚠️ 未找到按钮，尝试直接访问登录页...")
                await page.goto("https://searcade.userveria.com/login", wait_until="networkidle")
                await asyncio.sleep(4)

            await handle_turnstile(page, username)
            screenshots.append(await save_screenshot(page, "02_login_page", username))

            # 填写用户名
            print("  📝 填写用户名...")
            username_locator = page.locator('input[name="username"], input[name="email"], input[type="text"]')
            await username_locator.wait_for(state="visible", timeout=45000)
            await username_locator.fill(username)

            # 填写密码
            print("  🔐 填写密码...")
            password_locator = page.locator('input[name="password"], input[type="password"]')
            await password_locator.wait_for(state="visible", timeout=45000)
            await password_locator.fill(password)

            screenshots.append(await save_screenshot(page, "03_filled_form", username))

            # 点击登录
            button_selectors = [
                'button:has-text("Login")', 'button:has-text("Sign in")',
                'button[type="submit"]',
            ]
            button_clicked = False
            for selector in button_selectors:
                try:
                    button = page.locator(selector).first
                    if await button.is_visible():
                        await button.click()
                        button_clicked = True
                        break
                except:
                    continue

            if not button_clicked:
                print("  ⚠️ 未找到登录按钮，尝试回车...")
                await password_locator.press("Enter")

            await asyncio.sleep(5)
            await handle_turnstile(page, username)

            # 检查登录成功
            current_url = page.url
            content = await page.content()
            success = "login" not in current_url.lower() and any(keyword in content.lower() for keyword in ["logout", "profile", "dashboard"])

            screenshots.append(await save_screenshot(page, "04_final", username))

            if success:
                print(f"✅ 账号 {username} 登录成功")
                await context.storage_state(path=str(AUTH_STATE_FILE))
            else:
                print(f"❌ 账号 {username} 登录失败")

            await browser.close()
            return success, screenshots

        except Exception as e:
            print(f"  ❌ 错误: {str(e)}")
            screenshots.append(await save_screenshot(page, "error", username))
            await browser.close()
            return False, screenshots


def send_telegram_notification(title, message, success_count, fail_count):
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if not bot_token or not chat_id:
        print("⚠️  未配置 Telegram 通知信息")
        return
    
    try:
        status = "✅ 成功" if fail_count == 0 else "⚠️ 部分失败"
        text = f"""
{title}

{message}

📊 统计信息:
- 成功: {success_count}
- 失败: {fail_count}
- 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

状态: {status}
"""
        
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        data = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML"
        }
        
        response = requests.post(url, data=data, timeout=10)
        if response.status_code == 200:
            print("✅ Telegram 通知已发送")
        else:
            print(f"❌ Telegram 通知发送失败: {response.status_code}")
    except Exception as e:
        print(f"❌ 发送 Telegram 通知出错: {str(e)}")

async def main():
    print(f"🚀 Searcade Playwright 登录脚本 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    accounts = await load_accounts()
    
    if not accounts:
        print("❌ 未找到任何账号")
        send_telegram_notification(
            "Searcade 保号登录",
            "❌ 未找到任何账号配置",
            0, 0
        )
        return
    
    print(f"📊 共找到 {len(accounts)} 个账号\n")
    
    success_count = 0
    fail_count = 0
    results = []
    
    for i, account in enumerate(accounts, 1):
        username = account.get("username")
        password = account.get("password")
        
        if not username or not password:
            print(f"⚠️  账号 {i} 信息不完整")
            fail_count += 1
            results.append(f"❌ 账号 {i}: 信息不完整")
            continue
        
        success, shots = await login_with_playwright(username, password)
        
        if success:
            success_count += 1
            results.append(f"✅ {username}: 登录成功")
        else:
            fail_count += 1
            results.append(f"❌ {username}: 登录失败")
        
        if i < len(accounts):
            await asyncio.sleep(2)
    
    print(f"\n{'='*50}")
    print(f"📈 成功: {success_count}, 失败: {fail_count}")
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}")
    
    # 发送 Telegram 通知
    message = "\n".join(results)
    send_telegram_notification(
        "🔐 Searcade 保号登录结果",
        message,
        success_count,
        fail_count
    )
    
    if fail_count > 0 and success_count == 0:
        exit(1)

if __name__ == "__main__":
    asyncio.run(main())
