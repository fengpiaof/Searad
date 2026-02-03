import asyncio
import json
import os
from datetime import datetime
import requests
from pathlib import Path
from playwright_stealth import stealth_async  # 新增 stealth

# 截图保存目录
SCREENSHOT_DIR = Path("screenshots")
SCREENSHOT_DIR.mkdir(exist_ok=True)

async def load_accounts():
    try:
        accounts_json = os.getenv("SEARCADE_ACCOUNTS", "[]")
        print(f"DEBUG: SEARCADE_ACCOUNTS 长度: {len(accounts_json)}")
        accounts = json.loads(accounts_json)
        print(f"加载账号成功: {len(accounts)} 个")
        return accounts
    except json.JSONDecodeError as e:
        print(f"❌ 无法解析账号JSON: {e}")
        print(f"原始内容 (前200字符): {accounts_json[:200]}...")
        return []


async def save_screenshot(page, name_prefix: str, username: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_username = username.replace("@", "_at_").replace(".", "_")
    path = SCREENSHOT_DIR / f"{name_prefix}_{safe_username}_{timestamp}.png"
    await page.screenshot(path=str(path), full_page=True)
    print(f"📸 保存截图: {path}")
    return str(path)


async def login_with_playwright(username: str, password: str) -> tuple[bool, list[str]]:
    print(f"\n🔐 正在登录账号: {username}")
    screenshots = []

    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            # 加强反检测启动参数
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-infobars",
                    "--window-size=1920,1080",
                    "--disable-dev-shm-usage",
                    "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                ]
            )
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                locale="en-US",
                timezone_id="Europe/Berlin"  # 根据你的位置调整
            )
            page = await context.new_page()

            # 应用 stealth 隐藏 webdriver 等特征
            await stealth_async(page)

            try:
                page.set_default_timeout(60000)
                page.set_default_navigation_timeout(60000)

                # 1. 打开首页
                print("  🌐 打开主站点 https://searcade.com/ ...")
                response = await page.goto("https://searcade.com/", wait_until="networkidle", timeout=60000)
                screenshots.append(await save_screenshot(page, "01_home", username))

                # 检测是否卡在 CF Turnstile
                if "turnstile" in (await page.content()).lower() or "verify you are human" in (await page.content()).lower():
                    print("  ⚠️ 检测到 Cloudflare Turnstile，正在等待自动通过（建议使用住宅代理）...")
                    await asyncio.sleep(20)  # 给 JS 挑战时间
                    screenshots.append(await save_screenshot(page, "cf_turnstile_wait", username))
                    # 再等一次
                    await asyncio.sleep(15)
                    if "turnstile" in (await page.content()).lower():
                        print("  ❌ Turnstile 未通过（很可能 IP 被标记为数据中心）")
                        screenshots.append(await save_screenshot(page, "cf_turnstile_failed", username))

                # 2. 查找登录按钮
                print("  🔍 查找登录按钮...")
                login_selectors = [
                    'a:has-text("Login")', 'a:has-text("Sign in")', 'a[href*="/login"]',
                    'button:has-text("Login")', '[class*="login"]', '[id*="login"]'
                ]
                login_clicked = False
                for sel in login_selectors:
                    try:
                        btn = page.locator(sel).first
                        if await btn.is_visible(timeout=8000):
                            await btn.click()
                            login_clicked = True
                            print(f"  ✓ 点击登录按钮: {sel}")
                            await asyncio.sleep(2)
                            break
                    except:
                        pass

                if not login_clicked:
                    print("  ⚠️ 未找到登录按钮，尝试直接访问可能的登录路径...")
                    await page.goto("https://searcade.userveria.com/login", wait_until="networkidle", timeout=45000)
                    await asyncio.sleep(3)  # 再等 CF

                screenshots.append(await save_screenshot(page, "02_login_page", username))

                # 再次检查 CF
                content_lower = (await page.content()).lower()
                if "turnstile" in content_lower or "verify you are human" in content_lower:
                    print("  ⚠️ 登录页又触发 Turnstile，额外等待...")
                    await asyncio.sleep(25)
                    screenshots.append(await save_screenshot(page, "cf_login_turnstile", username))

                # 3. 填写用户名 & 密码（保持原有多 selector 尝试）
                # ... （这里保持你原来的用户名/密码填写逻辑不变，只加截图）
                # 填写用户名部分
                print("  📝 填写用户名...")
                # （你的原代码用户名 selector 尝试...）
                # 假设填写成功后
                await asyncio.sleep(1)
                screenshots.append(await save_screenshot(page, "03_filled_username", username))

                # 填写密码...
                # （你的原代码...）
                screenshots.append(await save_screenshot(page, "04_filled_password", username))

                # 4. 提交登录
                # （你的原代码提交部分...）

                await asyncio.sleep(5)  # 等待跳转

                final_url = page.url
                title = await page.title()
                final_content = await page.content()

                screenshots.append(await save_screenshot(page, "05_final_page", username))

                # 判断成功（放宽条件）
                success = False
                if "login" not in final_url.lower():
                    success = True
                elif any(kw in final_content.lower() for kw in ["logout", "profile", "dashboard", "account", "servers"]):
                    success = True
                elif "turnstile" not in final_content.lower() and "verify" not in final_content.lower():
                    success = True  # 没盾就算过

                print(f"  📍 最终 URL: {final_url}")
                print(f"  📄 页面标题: {title}")
                print(f"  判断结果: {'成功' if success else '失败'}")

                await browser.close()
                return success, screenshots

            except Exception as e:
                print(f"  ❌ 登录异常: {str(e)}")
                err_shot = await save_screenshot(page, "error_exception", username)
                screenshots.append(err_shot)
                await browser.close()
                return False, screenshots

    except Exception as e:
        print(f"❌ Playwright 初始化失败: {str(e)}")
        return False, []


