#!/usr/bin/env python3

import os
import time
import logging
import random
import re
import requests
import undetected_chromedriver as uc
from datetime import datetime, timezone, timedelta
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import TimeoutException, WebDriverException
from dotenv import load_dotenv

load_dotenv()

# ===================== 配置日志 =====================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ===================== 全局配置 =====================
HEADLESS = os.getenv('HEADLESS', 'true').lower() == 'true'
PAUSE_BETWEEN_ACCOUNTS_MS = int(os.getenv('PAUSE_BETWEEN_ACCOUNTS_MS', '10000'))
TELEGRAM_BOT_TOKEN = os.getenv('BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.getenv('CHAT_ID', '')
ACCOUNTS_ENV = os.getenv('ACCOUNTS', '')
PROXY_SERVER = os.getenv('HTTP_PROXY', '')

# ===================== 通知过滤（不通知的失败原因） =====================
# 当续期失败的提示包含以下内容时，仅记录日志，不发 Telegram 通知（也不计入失败汇总）
SKIP_RENEW_NOTICE_PATTERNS = [
    "You can't renew your server yet",
    "You will be able to as of",
]

# ===================== 工具函数 =====================
def should_skip_renew_notice(msg: str) -> bool:
    if not msg:
        return False
    m = msg.strip()
    return any(p in m for p in SKIP_RENEW_NOTICE_PATTERNS)

def rand_int(min_val, max_val):
    return random.randint(min_val, max_val)

def sleep(ms):
    time.sleep(ms / 1000)

def human_delay():
    delay = 7000 + random.random() * 5000
    sleep(delay)

def human_type(driver, selector_type, selector_value, text):
    try:
        element = WebDriverWait(driver, 15).until(EC.visibility_of_element_located((selector_type, selector_value)))
        element.clear()
        for char in text:
            element.send_keys(char)
            sleep(rand_int(50, 150))
        return True
    except Exception as e:
        logger.warning(f"打字失败: {e}")
        return False

# ===================== Telegram 通知 =====================
def send_telegram(message, screenshot_path=None):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    tz_offset = timezone(timedelta(hours=8))
    time_str = datetime.now(tz_offset).strftime("%Y-%m-%d %H:%M:%S") + " HKT"
    full_message = f"🎉 Katabump 续期通知\n\n续期时间：{time_str}\n\n{message}"
    try:
        if screenshot_path and os.path.exists(screenshot_path):
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
            with open(screenshot_path, 'rb') as photo:
                requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "caption": full_message}, files={'photo': photo}, timeout=20)
        else:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": full_message}, timeout=10)
        logger.info("✅ Telegram 通知发送成功")
    except Exception as e:
        logger.warning(f"⚠️ Telegram 发送失败: {e}")

