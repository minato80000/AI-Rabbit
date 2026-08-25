"""CoreS3 との接続。`transport.link` で繋ぎ方を選ぶ。

プロトコルは3通りとも同じで、違うのは電波の親機と WebSocket の向きだけ。

| link | 親機（電波を出す） | WebSocket | ルータ | PC のネット |
|---|---|---|---|---|
| `router`   | 家の WiFi ルータ | PC が待つ | **要る** | 保てる |
| `hotspot`  | PC             | PC が待つ | 不要 | 保てる |
| `robot-ap` | CoreS3         | PC が繋ぐ | 不要 | **落ちる** |

ファーム側（`firmware/src/config.h` の `LINK_MODE`）と揃えること。
選び方は docs/wireless-link.md。
"""
from __future__ import annotations

from .client import RabbitClient
from .link import RabbitLink
from .server import RabbitServer

__all__ = [
    "RabbitClient", "RabbitLink", "RabbitServer",
    "build_link", "normalize_link", "LINK_MODES",
]

# 表記ゆれを吸収する。ファーム側の LINK_MODE と同じ名前で書けるように
_ALIASES = {
    "router": "router",
    "wifi": "router",
    "lan": "router",
    "hotspot": "hotspot",
    "pc-ap": "hotspot",
    "robot-ap": "robot-ap",
    "robot_ap": "robot-ap",
    "ap": "robot-ap",
    "softap": "robot-ap",
}

LINK_MODES = ("router", "hotspot", "robot-ap")


def normalize_link(name: str | None) -> str:
    key = str(name or "router").strip().lower()
    if key not in _ALIASES:
        raise ValueError(
            f"transport.link は {' / '.join(LINK_MODES)} のいずれか: {name!r}"
        )
    return _ALIASES[key]


def build_link(cfg: dict) -> RabbitLink:
    """設定から接続を組み立てる。start() は呼ばない。"""
    tcfg = cfg.get("transport", {})
    mode = normalize_link(tcfg.get("link"))

    if mode == "robot-ap":
        # ロボットが親機。繋ぎ先は ESP32 SoftAP のゲートウェイで固定
        return RabbitClient(
            host=tcfg.get("core_host", "192.168.4.1"),
            port=tcfg.get("port", 8765),
            path=tcfg.get("path", "/rabbit"),
            sample_rate=24000,
            chunk_ms=tcfg.get("chunk_ms", 20),
        )

    # router / hotspot はどちらも PC が待ち受ける
    return RabbitServer(
        host=tcfg.get("host", "0.0.0.0"),
        port=tcfg.get("port", 8765),
        path=tcfg.get("path", "/rabbit"),
        sample_rate=24000,
        chunk_ms=tcfg.get("chunk_ms", 20),
    )
