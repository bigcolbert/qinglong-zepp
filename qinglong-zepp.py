# -*- coding: UTF-8 -*-
"""
// @name         华米运动步数修改(mixia) - 多账号基准随机化 + 通知
// @version      1.0
// @description  通过青龙面板修改华米运动步数并同步到微信/支付宝
// @note         多账号支持，环境变量 ZEPP_ACCOUNTS="账号#密码#基准&账号#密码#基准"
// @note         步数 = (基准 ± BASE_RANDOM_RANGE) ± STEP_RANGE（脚本内固定浮动）
// @note         运行结束后会通过 SendNotify.py 或 notify.py 发送汇总通知
"""

import requests
import os
import re
import sys
import time
import json
import socket
from random import randint
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

# 当前脚本路径
cur_path = os.path.abspath(os.path.dirname(__file__))
sys.path.append(cur_path)

# 兼容青龙通知模块导入
try:
    from SendNotify import send
except ModuleNotFoundError:
    try:
        from notify import send
    except ModuleNotFoundError:
        def send(title, msg):
            print(f"⚠️ 通知模块未找到，标题: {title}\n内容: {msg}")

# 全局配置
MAX_RETRIES = 3
TIMEOUT = (10, 30)
STEP_RANGE = 2000  # 固定浮动范围，可自行调整

def log(message):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}")

def resolve_dns():
    try:
        socket.getaddrinfo('api-user.huami.com', 443, flags=socket.AI_CANONNAME)
        log("✅ DNS解析成功")
        return True
    except Exception as e:
        log(f"❌ DNS解析失败: {str(e)}")
        return False

# 从单一环境变量获取多账号配置
def get_accounts():
    raw = os.environ.get("ZEPP_ACCOUNTS", "").strip()
    if not raw:
        log("❌ 错误：未配置 ZEPP_ACCOUNTS 环境变量")
        return []

    accounts = []
    for entry in raw.split("&"):
        parts = entry.split("#")
        if len(parts) < 3:
            log(f"⚠️ 跳过无效账号配置: {entry}")
            continue
        user, pwd, base = parts[:3]
        accounts.append({
            "user": user.strip(),
            "password": pwd.strip(),
            "base": int(base.strip()),
            "device_id": os.environ.get("DEVICE_ID", "88CC5224060006C4"),
            "proxy": os.environ.get("PROXY", "")
        })

    if not accounts:
        log("❌ ZEPP_ACCOUNTS 格式错误，请使用 账号#密码#基准&账号#密码#基准")
    return accounts

# 生成最终步数（基准 ± 基准随机范围 ± 固定浮动范围）
def generate_steps(config):
    base_random_range = int(os.environ.get("BASE_RANDOM_RANGE", 0))  # 基准随机范围
    base = config["base"]
    # 基准随机化
    if base_random_range > 0:
        base = randint(max(0, base - base_random_range), base + base_random_range)
        log(f"🎲 基准随机化: {base} (原基准: {config['base']}, 随机范围: ±{base_random_range})")
    # 最终步数生成
    steps = randint(max(0, base - STEP_RANGE), base + STEP_RANGE)
    log(f"🎲 最终生成步数: {steps} (浮动范围: ±{STEP_RANGE})")
    return steps

def get_token_path(user):
    current_dir = os.path.dirname(os.path.abspath(__file__))
    safe_user = re.sub(r'[^\w\-]', '_', user)  # 文件名安全
    return os.path.join(current_dir, f"zepp_token_{safe_user}.json")

