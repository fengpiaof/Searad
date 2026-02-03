import asyncio
import json
import os
from datetime import datetime
import requests
from pathlib import Path

# 截图保存目录
SCREENSHOT_DIR = Path("screenshots")
SCREENSHOT_DIR.mkdir(exist_ok=True)

async def load_accounts():
    """从环境变量加载账号列表"""
    try:
        accounts_json = os.getenv("SEARCADE_ACCOUNTS", "[]")
        print(f"DEBUG: SEARCADE_ACCOUNTS 长度: {len(accounts_json)}")
        accounts = json.loads(accounts_json)
        print(f"加载账号成功: {len(accounts)} 个")
        return accounts
    except json.JSONDecodeError as e:
        print(f"❌ 无法解析账号JSON: {e}")
        print(f"原始内容: {accounts_json[:200]}...")  # 截断避免泄露
        return []


async def save_screenshot(page, name_prefix: str, username: str) -> str:
    """保存截图并返回路径"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_username = username.replace("@", "_").replace(".", "_")
    path = SCREENSHOT_DIR / f"{name_prefix}_{safe_username}_{timestamp}.png"
    await page.screenshot(path=str(path), full_page=True)
    print(f"📸 保存截图: {path}")
    return str(path)


async def login_with_playwright(username: str, password: str) -> tuple[bool, list[str]]:
    """使用 Playwright 登录，返回 (成功与否, 截图路径列表)"""
    print(f"\n🔐 正在登录账号: {username}")
    screenshots = []

    try:
        from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-setuid-sandbox"])
            context = await browser.new_context(viewport={"width": 1280, "height": 800})
            page = await context.new_page()

            try:
                page.set_default_timeout(60000)
                page.set_default_navigation_timeout(60000)

                # 1. 打开首页
                print("  🌐 打开主站点...")
                await page.goto("https://searcade.com/", wait_until="networkidle", timeout=45000)
                screenshots.append(await save_screenshot(page, "01_home", username))

                # 2. 尝试找到并点击登录按钮
                print("  🔍 查找登录按钮...")
                login_selectors = [
                    'a:has-text("Login")', 'a:has-text("Sign in")',
                    'button:has-text("Login")', 'button:has-text("Sign in")',
                    '[href*="/login"]', '[class*="login"]', '[id*="login"]',
                ]

                login_clicked = False
                for sel in login_selectors:
                    try:
                        btn = page.locator(sel).first
                        if await btn.is_visible(timeout=5000):
                            print(f"  ✓ 找到并点击: {sel}")
                            await btn.click()
                            login_clicked = True
                            await asyncio.sleep(1.5)
                            break
                    except:
                        pass

                if not login_clicked:
                    print("  ⚠️ 未找到登录按钮，尝试直接访问可能的登录页...")
                    # 根据搜索结果，searcade.com 可能没有 /login，尝试 dashboard 或其他
                    # 但实际站点似乎登录在其他地方，这里保持原样或注释
                    await page.goto("https://searcade.com/en", wait_until="networkidle")

                screenshots.append(await save_screenshot(page, "02_login_page", username))

                # 3. 填写用户名
                print("  📝 填写用户名...")
                username_selectors = [
                    'input[name="username"]', 'input[name="email"]',
                    'input[type="text"]', 'input[type="email"]',
                    '#username', '#email', '[placeholder*="Email"]', '[placeholder*="Username"]'
                ]
                username_filled = False
                for sel in username_selectors:
                    try:
                        input_el = page.locator(sel).first
                        if await input_el.is_visible(timeout=8000):
                            await input_el.fill(username)
                            username_filled = True
                            print(f"  ✓ 用户名填写成功 ({sel})")
                            break
                    except:
                        pass

                if not username_filled:
                    print("  ❌ 未找到用户名输入框")
                    screenshots.append(await save_screenshot(page, "error_no_username", username))
                    return False, screenshots

                # 4. 填写密码
                print("  🔐 填写密码...")
                password_selectors = [
                    'input[name="password"]', 'input[type="password"]',
                    '#password', '[placeholder*="Password"]'
                ]
                password_filled = False
                for sel in password_selectors:
                    try:
                        input_el = page.locator(sel).first
                        if await input_el.is_visible(timeout=8000):
                            await input_el.fill(password)
                            password_filled = True
                            print(f"  ✓ 密码填写成功 ({sel})")
                            break
                    except:
                        pass

                if not password_filled:
                    print("  ❌ 未找到密码输入框")
                    screenshots.append(await save_screenshot(page, "error_no_password", username))
                    return False, screenshots

                screenshots.append(await save_screenshot(page, "03_filled_form", username))

                # 5. 点击登录
                print("  🚀 点击登录...")
                submit_selectors = [
                    'button:has-text("Login")', 'button:has-text("Sign in")',
                    'button[type="submit"]', 'button >> text="登录"',
                    'input[type="submit"]'
                ]
                submitted = False
                for sel in submit_selectors:
                    try:
                        btn = page.locator(sel).first
                        if await btn.is_enabled(timeout=5000) and await btn.is_visible():
                            await btn.click()
                            submitted = True
                            print(f"  ✓ 已点击提交 ({sel})")
                            break
                    except:
                        pass

                if not submitted:
                    print("  ⚠️ 未找到提交按钮，尝试回车...")
                    await page.keyboard.press("Enter")

                await asyncio.sleep(4)  # 等待跳转

                # 6. 判断是否成功
                current_url = page.url
                title = await page.title()
                content_lower = (await page.content()).lower()

                success_indicators = 0
                if "login" not in current_url.lower() and "dashboard" in current_url.lower() or "account" in current_url.lower():
                    success_indicators += 1
                if any(kw in title.lower() for kw in ["dashboard", "panel", "account", "profile"]):
                    success_indicators += 1
                if any(kw in content_lower for kw in ["logout", "sign out", "profile", "servers", "minecraft"]):
                    success_indicators += 1
                if any(kw in content_lower for kw in ["invalid", "failed", "incorrect", "error"]):
                    success_indicators -= 1

                final_screenshot = await save_screenshot(page, "04_final", username)
                screenshots.append(final_screenshot)

                success = success_indicators >= 2
                status = "成功" if success else "失败"
                print(f"  判断结果: {status} (指标: {success_indicators}) | URL: {current_url} | Title: {title}")

                await browser.close()
                return success, screenshots

            except Exception as e:
                print(f"  ❌ 登录过程中异常: {str(e)}")
                err_shot = await save_screenshot(page, "error_exception", username)
                screenshots.append(err_shot)
                await browser.close()
                return False, screenshots

    except Exception as e:
        print(f"❌ Playwright 初始化失败: {str(e)}")
        return False, screenshots


def send_telegram_notification(title: str, message: str, success_count: int, fail_count: int, all_screenshots: list[str]):
    """发送 Telegram 通知 + 截图"""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        print("⚠️ 未配置 Telegram，跳过通知")
        return

    status = "✅ 全成功" if fail_count == 0 else "⚠️ 有失败" if success_count > 0 else "❌ 全失败"
    text = f"""
