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


def once(func: Callable[..., Any]) -> Callable[..., Any]:
    """Runs a function only once."""
    results: dict[Any, Callable[..., Any]] = {}

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if func not in results:
            results[func] = func(*args, **kwargs)
        return results[func]

    return wrapper


@once
def get_date() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


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

try:
    remain = float(re.findall((r"(-?\d+(\.\d+)?)度"), response.text)[0][0])
    logging.info(f"剩余电量：{remain}")
except Exception as e:
    logging.exception(e)
    logging.error("剩余电量获取失败，response: " + response.text)
    exit(1)

originstring = "[]"

# read from data.js preprocessed as json
with suppress(FileNotFoundError):
    with open("data.js", "r", encoding="utf-8") as f:
        originstring = f.read().lstrip("data=")
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
