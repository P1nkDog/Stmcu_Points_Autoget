import json
import time
import os
import random
import re
import argparse
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException, SessionNotCreatedException
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.microsoft import EdgeChromiumDriverManager

# 常量定义
BASE_URL = "https://www.stmcu.com.cn"
POINTS_URL = f"{BASE_URL}/User/MyPoint"
VIDEO_URL_PREFIX = f"{BASE_URL}/video/"
CONFIG_FILE = "config.json"

# 默认配置
DEFAULT_CONFIG = {
    "browser": "",
    "max_daily_points": 300,
    "points_per_video": 10,
    "delay_min": 0.5,
    "delay_max": 2.0,
    "page_load_timeout": 10,
    "debug": False,
    "users": {}
}

def load_config():
    """加载配置文件"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                # 合并默认配置（防止缺少新字段）
                for key, value in DEFAULT_CONFIG.items():
                    if key not in config:
                        config[key] = value
                return config
        except Exception as e:
            print(f"[警告] 加载配置文件失败: {e}")
    
    return DEFAULT_CONFIG.copy()

def save_config(config):
    """保存配置文件"""
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[错误] 保存配置文件失败: {e}")

def select_browser(config):
    """首次运行时选择浏览器"""
    if config["browser"]:
        return config["browser"]
    
    print("\n" + "="*50)
    print("首次运行配置")
    print("="*50)
    print("\n请选择要使用的浏览器:")
    print("  1. Edge (推荐)")
    print("  2. Chrome")
    
    while True:
        choice = input("\n请输入选项 (1 或 2): ").strip()
        if choice == "1":
            browser = "edge"
            break
        elif choice == "2":
            browser = "chrome"
            break
        else:
            print("[错误] 无效选项，请输入 1 或 2")
    
    config["browser"] = browser
    save_config(config)
    print(f"\n[INFO] 已选择 {browser.upper()} 浏览器，配置已保存")
    return browser

def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="STMCU 自动积点脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py                          # 使用配置文件
  python main.py --max-points 200         # 设置每日上限200积点
  python main.py --delay-min 2 --delay-max 5  # 设置延迟范围2-5秒
  python main.py --debug                  # 启用调试模式
  python main.py --browser chrome         # 使用Chrome浏览器
        """
    )
    
    parser.add_argument(
        "--max-points",
        type=int,
        default=None,
        help="每日积点上限"
    )
    
    parser.add_argument(
        "--points-per-video",
        type=int,
        default=None,
        help="每个视频获得的积点数"
    )
    
    parser.add_argument(
        "--delay-min",
        type=float,
        default=None,
        help="最小延迟秒数"
    )
    
    parser.add_argument(
        "--delay-max",
        type=float,
        default=None,
        help="最大延迟秒数"
    )
    
    parser.add_argument(
        "--timeout",
        type=int,
        default=None,
        help="页面加载超时秒数"
    )
    
    parser.add_argument(
        "--debug",
        action="store_true",
        default=None,
        help="启用调试模式，输出详细信息"
    )
    
    parser.add_argument(
        "--browser",
        type=str,
        choices=["chrome", "edge"],
        default=None,
        help="选择浏览器"
    )
    
    parser.add_argument(
        "--reset-browser",
        action="store_true",
        default=False,
        help="重新选择浏览器"
    )
    
    return parser.parse_args()