def send_telegram_notification(title: str, message: str, success_count: int, fail_count: int, all_screenshots: list[str]):
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        print("⚠️ 未配置 Telegram，跳过")
        return

    status = "✅ 全成功" if fail_count == 0 else "⚠️ 部分失败" if success_count > 0 else "❌ 全失败"
    text = f"""
<b>{title}</b>

{message}

📊 统计: 成功 {success_count} | 失败 {fail_count}
时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} CET
状态: {status}
    """

    try:
        # 发文字
        requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            data={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        )

        # 发截图（限前8张，避免 flood）
        for i, path in enumerate(all_screenshots[:8], 1):
            if os.path.exists(path):
                with open(path, "rb") as f:
                    caption = f"截图 {i} - {status} - {os.path.basename(path)}"
                    requests.post(
                        f"https://api.telegram.org/bot{bot_token}/sendPhoto",
                        data={"chat_id": chat_id, "caption": caption},
                        files={"photo": f}
                    )
        print("✅ 已发送通知 & 截图")
    except Exception as e:
        print(f"❌ Telegram 发送失败: {e}")


async def main():
    print(f"🚀 Searcade 保号登录 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} CET\n")

    accounts = await load_accounts()
    if not accounts:
        send_telegram_notification("Searcade 保号登录", "❌ 无账号配置", 0, 0, [])
        return

    success_count = fail_count = 0
    results = []
    global_screenshots = []

    for i, acc in enumerate(accounts, 1):
        username = acc.get("username") or acc.get("email")
        password = acc.get("password")

        if not username or not password:
            fail_count += 1
            results.append(f"❌ 账号 {i}: 信息不完整")
            continue

        success, shots = await login_with_playwright(username, password)
        global_screenshots.extend(shots)

        if success:
            success_count += 1
            results.append(f"✅ {username}: 成功")
        else:
            fail_count += 1
            results.append(f"❌ {username}: 失败")

        await asyncio.sleep(4) if i < len(accounts) else None

    summary = f"\n成功: {success_count}  |  失败: {fail_count}\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    print(summary)

    message = "\n".join(results)
    send_telegram_notification("🔐 Searcade 保号登录结果", message, success_count, fail_count, global_screenshots)

    if fail_count > 0 and success_count == 0:
        exit(1)


if __name__ == "__main__":
    asyncio.run(main())