# ===================== Katabump 核心续期类 =====================
class KatabumpAutoRenew:
    def __init__(self, user, password):
        self.user = user
        self.password = password
        self.driver = None
        self.screenshot_path = None
        self.masked_user = self.mask_email()

    def mask_email(self):
        try:
            if "@" in self.user:
                prefix, domain = self.user.split('@')
                if len(prefix) <= 2:
                    return f"{prefix[0]}***@{domain}"
                return f"{prefix[0]}***{prefix[-1]}@{domain}"
            return f"{self.user[0]}***{self.user[-1]}" if len(self.user) > 2 else self.user
        except:
            return "UnknownUser"

    def setup_driver(self):
        chrome_options = Options()
        if HEADLESS: chrome_options.add_argument('--headless')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        if PROXY_SERVER:
            chrome_options.add_argument(f'--proxy-server={PROXY_SERVER}')
        v_env = os.getenv('CHROME_VERSION', '')
        v_main = int(v_env) if v_env.isdigit() else None
        logger.info(f"🛠️ 驱动初始化 - 指定大版本: {v_main or '自动探测'}")
        try:
            self.driver = uc.Chrome(options=chrome_options, headless=HEADLESS, version_main=v_main, use_subprocess=True)
        except Exception as e:
            logger.warning(f"⚠️ 强制版本启动失败，尝试降级启动: {e}")
            self.driver = uc.Chrome(options=chrome_options, headless=HEADLESS)
        self.driver.set_window_size(1280, 720)

    def process(self):
        logger.info(f"🚀 开始登录账号: {self.masked_user}")
        self.driver.get("https://dashboard.katabump.com/auth/login")
        sleep(5000 + random.random() * 2000)

        # --- 第一步：输入用户名 ---
        logger.info(f"📝 {self.masked_user} - 填写用户名/邮箱...")
        if not human_type(self.driver, By.CSS_SELECTOR, "input#email", self.user):
            raise Exception("未找到用户名输入框")
        sleep(2000 + random.random() * 1000)

        # --- 第二步：输入密码 ---
        logger.info(f"🔒 {self.masked_user} - 填写密码...")
        if not human_type(self.driver, By.CSS_SELECTOR, "input#password", self.password):
            raise Exception("未找到密码输入框")
        sleep(2000 + random.random() * 1000)

        logger.info(f"📤 {self.masked_user} - 点击“Login”提交登录...")
        self.driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]').click()
        human_delay()

        # --- 第三步： Manage Server ---
        logger.info(f"🎯 {self.masked_user} - 进入服务器详情页...")
        manage_btn = WebDriverWait(self.driver, 30).until(
            EC.element_to_be_clickable((By.XPATH, "//a[contains(text(), 'See')]"))
        )
        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", manage_btn)
        sleep(1000 + random.random() * 1000)
        self.driver.execute_script("arguments[0].click();", manage_btn)
        human_delay()

        # --- 第四步： Renew Server ---
        logger.info(f"🔄 {self.masked_user} - 准备续期流程...")
        initial_expiry = ""
        try:
            initial_expiry_element = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.XPATH, "//div[contains(text(), 'Expiry')]/following-sibling::div"))
            )
            initial_expiry = initial_expiry_element.text.strip()
            logger.info(f"⌛ {self.masked_user} - 当前到期时间: {initial_expiry}")
        except Exception:
            logger.warning(f"⚠️ {self.masked_user} - 无法读取初始时间")

        try:
            renew_trigger = WebDriverWait(self.driver, 15).until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Renew')]"))
            )
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", renew_trigger)
            self.driver.execute_script("arguments[0].click();", renew_trigger)
            logger.info(f"📑 {self.masked_user} - 已打开 Renew 弹窗")
        except Exception as e:
            raise Exception(f"无法打开弹窗: {e}")
        sleep(2000 + random.random() * 1000)

        # 3. Cloudflare 验证
        try:
            container = self.driver.find_element(By.CLASS_NAME, "cf-turnstile")
            actions = ActionChains(self.driver)
            actions.move_to_element_with_offset(container, -120, 0).click().perform()
            logger.info(f"🖱️ {self.masked_user} - 执行偏移点击...")
            # ---轮询检查 Token ---
            validated = False
            logger.info(f"⏳ {self.masked_user} - 等待验证通过...")
            for _ in range(10):
                # 检查隐藏的 response 输入框是否有值
                token = self.driver.execute_script(
                    'return document.querySelector("input[name=\'cf-turnstile-response\']").value;'
                )
                if token and len(token) > 20:
                    logger.info(f"✅ {self.masked_user} - 验证已通过 (Token Ready)")
                    sleep(1000 + random.random() * 1000)                  
                    validated = True
                    break
                sleep(1000)
            
            if not validated:
                logger.warning(f"⚠️ {self.masked_user} - 验证未能在 10s 内完成，尝试继续...")

        except Exception as e:
            logger.error(f"❌ 验证框交互失败: {e}")

        # 4. 最终 Renew 按钮
        try:
            confirm_btn_xpath = "//div[@id='renew-modal']//button[@type='submit' and contains(text(), 'Renew')]"
            confirm_btn = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, confirm_btn_xpath))
            )
            logger.info(f"🚀 {self.masked_user} - 点击最终 Renew 按钮...")
            self.driver.execute_script("arguments[0].click();", confirm_btn)
        except Exception as e:
            raise Exception(f"弹窗内提交失败: {e}")
            
        logger.info(f"⏳ {self.masked_user} - 等待数据更新...")
        sleep(7000 + random.random() * 2000)

        # 结果核验
        try:
            alerts = self.driver.find_elements(By.CSS_SELECTOR, ".alert-danger")
            if alerts and alerts[0].is_displayed():
                alertmsg = alerts[0].text.strip().replace('×', '')
                # 这类提示表示“暂时还不能续期”，属于预期情况：只记录，不通知
                if should_skip_renew_notice(alertmsg):
                    logger.info(f"⏭️ {self.masked_user} - 暂不可续期，跳过通知: {alertmsg}")
                    return "skip", f"⏭️ {self.masked_user}\nℹ️ 暂不可续期: {alertmsg}"
                return "fail", f"⏳ {self.masked_user}\n⚠️ 续期失败: {alertmsg}"
            
            final_expiry_element = self.driver.find_element(By.XPATH, "//div[contains(text(), 'Expiry')]/following-sibling::div")
            final_expiry = final_expiry_element.text.strip()
            logger.info(f"✅ {self.masked_user} - 续期后到期时间: {final_expiry}")

            if final_expiry != initial_expiry and len(final_expiry) > 0:
                return "success", f"✅ {self.masked_user}\n🎉 续期成功: {final_expiry}"
            else:
                return "fail", f"⚠️ {self.masked_user}\n⚠️ 时间未更新 ({initial_expiry})"
        except Exception as e:
            return "fail", f"❌ {self.masked_user}\n⚠️ 验证结果出错: {e}"

    def run(self):
        try:
            self.setup_driver()
            status, message = self.process()
            return status, message
        except Exception as e:
            logger.error(f"❌ {self.masked_user} - 操作失败: {e}")
            self.screenshot_path = f"error-{self.user.split('@')[0]}.png"
            if self.driver:
                self.driver.save_screenshot(self.screenshot_path)
            return "fail", f"❌ {self.masked_user} 操作失败：{str(e)[:50]}"
        finally:
            if self.driver:
                self.driver.quit()

