import json
import requests
from datetime import datetime
from urllib.parse import urlparse, parse_qs, unquote

JSON_FILE = r"E:\tem\bible_audio.json"

with open(JSON_FILE, "r", encoding="utf-8") as f:
    data = json.load(f)

first_entry = data[0]
first_chapter_url = list(first_entry["chapters"].values())[0]

print(f"书卷: {first_entry['book']}  版本: {first_entry['version']}")
print(f"URL: {first_chapter_url[:80]}...")
print()

# 解析签名参数
parsed = urlparse(first_chapter_url)
params = parse_qs(parsed.query)

sign_time_raw = params.get("q-sign-time", [""])[0]
if sign_time_raw:
    start_ts, end_ts = sign_time_raw.split(";")
    start_dt = datetime.utcfromtimestamp(int(start_ts))
    end_dt = datetime.utcfromtimestamp(int(end_ts))
    now_ts = datetime.utcnow()
    print(f"签名有效期 (UTC): {start_dt}  ~  {end_dt}")
    print(f"当前时间   (UTC): {now_ts}")
    expired = now_ts > end_dt
    print(f"签名是否已过期: {'是 !!!' if expired else '否，仍有效'}")
    if expired:
        delta = now_ts - end_dt
        print(f"已过期时长: {delta}")
    print()

# 尝试下载
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "audio/mpeg, */*",
}

print("正在请求第一个音频 URL ...")
try:
    resp = requests.get(first_chapter_url, headers=headers, timeout=15, stream=True)
    print(f"HTTP 状态码: {resp.status_code}")
    print(f"响应头: {dict(resp.headers)}")

    if resp.status_code == 200:
        content_length = resp.headers.get("Content-Length", "未知")
        print(f"\n下载成功！内容大小: {content_length} 字节")
        out_path = r"E:\tem\test_chapter1.mp3"
        with open(out_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        print(f"已保存到: {out_path}")
    else:
        print(f"\n请求失败，状态码: {resp.status_code}")
        body = resp.text[:500]
        print(f"响应内容（前500字）:\n{body}")

        if resp.status_code == 403:
            print("\n[分析] HTTP 403 Forbidden —— 最常见原因:")
            print("  1. 签名已过期（q-sign-time 超出有效期）")
            print("  2. 签名与请求 Host 不匹配")
            print("  3. 服务端已撤销该签名密钥")
        elif resp.status_code == 401:
            print("\n[分析] HTTP 401 Unauthorized —— 认证信息无效或缺失")

except requests.exceptions.ConnectionError as e:
    print(f"连接失败: {e}")
    print("[分析] 可能原因: DNS 解析失败、网络不通、或域名被屏蔽")
except requests.exceptions.Timeout:
    print("请求超时")
except Exception as e:
    print(f"异常: {e}")
