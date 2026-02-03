import asyncio
import json
import os
from datetime import datetime
import requests
from pathlib import Path
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from playwright_stealth import stealth_async  # 需固定 playwright-stealth==1.0.6

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

async def handle_turnstile(page, username: str) -> bool:
    """参考 Katabump 处理 CF Turnstile：模拟偏移点击 + 轮询 token"""
    try:
        # 检测 Turnstile 容器
        turnstile_container = await page.query_selector(".cf-turnstile") or await page.query_selector("div#turnstile-wrapper")
        if not turnstile_container:
            print("  ✓ 无 Turnstile 检测到，跳过")
            return True

        print("  ⚠️ 检测到 Cloudflare Turnstile，正在模拟人类交互...")
        # 获取容器位置
        bounding_box = await turnstile_container.bounding_box()
        if not bounding_box:
            print("  ❌ 无法获取 Turnstile 位置")
            return False

        # 模拟偏移点击（参考 Katabump 的 -120 偏移，调整为 Playwright mouse）
        offset_x = -120 + random.uniform(-20, 20)  # 随机微调模拟人类
        offset_y = 0 + random.uniform(-10, 10)
        click_x = bounding_box['x'] + offset_x
        click_y = bounding_box['y'] + offset_y
        await page.mouse.move(click_x, click_y)
        await asyncio.sleep(random.uniform(0.5, 1.5))  # 人类犹豫
        await page.mouse.click(click_x, click_y)
        print(f"  🖱️ 执行偏移点击 (x={click_x:.0f}, y={click_y:.0f})")

        # 轮询检查 token (参考 Katabump 的 10 次循环)
        validated = False
        for _ in range(15):  # 延长到 15 次，约 15s
            token = await page.evaluate('''() => {
                const input = document.querySelector("input[name='cf-turnstile-response']");
                return input ? input.value : "";
            }''')
            if token and len(token) > 20:
                print(f"  ✅ Turnstile token 生成 (长度: {len(token)})")
                validated = True
                break
            await asyncio.sleep(1)  # 每秒检查

        if not validated:
            print("  ❌ Turnstile 未通过 (建议用住宅代理或 CAPTCHA solver)")
            await save_screenshot(page, "turnstile_failed", username)
            return False

        await asyncio.sleep(random.uniform(1, 3))  # 额外延迟
        return True

    except Exception as e:
        print(f"  ❌ Turnstile 处理失败: {str(e)}")
        return False

async def login_with_playwright(username: str, password: str) -> tuple[bool, list[str]]:
    """使用 Playwright 登录，返回 (成功与否, 截图路径列表)"""
    print(f"\n🔐 正在登录账号: {username}")
    screenshots = []

    try:
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
                page.set_default_timeout(60000)

                # 打开首页
                print("  🌐 打开主站点...")
                await page.goto("https://searcade.com/", wait_until="networkidle")
                screenshots.append(await save_screenshot(page, "01_home", username))

                # 处理可能的 Turnstile
                if not await handle_turnstile(page, username):
                    return False, screenshots

                # 后续登录流程（保持原逻辑，略微简化）
                print("  🔍 查找登录按钮...")
                login_button_selectors = [
                    'a:has-text("Login")', 'a:has-text("Sign in")',
                    'button:has-text("Login")', 'button:has-text("Sign in")',
                    '[class*="login"]', '[id*="login"]',
                ]
                login_button_found = False
                for selector in login_button_selectors:
                    try:
                        login_button = page.locator(selector).first
                        if await login_button.is_visible():
                            await login_button.click()
                            login_button_found = True
                            break
                    except:
                        continue

                if not login_button_found:
                    print("  ⚠️ 未找到登录按钮，尝试直接访问登录页面...")
                    await page.goto("https://searcade.userveria.com/login", wait_until="networkidle")

                # 处理登录页 Turnstile
                if not await handle_turnstile(page, username):
                    return False, screenshots

                screenshots.append(await save_screenshot(page, "02_login_page", username))

                # 填写用户名
                print("  📝 填写用户名...")
                username_selectors = [
                    'input[name="username"]', 'input[name="email"]',
                    'input[type="text"]', 'input[id*="username"]', 'input[id*="email"]',
                ]
                username_input = None
                for selector in username_selectors:
                    try:
                        username_input = page.locator(selector).first
                        if await username_input.is_visible():
                            break
                    except:
                        continue

                if username_input:
                    await username_input.fill(username)
                else:
                    print("  ❌ 找不到用户名输入框")
                    return False, screenshots

                # 填写密码
                print("  🔐 填写密码...")
                password_selectors = [
                    'input[name="password"]', 'input[type="password"]',
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

                if password_input:
                    await password_input.fill(password)
                else:
                    print("  ❌ 找不到密码输入框")
                    return False, screenshots

                screenshots.append(await save_screenshot(page, "03_filled_form", username))

                # 点击登录
                print("  🚀 点击登录按钮...")
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
                    await password_input.press("Enter")

                await asyncio.sleep(5)

                # 处理登录后可能的 Turnstile
                if not await handle_turnstile(page, username):
                    return False, screenshots

                # 检查登录成功
                current_url = page.url
                content = await page.content()
                success_checks = []
                if "login" not in current_url.lower():
                    success_checks.append(True)
                if any(keyword in content.lower() for keyword in ["logout", "profile", "dashboard", "account"]):
                    success_checks.append(True)

                screenshots.append(await save_screenshot(page, "04_final", username))

                success = len(success_checks) > 0
                print(f"  ✅ 账号 {username} 登录{'成功' if success else '失败'}（通过 {len(success_checks)} 个验证）")
                return success, screenshots

            except Exception as e:
                print(f"  ❌ 错误: {str(e)}")
                screenshots.append(await save_screenshot(page, "error", username))
                await browser.close()
                return False, screenshots

    except ImportError:
        print("❌ Playwright 未安装")
        return False, screenshots
    except Exception as e:
        print(f"❌ 登录出错: {str(e)}")
        return False, screenshots

def send_telegram_notification(title, message, success_count, fail_count):
    """发送 Telegram 通知"""
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
        
        if await login_with_playwright(username, password):
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
