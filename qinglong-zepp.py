# -*- coding: UTF-8 -*-
"""
// @name         华米运动步数修改(mixia)
// @namespace    https://github.com/jilei522/qinglong-zepp/
// @version      2.0.0
// @description  通过青龙面板修改华米运动步数并同步到微信/支付宝
// @author       jilei522 
// @supportURL   https://github.com/jilei522/qinglong-zepp/ 
"""
 
import requests 
import os
import re 
import time
import json 
import socket
from random import randint 
from urllib3.util.retry  import Retry 
from requests.adapters  import HTTPAdapter
 
# 全局配置
MAX_RETRIES = 3
RETRY_WAIT = 5 
TIMEOUT = (10, 30)  # (连接超时, 读取超时)
 
# 配置日志输出
def log(message):
    print(f"[{time.strftime('%Y-%m-%d  %H:%M:%S')}] {message}")
 
# 增强版DNS解析 
def resolve_dns():
    try:
        # 强制刷新DNS缓存 
        socket.getaddrinfo('api-user.huami.com',  443, flags=socket.AI_CANONNAME)
        log("✅ DNS解析成功")
        return True 
    except Exception as e:
        log(f"❌ DNS解析失败: {str(e)}")
        return False
 
# 从环境变量获取配置
def get_config():
    try:
        config = {
            'user': os.environ.get('ZEPP_USER',  '').strip(),
            'password': os.environ.get('ZEPP_PWD',  '').strip(),
            'min_steps': int(os.environ.get('MIN_STEPS',  '17760')),
            'max_steps': int(os.environ.get('MAX_STEPS',  '82240')),
            'device_id': os.environ.get('DEVICE_ID',  '88CC5224060006C4'),
            'proxy': os.environ.get('PROXY',  '')  # 新增代理支持 
        }
        
        if not config['user'] or not config['password']:
            log("❌ 错误：未配置账号密码，请在青龙面板添加环境变量 ZEPP_USER 和 ZEPP_PWD")
            return None 
            
        # 验证账号格式
        if '@' in config['user']:  # 邮箱
            if not re.match(r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$',  config['user']):
                log("❌ 邮箱格式不正确")
                return None 
        elif config['user'].isdigit() and len(config['user']) == 11:  # 手机号
            config['user'] = f"+86{config['user']}"
        else:
            log("❌ 账号必须是邮箱或11位手机号")
            return None 
            
        return config 
    except Exception as e:
        log(f"❌ 配置加载失败: {str(e)}")
        return None 
 
# 获取Token文件路径
def get_token_path():
    current_dir = os.path.dirname(os.path.abspath(__file__)) 
    return os.path.join(current_dir,  "zepp_token.json")   # 改为json格式
 
# 创建稳健的请求会话
def create_session(proxy=None):
    session = requests.Session()
    
    # 重试策略 
    retry_strategy = Retry(
        total=MAX_RETRIES,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["POST", "GET"]
    )
    
    # 适配器配置 
    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=1,
        pool_maxsize=1
    )
    session.mount("https://",  adapter)
    session.mount("http://",  adapter)
    
    # 代理设置
    if proxy:
        session.proxies  = {
            'http': proxy,
            'https': proxy 
        }
    
    # 超时设置 
    session.request  = lambda method, url, **kwargs: requests.Session.request( 
        session, method, url, timeout=TIMEOUT, **kwargs
    )
    
    return session 
 
# 登录功能
def login(config):
    try:
        # 创建会话
        session = create_session(config.get('proxy')) 
        
        # 确定账号类型 
        third_name = "huami_phone" if config['user'].startswith("+86") else "huami"
        
        headers = {
            "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
            "user-agent": "MiFit/6.12.0 (MCE16; Android 16; Density/1.5)",
            "app_name": "com.xiaomi.hm.health", 
        }
        
        # 第一步：获取access token
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
        res1 = session.post(url1,  data=data1, headers=headers)
        
        # 处理响应 
        if res1.status_code  == 429:
            retry_after = int(res1.headers.get('Retry-After',  60))
            log(f"⚠️ 请求过于频繁，等待{retry_after}秒后重试...")
            time.sleep(retry_after) 
            return login(config)  # 递归重试
            
        res1.raise_for_status() 
        res1_json = res1.json() 
        
        if "access" not in res1_json:
            log(f"❌ 第一步登录失败，响应: {res1.text}") 
            return None 
            
        code = res1_json["access"]
        
        # 第二步：获取登录token
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
        
        res2 = session.post(url2,  data=data2, headers=headers)
        res2.raise_for_status() 
        res2_json = res2.json() 
        
        if "token_info" not in res2_json:
            log(f"❌ 第二步登录失败，响应: {res2.text}") 
            return None
            
        # 保存token
        token_data = {
            "login_token": res2_json["token_info"]["login_token"],
            "user_id": res2_json["token_info"]["user_id"],
            "app_token": res2_json["token_info"]["app_token"],
            "expire_time": int(time.time())  + 86400,  # 24小时后过期 
            "last_update": time.strftime("%Y-%m-%d  %H:%M:%S")
        }
        
        token_path = get_token_path()
        with open(token_path, "w") as f:
            json.dump(token_data,  f, indent=2)
            
        log("✅ 登录成功，Token已保存")
        return {
            "user_id": token_data["user_id"],
            "app_token": token_data["app_token"]
        }
        
    except requests.exceptions.RequestException  as e:
        log(f"❌ 网络请求异常: {str(e)}")
        if "CERTIFICATE_VERIFY_FAILED" in str(e):
            log("⚠️ SSL证书验证失败，尝试以下解决方案：")
            log("1. 更新系统CA证书")
            log("2. 在青龙面板配置中添加：export REQUESTS_CA_BUNDLE=""/etc/ssl/certs/ca-certificates.crt""") 
        return None 
    except Exception as e:
        log(f"❌ 登录过程中发生异常: {str(e)}")
        return None
 
