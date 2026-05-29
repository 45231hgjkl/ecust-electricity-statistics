import datetime
import json
import logging
import os
import re
from contextlib import suppress
from pathlib import Path
from typing import Any, Callable, TypedDict

import requests
import tomllib


class ItemType(TypedDict):
    time: str
    kWh: float


# DEBUG：开启调试模式，将信息输出至 stdout
DEBUG = os.environ.get("DEBUG", os.environ.get("debug", "")).strip()
URL = os.environ.get("URL", "").strip()

config = tomllib.loads(Path("config.toml").read_text(encoding="utf-8"))
logging.basicConfig(level=logging.INFO)

TZ = datetime.timezone(datetime.timedelta(hours=8))  # UTC+8


def once(func: Callable[..., Any]) -> Callable[..., Any]:
    """Runs a function only once."""
    results: dict[Callable[..., Any], Any] = {}

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if func not in results:
            results[func] = func(*args, **kwargs)
        return results[func]

    return wrapper


@once
def get_date() -> str:
    return datetime.datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")


# main
header = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Connection": "keep-alive",
    "Host": "yktyd.ecust.edu.cn",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "User-Agent": "Mozilla/5.0 (Linux; U; Android 4.1.2; zh-cn; Chitanda/Akari) AppleWebKit/534.30 (KHTML, like Gecko) Version/4.0 Mobile Safari/534.30 MicroMessenger/6.0.0.58_r884092.501 NetType/WIFI",
}
response = requests.get(URL, headers=header)
response.encoding = response.apparent_encoding

try:
    match = re.search(r"(-?\d+(?:\.\d+)?)度", response.text)
    if not match:
        raise ValueError("未在响应中找到电量数据")
    remain = float(match.group(1))
    if remain < 0 or remain > 9999:
        raise ValueError(f"电量值异常: {remain}")
    logging.info(f"剩余电量：{remain}")
except Exception as e:
    logging.exception(e)
    logging.error("剩余电量获取失败，response: " + response.text)
    exit(1)

originstring = "[]"

# read from data.js preprocessed as json
with suppress(FileNotFoundError):
    with open("data.js", "r", encoding="utf-8") as f:
        originstring = f.read().removeprefix("data=")
try:
    data: list[ItemType] = json.loads(originstring)
except json.decoder.JSONDecodeError:
    logging.error("data.js 格式错误，请参考注意事项进行检查")
    exit(1)

# add new data
if data and data[-1]["time"][:10] == get_date()[:10]:
    data[-1]["kWh"] = remain
    data[-1]["time"] = get_date()  # update to latest timestamp
else:
    data.append({"time": get_date(), "kWh": remain})

# write back to data.js
if not DEBUG:
    originstring = json.dumps(data, indent=2, ensure_ascii=False)
    _ = Path("data.js").write_text("data=" + originstring, encoding="utf-8")
    logging.info("write back to data.js")
else:
    logging.info(f"DEBUG mode - 剩余电量: {remain}, 记录总数: {len(data)}")

# push notification
PUSH_PLUS_TOKEN = os.environ.get("PUSH_PLUS_TOKEN", "").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_USER_IDS = os.environ.get("TELEGRAM_USER_IDS", "").strip()

if PUSH_PLUS_TOKEN or TELEGRAM_BOT_TOKEN:
    warning_threshold: float = config.get("warning", 10)
    push_warning_only: bool = config.get("push_warning_only", True)
    days_to_show: int = config.get("days_to_show", 10)

    if push_warning_only and remain >= warning_threshold:
        logging.info("push_warning_only 开启且电量未低于阈值，跳过推送")
    else:
        show_data = data[-days_to_show:] if len(data) >= days_to_show else data[:]
        lines = [f"当前剩余电量：{remain:.1f} kWh"]
        if remain < warning_threshold:
            lines.append(f"⚠️ 电量低于预警阈值（{warning_threshold} kWh）！")
        lines.append(f"\n最近 {len(show_data)} 条记录：")
        for item in show_data:
            t = item["time"][:10]
            v = item["kWh"]
            marker = " ⚡" if v < warning_threshold else ""
            lines.append(f"  {t}: {v:.1f} kWh{marker}")

        if config.get("detail", True):
            owner = os.environ.get("GITHUB_REPOSITORY_OWNER", "").strip()
            repo = (os.environ.get("GITHUB_REPOSITORY", "").strip().split("/") or [""])[-1]
            if owner and repo:
                lines.append(f"\n📊 图表：https://{owner}.github.io/{repo}/")

        message = "\n".join(lines)

        if TELEGRAM_BOT_TOKEN and TELEGRAM_USER_IDS:
            for uid in TELEGRAM_USER_IDS.split():
                uid = uid.strip()
                if not uid:
                    continue
                try:
                    resp = requests.post(
                        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                        json={"chat_id": uid, "text": message},
                        timeout=10,
                    )
                    if resp.status_code == 200:
                        logging.info(f"Telegram 推送成功: chat_id={uid}")
                    else:
                        logging.error(f"Telegram 推送失败: chat_id={uid}, {resp.text}")
                except Exception as ex:
                    logging.exception(f"Telegram 推送异常: chat_id={uid}, {ex}")

        if PUSH_PLUS_TOKEN:
            try:
                resp = requests.post(
                    "https://www.pushplus.plus/send",
                    json={"token": PUSH_PLUS_TOKEN, "title": "电费统计推送", "content": message},
                    timeout=10,
                )
                if resp.status_code == 200:
                    logging.info("PushPlus 推送成功")
                else:
                    logging.error(f"PushPlus 推送失败: {resp.text}")
            except Exception as ex:
                logging.exception(f"PushPlus 推送异常: {ex}")