<b>{title}</b>

{message}

📊 统计:
成功: {success_count} | 失败: {fail_count}
时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC+1

状态: {status}
"""

    try:
        # 先发文字通知
        requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            data={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=15
        )

        # 再发截图（每张单独发，避免一次太多）
        for idx, shot_path in enumerate(all_screenshots[:8], 1):  # 限制最多8张
            if not os.path.exists(shot_path):
                continue
            caption = f"账号截图 {idx}/{len(all_screenshots)} - {status}"
            with open(shot_path, "rb") as f:
                resp = requests.post(
                    f"https://api.telegram.org/bot{bot_token}/sendPhoto",
                    data={"chat_id": chat_id, "caption": caption},
                    files={"photo": f},
                    timeout=30
                )
            if resp.status_code != 200:
                print(f"发送截图失败: {resp.text}")

        print("✅ Telegram 通知 & 截图已发送")
    except Exception as e:
        print(f"❌ Telegram 发送失败: {str(e)}")


async def main():
    start_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"🚀 Searcade 保号登录脚本启动 - {start_time}\n")

    accounts = await load_accounts()

    if not accounts:
        print("❌ 未找到任何账号")
        send_telegram_notification("Searcade 保号登录", "❌ 未找到任何账号配置", 0, 0, [])
        return

    print(f"📊 共 {len(accounts)} 个账号待处理\n")

    success_count = 0
    fail_count = 0
    results = []
    all_screenshots = []

    for i, acc in enumerate(accounts, 1):
        username = acc.get("username") or acc.get("email")
        password = acc.get("password") or acc.get("pass")

        if not username or not password:
            print(f"⚠️ 账号 {i} 信息不完整")
            fail_count += 1
            results.append(f"❌ 账号 {i}: 信息不完整")
            continue

        success, screenshots = await login_with_playwright(username, password)
        all_screenshots.extend(screenshots)

        if success:
            success_count += 1
            results.append(f"✅ {username}: 登录成功")
        else:
            fail_count += 1
            results.append(f"❌ {username}: 登录失败")

        if i < len(accounts):
            await asyncio.sleep(3)  # 账号间间隔

    summary = f"\n{'='*50}\n成功: {success_count} | 失败: {fail_count}\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n{'='*50}"
    print(summary)

    message = "\n".join(results)
    send_telegram_notification("🔐 Searcade 保号登录结果", message, success_count, fail_count, all_screenshots)

    if fail_count > 0 and success_count == 0:
        exit(1)


if __name__ == "__main__":
    asyncio.run(main())