# 刷新Token 
def refresh_token(config):
    try:
        token_path = get_token_path()
        if not os.path.exists(token_path): 
            return None
            
        with open(token_path, "r") as f:
            token_data = json.load(f) 
            
        # 检查token是否过期 
        if time.time()  > token_data["expire_time"]:
            log("⚠️ Token已过期，需要重新登录")
            return None
            
        session = create_session(config.get('proxy')) 
        
        # 刷新login_token
        url = f"https://account-cn.huami.com/v1/client/renew_login_token?login_token={token_data['login_token']}" 
        res = session.get(url) 
        res.raise_for_status() 
        res_json = res.json() 
        
        if "token_info" in res_json:
            # 更新token数据 
            token_data.update({ 
                "login_token": res_json["token_info"]["login_token"],
                "expire_time": int(time.time())  + 86400,
                "last_update": time.strftime("%Y-%m-%d  %H:%M:%S")
            })
            
            with open(token_path, "w") as f:
                json.dump(token_data,  f, indent=2)
                
        # 返回app_token 
        return {
            "user_id": token_data["user_id"],
            "app_token": token_data["app_token"]
        }
    except Exception as e:
        log(f"❌ Token刷新失败: {str(e)}")
        return None 
 
# 获取时间戳（多源容错）
def get_timestamp():
    timestamp_sources = [
        "https://api.m.taobao.com/rest/api3.do?api=mtop.common.getTimestamp", 
        "http://api.m.taobao.com/rest/api3.do?api=mtop.common.getTimestamp", 
        "https://www.baidu.com", 
        "https://www.taobao.com" 
    ]
    
    session = create_session()
    for source in timestamp_sources:
        try:
            if "baidu" in source:
                return str(int(time.time()  * 1000))
                
            res = session.get(source,  timeout=10)
            data = res.json() 
            return data["data"]["t"]
        except:
            continue
            
    return str(int(time.time()  * 1000))
 
# 提交步数数据 
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
        
        # 构造提交数据
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
                "stp": {
                    "ttl": steps,
                    "dis": int(steps) * 0.6,
                    "cal": int(steps) * 0.04,
                    "wk": int(steps) / 1000 
                },
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
        
        res = session.post(url,  data=data, headers=headers)
        res.raise_for_status() 
        return res.json() 
    except Exception as e:
        log(f"❌ 提交步数失败: {str(e)}")
        return None
 
# 主函数 
def main(): 
    log("="*50)
    log("🏃 华米运动步数修改脚本开始运行")
    
    # 检查DNS 
    if not resolve_dns():
        log("⚠️ 尝试使用备用DNS解析...")
        os.system('echo  "nameserver 8.8.8.8" > /etc/resolv.conf') 
        os.system('echo  "nameserver 114.114.114.114" >> /etc/resolv.conf') 
    
    # 获取配置
    config = get_config()
    if not config:
        return
        
    log(f"🔧 配置加载成功 | 账号: {config['user']} | 设备ID: {config['device_id']}")
    
    # 尝试使用现有Token
    token = refresh_token(config)
    
    # 如果Token无效则重新登录
    if not token:
        log("🔄 Token无效，尝试重新登录...")
        token = login(config)
        if not token:
            log("❌ 登录失败，请检查账号密码和网络连接")
            return
            
    # 生成随机步数
    steps = randint(config['min_steps'], config['max_steps'])
    log(f"🎯 准备提交步数: {steps} (范围: {config['min_steps']}-{config['max_steps']})")
    
    # 提交步数 
    result = submit_steps(config, token, steps)
    if not result:
        log("❌ 步数提交失败")
        return
        
    log("✅ 提交成功! 详细信息:")
    log(f"├ 账号: {config['user']}")
    log(f"├ 步数: {steps}")
    log(f"├ 日期: {time.strftime('%Y-%m-%d')}") 
    log(f"├ 设备ID: {config['device_id']}")
    log(f"└ 服务器响应: {json.dumps(result,  ensure_ascii=False, indent=2)}")
    log("="*50)
 
if __name__ == "__main__":
    main()