class StmcuPointsBot:
    def __init__(self, config):
        self.config = config
        self.driver = None
        self.today = datetime.now().strftime("%Y-%m-%d")
        self.today_points = 0
        self.last_video_id = 1
        self.log_entries = []
        self.username = None
        
        # 从配置中获取参数
        self.max_daily_points = config["max_daily_points"]
        self.points_per_video = config["points_per_video"]
        self.delay_min = config["delay_min"]
        self.delay_max = config["delay_max"]
        self.page_load_timeout = config["page_load_timeout"]
        self.debug = config["debug"]
        self.browser = config["browser"]
        
    def get_user_progress_file(self):
        """获取用户独立的进度文件"""
        return f"progress_{self.username}.json"
    
    def get_user_logs_dir(self):
        """获取用户独立的日志目录"""
        return f"logs_{self.username}"
    
    def get_random_user_agent(self):
        """获取随机 User-Agent"""
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        ]
        return random.choice(user_agents)

    def random_delay(self, min_seconds=None, max_seconds=None):
        """随机延迟，模拟人类行为"""
        min_s = min_seconds if min_seconds is not None else self.delay_min
        max_s = max_seconds if max_seconds is not None else self.delay_max
        delay = random.uniform(min_s, max_s)
        if self.debug:
            print(f"[调试] 延迟 {delay:.2f} 秒")
        time.sleep(delay)

    def find_browser_binary(self, browser_type=None):
        """查找浏览器可执行文件"""
        browser = browser_type or self.browser
        
        if browser == "chrome":
            possible_paths = [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe"),
            ]
            registry_key = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"
        elif browser == "edge":
            possible_paths = [
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                os.path.expanduser(r"~\AppData\Local\Microsoft\Edge\Application\msedge.exe"),
            ]
            registry_key = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe"
        else:
            return None
        
        for path in possible_paths:
            if os.path.exists(path):
                return path
        
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, registry_key)
            browser_path = winreg.QueryValue(key, "")
            winreg.CloseKey(key)
            if os.path.exists(browser_path):
                return browser_path
        except Exception:
            pass
        
        return None

    def init_browser(self):
        """初始化浏览器（含反检测措施）"""
        browser_path = self.find_browser_binary()
        if browser_path is None:
            print("\n" + "="*50)
            print(f"[错误] 未找到 {self.browser.upper()} 浏览器")
            if self.browser == "chrome":
                print("[提示] 请确保已安装 Google Chrome 浏览器")
                print("[提示] 下载地址: https://www.google.com/chrome/")
            else:
                print("[提示] 请确保已安装 Microsoft Edge 浏览器")
                print("[提示] 下载地址: https://www.microsoft.com/edge")
            print("="*50)
            raise FileNotFoundError(f"{self.browser.upper()} 浏览器未找到")
        
        if self.debug:
            print(f"[调试] {self.browser.upper()} 路径: {browser_path}")
        
        try:
            if self.browser == "chrome":
                chrome_options = ChromeOptions()
                chrome_options.binary_location = browser_path
                chrome_options.add_argument("--start-maximized")
                chrome_options.add_argument("--disable-blink-features=AutomationControlled")
                chrome_options.add_argument(f"--user-agent={self.get_random_user_agent()}")
                chrome_options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
                chrome_options.add_experimental_option('useAutomationExtension', False)
                chrome_options.add_experimental_option("detach", True)
                chrome_options.add_argument("--disable-infobars")
                chrome_options.add_argument("--disable-dev-shm-usage")
                chrome_options.add_argument("--no-sandbox")
                
                service = ChromeService(ChromeDriverManager().install())
                self.driver = webdriver.Chrome(service=service, options=chrome_options)
                
            elif self.browser == "edge":
                edge_options = EdgeOptions()
                edge_options.binary_location = browser_path
                edge_options.add_argument("--start-maximized")
                
                try:
                    driver_path = EdgeChromiumDriverManager().install()
                    if self.debug:
                        print(f"[调试] Edge WebDriver 路径: {driver_path}")
                    service = EdgeService(driver_path)
                    self.driver = webdriver.Edge(service=service, options=edge_options)
                except Exception as e:
                    if self.debug:
                        print(f"[调试] Edge 初始化失败: {e}")
                    raise Exception(
                        "无法初始化 Edge 浏览器。请确保：\n"
                        "1. Edge 浏览器已安装\n"
                        "2. Edge WebDriver 版本与浏览器版本匹配\n"
                        "访问 https://developer.microsoft.com/en-us/microsoft-edge/tools/webdriver/ 下载对应版本"
                    )
                
        except SessionNotCreatedException as e:
            if "cannot find" in str(e).lower() and "binary" in str(e).lower():
                print("\n" + "="*50)
                print(f"[错误] {self.browser.upper()} 浏览器路径无效")
                print(f"[尝试路径] {browser_path}")
                print(f"[提示] 请确保 {self.browser.upper()} 浏览器已正确安装")
                print("="*50)
            raise
        
        # 执行反检测 JavaScript
        self.driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en']});
                window.chrome = {runtime: {}};
            """
        })
        
        self.driver.implicitly_wait(10)
        
    def get_username(self):
        """从网页获取当前登录用户名"""
        try:
            self.driver.get(POINTS_URL)
            
            wait = WebDriverWait(self.driver, self.page_load_timeout)
            try:
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".common-h-login")))
            except TimeoutException:
                pass
            
            self.random_delay(0.5, 1)
            
            # 策略1: 查找 common-h-login 中的用户名
            try:
                login_elements = self.driver.find_elements(By.CSS_SELECTOR, ".common-h-login a[href*='UserCenter']")
                for elem in login_elements:
                    text = elem.text.strip()
                    if text and text != "退出":
                        return text
            except Exception:
                pass
            
            # 策略2: 查找欢迎信息
            try:
                body_text = self.driver.find_element(By.TAG_NAME, "body").text
                match = re.search(r'欢迎[：:]\s*(\S+)', body_text)
                if match:
                    return match.group(1)
            except Exception:
                pass
            
            return None
            
        except Exception as e:
            if self.debug:
                print(f"[调试] 获取用户名失败: {e}")
            return None
        
    def load_progress(self):
        """加载用户进度文件"""
        progress_file = self.get_user_progress_file()
        if os.path.exists(progress_file):
            with open(progress_file, 'r', encoding='utf-8') as f:
                progress = json.load(f)
                if progress.get("date") == self.today:
                    self.last_video_id = progress.get("last_video_id", 1)
                    self.today_points = progress.get("today_points", 0)
                    print(f"[INFO] 加载今日进度: 视频ID从{self.last_video_id}开始, 已获积点{self.today_points}")
                else:
                    self.last_video_id = progress.get("last_video_id", 1)
                    print(f"[INFO] 新的一天, 从视频ID {self.last_video_id} 开始")
                    
    def save_progress(self):
        """保存进度到用户文件（含错误处理）"""
        progress_file = self.get_user_progress_file()
        progress = {
            "date": self.today,
            "last_video_id": self.last_video_id,
            "today_points": self.today_points
        }
        try:
            temp_file = progress_file + ".tmp"
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(progress, f, ensure_ascii=False, indent=2)
            if os.path.exists(progress_file):
                os.replace(temp_file, progress_file)
            else:
                os.rename(temp_file, progress_file)
        except PermissionError:
            print("[警告] 保存进度失败: 文件被占用，尝试直接写入...")
            try:
                with open(progress_file, 'w', encoding='utf-8') as f:
                    json.dump(progress, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"[错误] 保存进度失败: {e}")
        except OSError as e:
            print(f"[错误] 保存进度失败: {e}")
        except Exception as e:
            print(f"[错误] 保存进度失败: {e}")
            
    def wait_for_user_login(self):
        """等待用户手动登录"""
        self.driver.get(f"{BASE_URL}/User/Login")
        print("\n" + "="*50)
        print("[重要] 请在浏览器中手动登录账号")
        print("登录完成后，按回车键继续...")
        print("="*50 + "\n")
        input()
        
    def get_current_points(self):
        """获取当前积点（精确定位）"""
        try:
            self.driver.get(POINTS_URL)
            
            wait = WebDriverWait(self.driver, self.page_load_timeout)
            try:
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".lb1b")))
                wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
            except TimeoutException:
                print("[警告] 页面加载超时，尝试继续...")
            
            self.random_delay(2, 3)
            
            # 策略1: 精确查找 <font class="zt_r"> 元素
            if self.debug:
                print("[调试] 策略1: 查找 font.zt_r 元素")
            try:
                elements = self.driver.find_elements(By.CSS_SELECTOR, "font.zt_r")
                for elem in elements:
                    text = elem.text.strip()
                    if text.isdigit():
                        if self.debug:
                            print(f"[调试] 策略1成功: 找到积点 {text}")
                        return int(text)
            except Exception:
                pass
            
            # 策略2: 查找包含"可用积点"的 div.lb1b 中的数字
            if self.debug:
                print("[调试] 策略2: 查找 div.lb1b 中的可用积点")
            try:
                lb1b_elements = self.driver.find_elements(By.CSS_SELECTOR, "div.lb1b")
                for lb1b in lb1b_elements:
                    text = lb1b.text
                    if "可用积点" in text:
                        match = re.search(r'可用积点\s*(\d+)', text)
                        if match:
                            if self.debug:
                                print(f"[调试] 策略2成功: 找到积点 {match.group(1)}")
                            return int(match.group(1))
            except Exception:
                pass
            
            # 策略3: 通用查找
            if self.debug:
                print("[调试] 策略3: 全文搜索可用积点")
            try:
                body_text = self.driver.find_element(By.TAG_NAME, "body").text
                match = re.search(r'可用积[点分]\s*(\d+)', body_text)
                if match:
                    if self.debug:
                        print(f"[调试] 策略3成功: 找到积点 {match.group(1)}")
                    return int(match.group(1))
            except Exception:
                pass
            
            # 策略4: 调试模式
            if self.debug:
                print("\n" + "="*50)
                print("[调试] 策略4: 分析页面结构")
            else:
                print("\n" + "="*50)
                print("[调试] 自动识别积点失败")
                print("[调试] 正在分析页面结构...")
            
            try:
                debug_elements = self.driver.find_elements(By.XPATH, "//*[contains(text(), '积')]")
                print(f"[调试] 找到 {len(debug_elements)} 个包含'积'的元素:")
                for i, elem in enumerate(debug_elements[:5]):
                    print(f"  [{i+1}] 标签: {elem.tag_name}, 类: {elem.get_attribute('class')}, 文本: {elem.text[:50]}...")
            except Exception:
                pass
            
            print("="*50)
            print("[提示] 请手动查看浏览器中的积点")
            return None
            
        except Exception as e:
            print(f"[错误] 获取积点失败: {e}")
            return None
            
    def get_today_earned_points(self):
        """从积点变动详情页获取今日已获积点"""
        today_str = datetime.now().strftime("%Y-%m-%d")
        total_earned = 0
        page = 1
        
        try:
            while True:
                url = f"{BASE_URL}/User/userPointsDetail?&p={page}"
                if self.debug:
                    print(f"[调试] 正在访问积点详情页: {url}")
                
                self.driver.get(url)
                
                wait = WebDriverWait(self.driver, self.page_load_timeout)
                try:
                    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".snr")))
                    wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
                except TimeoutException:
                    if self.debug:
                        print("[调试] 页面加载超时")
                    break
                
                self.random_delay(2, 3)
                
                # 查找表格中的行
                try:
                    rows = self.driver.find_elements(By.CSS_SELECTOR, "table.table tr")
                    found_today = False
                    
                    for row in rows:
                        cells = row.find_elements(By.CSS_SELECTOR, "td.listd")
                        if len(cells) >= 3:
                            points_text = cells[0].text.strip()
                            note_text = cells[1].text.strip()
                            date_text = cells[2].text.strip()
                            
                            # 检查是否是今日的记录
                            if today_str in date_text:
                                found_today = True
                                # 只统计正向积点（观看视频、下载视频等）
                                if points_text.isdigit():
                                    points = int(points_text)
                                    if points > 0:
                                        total_earned += points
                                        if self.debug:
                                            print(f"[调试] 今日记录: {points_text} 积点 - {note_text}")
                    
                    # 如果这一页没有今日记录，停止翻页
                    if not found_today:
                        if self.debug:
                            print(f"[调试] 第 {page} 页无今日记录，停止翻页")
                        break
                    
                    # 检查是否有下一页
                    try:
                        # 查找"下一页"链接
                        next_links = self.driver.find_elements(By.XPATH, "//a[contains(text(), '下一页') or contains(text(), 'Next')]")
                        if not next_links:
                            if self.debug:
                                print("[调试] 无下一页链接")
                            break
                    except Exception:
                        break
                    
                    page += 1
                    
                except Exception as e:
                    if self.debug:
                        print(f"[调试] 解析表格失败: {e}")
                    break
            
            if self.debug:
                print(f"[调试] 今日共获取 {total_earned} 积点（共访问 {page} 页）")
            
            return total_earned
            
        except Exception as e:
            print(f"[错误] 获取今日积点详情失败: {e}")
            return 0
            
    def watch_video(self, video_id):
        """观看视频"""
        video_url = f"{VIDEO_URL_PREFIX}{video_id}"
        try:
            self.driver.get(video_url)
            
            # 等待页面完全加载
            wait = WebDriverWait(self.driver, self.page_load_timeout)
            try:
                # 等待 body 加载完成
                wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
                # 额外等待页面 JavaScript 执行完成
                wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
            except TimeoutException:
                return False, "页面加载超时"
            
            # 增加等待时间，确保动态内容加载完成
            self.random_delay(3, 5)
            
            page_source = self.driver.page_source.lower()
            if "404" in page_source or "页面不存在" in page_source or "not found" in page_source:
                return False, "页面不存在(404)"
                
            video_elements = self.driver.find_elements(By.TAG_NAME, "video")
            iframe_elements = self.driver.find_elements(By.TAG_NAME, "iframe")
            
            if not video_elements and not iframe_elements:
                video_containers = self.driver.find_elements(By.CSS_SELECTOR, "[class*='video'], [class*='player']")
                if not video_containers:
                    return False, "无视频内容"
                    
            return True, "访问成功"
            
        except TimeoutException:
            return False, "页面加载超时"
        except WebDriverException as e:
            return False, f"浏览器错误: {str(e)[:100]}"
        except Exception as e:
            return False, f"访问异常: {str(e)}"
            
    def add_log(self, video_id, status, points_before, points_after, note=""):
        """添加日志条目"""
        entry = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "video_id": video_id,
            "video_url": f"{VIDEO_URL_PREFIX}{video_id}",
            "status": status,
            "points_before": points_before,
            "points_after": points_after,
            "points_gained": points_after - points_before if points_after is not None and points_before is not None else 0,
            "note": note
        }
        self.log_entries.append(entry)
        
    def save_log_to_md(self):
        """保存日志到用户独立的MD文件"""
        logs_dir = self.get_user_logs_dir()
        if not os.path.exists(logs_dir):
            os.makedirs(logs_dir)
            
        log_file = os.path.join(logs_dir, f"log_{self.today}.md")
        
        with open(log_file, 'w', encoding='utf-8') as f:
            f.write(f"# STMCU积点任务日志\n\n")
            f.write(f"**用户**: {self.username}\n")
            f.write(f"**日期**: {self.today}\n")
            f.write(f"**总获取积点**: {self.today_points}\n")
            f.write(f"**起始视频ID**: {self.last_video_id - len(self.log_entries)}\n")
            f.write(f"**结束视频ID**: {self.last_video_id - 1}\n\n")
            
            f.write("## 详细记录\n\n")
            f.write("| 时间 | 视频ID | 状态 | 积点前 | 积点后 | 获得积点 | 备注 |\n")
            f.write("|------|--------|------|--------|--------|----------|------|\n")
            
            for entry in self.log_entries:
                status_emoji = "✅" if entry["status"] == "已看" else "❌"
                points_display = f"+{entry['points_gained']}" if entry['points_gained'] > 0 else str(entry['points_gained'])
                f.write(f"| {entry['time']} | {entry['video_id']} | {status_emoji} {entry['status']} | {entry['points_before']} | {entry['points_after']} | {points_display} | {entry['note']} |\n")
                
            f.write("\n## 统计\n\n")
            valid_count = sum(1 for e in self.log_entries if e["status"] == "已看")
            invalid_count = sum(1 for e in self.log_entries if e["status"] == "无效")
            f.write(f"- 有效视频: {valid_count} 个\n")
            f.write(f"- 无效视频: {invalid_count} 个\n")
            f.write(f"- 总获取积点: {self.today_points}\n")
            
        print(f"\n[INFO] 日志已保存到: {log_file}")
        return log_file
        
    def run(self):
        """主运行函数"""
        print("="*50)
        print("STMCU 自动积点脚本")
        print("="*50)
        
        # 显示配置信息
        if self.debug:
            print("\n[调试] 当前配置:")
            print(f"  浏览器: {self.browser.upper()}")
            print(f"  每日积点上限: {self.max_daily_points}")
            print(f"  每视频积点: {self.points_per_video}")
            print(f"  延迟范围: {self.delay_min}-{self.delay_max} 秒")
            print(f"  页面超时: {self.page_load_timeout} 秒")
            print()
        
        # 初始化浏览器
        print("\n[INFO] 正在初始化浏览器...")
        self.init_browser()
        
        try:
            # 等待用户登录
            self.wait_for_user_login()
            
            # 获取用户名
            print("\n[INFO] 正在获取用户名...")
            self.username = self.get_username()
            if self.username:
                print(f"[INFO] 当前用户: {self.username}")
            else:
                print("[警告] 无法自动获取用户名")
                self.username = input("请输入您的用户名: ").strip()
                if not self.username:
                    self.username = "default"
            
            # 加载用户进度
            print(f"\n[INFO] 加载用户 {self.username} 的进度...")
            self.load_progress()
            
            # 从积点详情页获取今日已获积点
            print("\n[INFO] 正在获取今日积点详情...")
            today_earned = self.get_today_earned_points()
            if today_earned > 0:
                print(f"[INFO] 今日已获取 {today_earned} 积点")
                self.today_points = today_earned
            else:
                print("[INFO] 今日尚未获取积点")
            
            # 获取当前积点
            print("\n[INFO] 正在获取当前积点...")
            current_points = self.get_current_points()
            if current_points is not None:
                print(f"[INFO] 当前积点: {current_points}")
            else:
                print("[警告] 无法获取积点，将手动输入")
                current_points = int(input("请输入当前积点: "))
            
            # 检查今日是否已达到上限
            if self.today_points >= self.max_daily_points:
                print("\n" + "="*50)
                print(f"[警告] 用户 {self.username} 今日已获取 {self.today_points} 积点")
                print(f"[警告] 已达到每日上限 {self.max_daily_points} 点")
                print("[警告] 继续观看视频不会增加积点，反而会浪费视频资源")
                print("[警告] （每个视频只有第一次观看时能获得积点）")
                print("="*50)
                print("\n[INFO] 脚本退出")
                return
            
            remaining = self.max_daily_points - self.today_points
            print(f"\n[INFO] 今日还可获取 {remaining} 积点")
            print(f"[INFO] 需要观看 {remaining // self.points_per_video} 个视频")
            print(f"[INFO] 从视频ID {self.last_video_id} 开始")
            
            # 开始视频任务循环
            print("\n" + "="*50)
            print("开始执行视频任务")
            print("="*50 + "\n")
            
            video_id = self.last_video_id
            
            while self.today_points < self.max_daily_points:
                if self.today_points >= self.max_daily_points:
                    print(f"\n[INFO] 今日积点已达到 {self.today_points}，停止任务")
                    break
                    
                print(f"\n[视频 {video_id}] 正在访问...")
                
                points_before = current_points
                
                success, message = self.watch_video(video_id)
                
                if success:
                    self.random_delay(1, 2)
                    
                    new_points = self.get_current_points()
                    
                    if new_points is not None:
                        points_gained = new_points - points_before
                        
                        if points_gained > 0:
                            self.today_points += points_gained
                            current_points = new_points
                            status = "已看"
                            note = f"+{points_gained}积点"
                            print(f"[成功] 视频 {video_id}: 积点 {points_before} → {new_points} (+{points_gained})，今日累计 {self.today_points}")
                        else:
                            status = "无效"
                            note = "未获得积点"
                            print(f"[无效] 视频 {video_id}: 积点 {points_before} → {new_points} (+0)")
                    else:
                        status = "未知"
                        note = "无法获取积点"
                        print(f"[警告] 视频 {video_id}: 无法获取积点变化")
                        
                else:
                    status = "无效"
                    note = message
                    print(f"[无效] 视频 {video_id}: {message}")
                    
                self.add_log(video_id, status, points_before, current_points, note)
                
                self.last_video_id = video_id + 1
                self.save_progress()
                
                video_id += 1
                
                self.random_delay(0.5, 1.5)
                
        except KeyboardInterrupt:
            print("\n\n[INFO] 用户中断程序")
            
        except Exception as e:
            print(f"\n[错误] 程序异常: {e}")
            import traceback
            traceback.print_exc()
            
        finally:
            if self.log_entries:
                log_file = self.save_log_to_md()
                
            self.save_progress()
            
            if self.driver:
                print("\n[INFO] 正在关闭浏览器...")
                self.driver.quit()
                
            print("\n" + "="*50)
            print("任务完成总结")
            print("="*50)
            print(f"用户: {self.username}")
            print(f"今日获取积点: {self.today_points}")
            print(f"处理视频数量: {len(self.log_entries)}")
            if self.log_entries:
                valid_count = sum(1 for e in self.log_entries if e["status"] == "已看")
                print(f"有效视频数量: {valid_count}")
            print(f"下次起始视频ID: {self.last_video_id}")
            print("="*50)

if __name__ == "__main__":
    # 加载配置文件
    config = load_config()
    
    # 解析命令行参数
    args = parse_args()
    
    # 重置浏览器选择
    if args.reset_browser:
        config["browser"] = ""
    
    # 选择浏览器（首次运行或重置时）
    if not config["browser"]:
        select_browser(config)
    
    # 命令行参数覆盖配置文件
    if args.browser is not None:
        config["browser"] = args.browser
    if args.max_points is not None:
        config["max_daily_points"] = args.max_points
    if args.points_per_video is not None:
        config["points_per_video"] = args.points_per_video
    if args.delay_min is not None:
        config["delay_min"] = args.delay_min
    if args.delay_max is not None:
        config["delay_max"] = args.delay_max
    if args.timeout is not None:
        config["page_load_timeout"] = args.timeout
    if args.debug is not None:
        config["debug"] = args.debug
    
    # 验证参数
    if config["delay_min"] > config["delay_max"]:
        print("[错误] delay-min 不能大于 delay-max")
        exit(1)
    
    if config["max_daily_points"] <= 0:
        print("[错误] max-points 必须大于 0")
        exit(1)
    
    # 保存配置
    save_config(config)
    
    bot = StmcuPointsBot(config)
    bot.run()