# ===================== 主逻辑管理 =====================
class MultiManager:
    def __init__(self):
        raw_accs = re.split(r'[,;]', ACCOUNTS_ENV)
        self.accounts = []
        for a in raw_accs:
            if ':' in a:
                u, p = a.split(':', 1)
                self.accounts.append({'user': u.strip(), 'pass': p.strip()})

    def run_all(self):
        total = len(self.accounts)
        logger.info(f"🔍 发现 {total} 个账号需要续期")
        results = []
        last_screenshot = None
        success_count = 0

        for i, acc in enumerate(self.accounts):
            logger.info(f"\n📋 处理第 {i+1}/{total} 个账号")
            bot = KatabumpAutoRenew(acc['user'], acc['pass'])
            status, msg = bot.run()
            # skip：暂不可续期，不进入通知汇总
            if status == 'skip':
                continue
            results.append({'message': msg, 'success': status == 'success'})
            if status == 'success':
                success_count += 1
            if bot.screenshot_path: last_screenshot = bot.screenshot_path

            if i < total - 1:
                wait_time = PAUSE_BETWEEN_ACCOUNTS_MS + random.random() * 5000
                logger.info(f"⏳ 账号间歇期：等待 {round(wait_time/1000)} 秒...")
                sleep(wait_time)

        # 若全部账号都是“暂不可续期”，则不发送任何 Telegram 通知
        if not results:
            logger.info("ℹ️ 本轮全部账号暂不可续期（或已被跳过），不发送 Telegram 通知")
            return

        summary = f"📊 登录汇总: {success_count}/{total} 个账号成功\n\n"
        summary += "\n\n".join([r['message'] for r in results])
        send_telegram(summary, last_screenshot)
        send_telegram(summary, last_screenshot)

        if last_screenshot and os.path.exists(last_screenshot):
            import glob
            for f in glob.glob("error-*.png"): os.remove(f)
        logger.info("\n✅ 所有账号处理完成！")

if __name__ == "__main__":
    if not ACCOUNTS_ENV:
        logger.error("❌ 未配置账号")
        exit(1)
    try:
        MultiManager().run_all()
    finally:
        os._exit(0)
