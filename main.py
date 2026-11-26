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
# PushPlus 用户 token，在 GitHub Secrets 中配置
PUSH_PLUS_TOKEN = os.environ.get("PUSH_PLUS_TOKEN", "").strip()

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


def push_warning(remain: float) -> None:
    """电量低于 config.toml 的 warning 阈值时，通过 PushPlus 新消息ClawBot 推送一次。"""
    threshold: float = config.get("warning", 20)
    if threshold <= 0 or remain >= threshold:
        logging.info(f"剩余电量 {remain} 不低于阈值 {threshold}，跳过推送")
        return
    if not PUSH_PLUS_TOKEN:
        logging.info("PUSH_PLUS_TOKEN 未配置，跳过推送")
        return

    content = (
        f"当前剩余电量：{remain:.1f} kWh\n"
        f"预警阈值：{threshold:.1f} kWh\n"
        f"检测时间：{get_date()}\n\n"
        "请及时充值，避免断电。"
    )
    try:
        resp = requests.post(
            "https://www.pushplus.plus/send",
            json={
                "token": PUSH_PLUS_TOKEN,
                "title": "华理宿舍电量告急",
                "content": content,
                "channel": "cmcc",
                "template": "txt",
            },
            timeout=10,
        )
        resp.raise_for_status()
        result = resp.json()
        if result.get("code") == 200:
            logging.info(f"PushPlus 推送成功，流水号：{result.get('data')}")
        else:
            logging.error(f"PushPlus 推送失败：{result}")
    except (requests.RequestException, ValueError) as e:
        logging.exception(f"PushPlus 推送异常：{e}")


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
push_warning(remain)
