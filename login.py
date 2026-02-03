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

# 认证状态文件（cookies + storage）
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


async def try_load_state_and_check_login(context, page, username: str) -> bool:
    """尝试加载已保存的 storage state，检查是否仍有效"""
    if not AUTH_STATE_FILE.exists():
        print("  ⚠️ 无已保存的 auth state 文件，需要完整登录")
        return False

    try:
        print(f"  🔑 尝试加载 auth state: {AUTH_STATE_FILE}")
        await context.add_init_script(script="""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        """)
        await context.storage_state(path=str(AUTH_STATE_FILE))  # 加载整个 state

        print("  🔍 检查登录状态（访问首页）...")
        await page.goto("https://searcade.com/", wait_until="networkidle", timeout=45000)

        content_lower = (await page.content()).lower()
        current_url = page.url.lower()

        # 判断是否已登录（根据常见登录后特征，可根据实际站点调整）
        is_logged_in = (
            "login" not in current_url and
            any(kw in content_lower for kw in ["logout", "sign out", "profile", "dashboard", "account", "settings"])
        )

        if is_logged_in:
            print(f"  ✅ Cookies / state 有效，已处于登录状态 ({username})")
            await save_screenshot(page, "logged_in_via_state", username)
            return True
        else:
            print("  ⚠️ state 已失效，需要重新登录")
            await save_screenshot(page, "state_invalid", username)
            return False

    except Exception as e:
        print(f"  ❌ 加载/检查 state 失败: {str(e)}")
        return False


async def handle_turnstile(page, username: str) -> bool:
    """模拟人类交互处理 Cloudflare Turnstile"""
    try:
        turnstile = await page.query_selector(".cf-turnstile, div#turnstile-wrapper, iframe[title*='challenge']")
        if not turnstile:
            return True

        print("  ⚠️ 检测到 Turnstile，正在模拟交互...")
        box = await turnstile.bounding_box()
        if not box:
            return False

        offset_x = box["width"] * random.uniform(0.2, 0.4)
        offset_y = box["height"] * random.uniform(0.4, 0.6)
        click_x = box["x"] + offset_x
        click_y = box["y"] + offset_y

        await page.mouse.move(click_x, click_y, steps=10)
        await asyncio.sleep(random.uniform(0.6, 1.8))
        await page.mouse.click(click_x, click_y)

        # 轮询 token
        for _ in range(20):
            token = await page.evaluate('''() => document.querySelector("input[name='cf-turnstile-response']")?.value || ""''')
            if token and len(token) > 20:
                print("  ✅ Turnstile 通过")
                return True
            await asyncio.sleep(1)

        print("  ❌ Turnstile 未通过")
        await save_screenshot(page, "turnstile_failed", username)
        return False
    except:
        return True  # 异常时假设已过（避免卡死）


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

        try:
            # 优先尝试加载已有 state
            if await try_load_state_and_check_login(context, page, username):
                screenshots.append(await save_screenshot(page, "via_state_success", username))
                await browser.close()
                return True, screenshots

            # state 失效 → 完整登录
            print("  🔄 state 失效，开始完整登录流程...")

            await page.goto("https://searcade.com/", wait_until="networkidle")
            screenshots.append(await save_screenshot(page, "01_home", username))

            if not await handle_turnstile(page, username):
                return False, screenshots

            # 查找并点击登录按钮（你的原逻辑）
            login_selectors = [
                'a:has-text("Login")', 'a:has-text("Sign in")',
                'button:has-text("Login")', '[href*="/login"]'
            ]
            for sel in login_selectors:
                try:
                    btn = page.locator(sel).first
                    if await btn.is_visible(timeout=8000):
                        await btn.click()
                        break
                except:
                    pass
            else:
                await page.goto("https://searcade.userveria.com/login", wait_until="networkidle")

            if not await handle_turnstile(page, username):
                return False, screenshots

            screenshots.append(await save_screenshot(page, "02_login_page", username))

            # 填写表单（简化版，可根据实际调整 selector）
            await page.fill('input[name="username"], input[name="email"], input[type="text"]', username)
            await page.fill('input[name="password"], input[type="password"]', password)
            await page.click('button[type="submit"], button:has-text("Login"), button:has-text("Sign in")')

            await asyncio.sleep(5)

            if not await handle_turnstile(page, username):
                return False, screenshots

            # 判断是否登录成功
            current_url = page.url.lower()
            content = await page.content()
            success = "login" not in current_url and any(kw in content.lower() for kw in ["logout", "profile", "dashboard"])

            screenshots.append(await save_screenshot(page, "04_final", username))

            if success:
                print("  🎉 登录成功，正在保存新的 auth state...")
                await context.storage_state(path=str(AUTH_STATE_FILE))
                print(f"  💾 已保存到 {AUTH_STATE_FILE}")
            else:
                print("  ❌ 登录失败")

            await browser.close()
            return success, screenshots

        except Exception as e:
            print(f"  ❌ 异常: {str(e)}")
            screenshots.append(await save_screenshot(page, "error", username))
            await browser.close()
            return False, screenshots


def send_telegram_notification(title, message, success_count, fail_count):
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        print("⚠️ 未配置 Telegram")
        return

    status = "✅ 全成功" if fail_count == 0 else "⚠️ 部分失败" if success_count > 0 else "❌ 全失败"
    text = f"""
<b>{title}</b>

{message}

📊 成功: {success_count} | 失败: {fail_count}
时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} CET
状态: {status}
"""
    try:
        requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            data={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=15
        )
        print("✅ Telegram 通知已发送")
    except Exception as e:
        print(f"❌ Telegram 发送失败: {e}")


async def main():
    print(f"🚀 Searcade 保号登录 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} CET\n")

    accounts = await load_accounts()
    if not accounts:
        send_telegram_notification("Searcade 保号登录", "❌ 无账号配置", 0, 0)
        return

    success_count = fail_count = 0
    results = []
    all_screenshots = []

    for i, acc in enumerate(accounts, 1):
        username = acc.get("username") or acc.get("email")
        password = acc.get("password")

        if not username or not password:
            fail_count += 1
            results.append(f"❌ 账号 {i}: 信息不完整")
            continue

        success, shots = await login_with_playwright(username, password)
        all_screenshots.extend(shots)

        if success:
            success_count += 1
            results.append(f"✅ {username}: 成功")
        else:
            fail_count += 1
            results.append(f"❌ {username}: 失败")

        if i < len(accounts):
            await asyncio.sleep(random.uniform(3, 8))

    summary = f"\n成功: {success_count}  |  失败: {fail_count}"
    print(summary)

    message = "\n".join(results)
    send_telegram_notification("🔐 Searcade 保号登录结果", message, success_count, fail_count)


if __name__ == "__main__":
    asyncio.run(main())