def create_session(proxy=None):
    session = requests.Session()
    retry_strategy = Retry(
        total=MAX_RETRIES,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["POST", "GET"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=1, pool_maxsize=1)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    if proxy:
        session.proxies = {"http": proxy, "https": proxy}
    return session

def login(config):
    try:
        session = create_session(config.get('proxy'))
        third_name = "huami_phone" if config['user'].startswith("+86") else "huami"
        headers = {
            "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
            "user-agent": "MiFit/6.12.0 (MCE16; Android 16; Density/1.5)",
            "app_name": "com.xiaomi.hm.health",
        }
        url1 = f"https://api-user.huami.com/registrations/{config['user']}/tokens"
        data1 = {
            "client_id": "HuaMi",
            "country_code": "CN",
            "json_response": "true",
            "name": config['user'],
            "password": config['password'],
            "redirect_uri": "https://s3-us-west-2.amazonaws.com/hm-registration/successsignin.html",
            "state": "REDIRECTION",
            "token": "access"
        }
        log("🔄 正在尝试登录...")
        res1 = session.post(url1, data=data1, headers=headers, timeout=TIMEOUT)
        res1.raise_for_status()
        res1_json = res1.json()
        if "access" not in res1_json:
            log(f"❌ 第一步登录失败: {res1.text}")
            return None
        code = res1_json["access"]

        url2 = "https://account.huami.com/v2/client/login"
        data2 = {
            "app_name": "com.xiaomi.hm.health",
            "country_code": "CN",
            "code": code,
            "device_id": "02:00:00:00:00:00",
            "device_model": "android_phone",
            "app_version": "6.12.0",
            "grant_type": "access_token",
            "allow_registration": "false",
            "source": "com.xiaomi.hm.health",
            "third_name": third_name
        }
        res2 = session.post(url2, data=data2, headers=headers, timeout=TIMEOUT)
        res2.raise_for_status()
        res2_json = res2.json()
        if "token_info" not in res2_json:
            log(f"❌ 第二步登录失败: {res2.text}")
            return None

        token_data = {
            "login_token": res2_json["token_info"]["login_token"],
            "user_id": res2_json["token_info"]["user_id"],
            "app_token": res2_json["token_info"]["app_token"],
            "expire_time": int(time.time()) + 86400,
            "last_update": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        token_path = get_token_path(config['user'])
        with open(token_path, "w") as f:
            json.dump(token_data, f, indent=2)
        log("✅ 登录成功，Token已保存")
        return {"user_id": token_data["user_id"], "app_token": token_data["app_token"]}
    except Exception as e:
        log(f"❌ 登录异常: {str(e)}")
        return None

def refresh_token(config):
    try:
        token_path = get_token_path(config['user'])
        if not os.path.exists(token_path):
            return None
        with open(token_path, "r") as f:
            token_data = json.load(f)
        if time.time() > token_data["expire_time"]:
            log("⚠️ Token已过期")
            return None
        log("ℹ️ 使用缓存Token")
        return {"user_id": token_data["user_id"], "app_token": token_data["app_token"]}
    except Exception as e:
        log(f"❌ Token刷新失败: {str(e)}")
        return None

def get_timestamp():
    return str(int(time.time() * 1000))

def submit_steps(config, token, steps):
    try:
        timestamp = get_timestamp()
        seconds = int(int(timestamp) / 1000)
        date_today = time.strftime("%Y-%m-%d")
        session = create_session(config.get('proxy'))
        headers = {
            "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
            "user-agent": "MiFit/6.12.0 (MCE16; Android 16; Density/1.5)",
            "app_name": "com.xiaomi.hm.health",
            "apptoken": token["app_token"]
        }
        data_json = {
            "data_hr": "",
            "date": date_today,
            "data": [{
                "start": 0,
                "stop": 1439,
                "value": steps,
                "tz": 32,
                "did": config['device_id'],
                "src": 24
            }],
            "summary": json.dumps({
                "v": 6,
                "slp": {"st": seconds, "ed": seconds, "dp": 0},
                "stp": {"ttl": steps, "dis": round(steps * 0.6, 1),
                        "cal": round(steps * 0.04, 1), "wk": int(steps) / 1000},
                "goal": 8000,
                "tz": "28800"
            }),
            "source": 24,
            "type": 0
        }
        url = f"https://api-mifit-cn.huami.com/v1/data/band_data.json?&t={timestamp}"
        data = {
            "userid": token["user_id"],
            "last_sync_data_time": seconds,
            "device_type": 0,
            "last_deviceid": config['device_id'],
            "data_json": json.dumps([data_json])
        }
        res = session.post(url, data=data, headers=headers, timeout=TIMEOUT)
        res.raise_for_status()
        return res.json()
    except Exception as e:
        log(f"❌ 提交步数失败: {str(e)}")
        return None

def main():
    log("=" * 50)
    log("🏃 华米运动步数修改脚本开始运行（多账号 + 基准随机化 + 通知）")

    if not resolve_dns() and os.name == "posix":
        log("⚠️ 尝试使用备用DNS解析...")
        os.system('echo "nameserver 8.8.8.8" > /etc/resolv.conf')
        os.system('echo "nameserver 114.114.114.114" >> /etc/resolv.conf')

    accounts = get_accounts()
    if not accounts:
        return

    notify_messages = []

    for idx, config in enumerate(accounts, 1):
        log("-" * 40)
        log(f"👤 正在处理账号 {idx}: {config['user']}")
        token = refresh_token(config)
        if not token:
            log("🔄 Token无效，尝试重新登录...")
            token = login(config)
            if not token:
                msg = f"❌ 账号 {config['user']} 登录失败"
                log(msg)
                notify_messages.append(msg)
                continue

        steps = generate_steps(config)
        result = submit_steps(config, token, steps)
        if not result:
            msg = f"❌ 账号 {config['user']} 步数提交失败"
            log(msg)
            notify_messages.append(msg)
            continue

        msg = (
            f"✅ 账号: {config['user']}\n"
            f"步数: {steps}\n"
            f"日期: {time.strftime('%Y-%m-%d')}\n"
            f"设备ID: {config['device_id']}"
        )
        log(msg)
        notify_messages.append(msg)

    log("=" * 50)

    if notify_messages:
        try:
            send("华米运动步数提交结果", "\n\n".join(notify_messages))
        except Exception as e:
            log(f"⚠️ 通知发送失败: {e}")

if __name__ == "__main__":
    main()
