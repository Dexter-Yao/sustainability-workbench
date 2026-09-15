# ABOUTME: matplotlib 图表中文字体统一配置——项目字体目录优先注册，再按系统候选名回退，供各图表渲染器共享。
# ABOUTME: 唯一 owner 是本模块；matrix_chart/metric_summary_chart 均调用此处，不得各自维护字体逻辑副本。
# ABOUTME(en): Single configuration of the Chinese matplotlib chart font — registers the project font dir, then falls
# ABOUTME(en): back to system candidates. Sole owner: matrix_chart and metric_summary_chart call here, never fork it.
from __future__ import annotations

import logging
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402 — 必须在 use("Agg") 之后导入
from matplotlib import font_manager  # noqa: E402

logger = logging.getLogger(__name__)

# 中文字体：项目内 data/fonts 优先加载，其后按系统常见中文字体名回退（杜绝方框/乱码）。
_FONTS_DIR = Path(__file__).resolve().parents[3] / "data" / "fonts"
_FONT_CANDIDATES = [
    "Source Han Sans SC",
    "Noto Sans CJK SC",
    "Songti SC",
    "STSong",
    "Heiti SC",
    "STHeiti",
    "PingFang SC",
    "Microsoft YaHei",
    "WenQuanYi Micro Hei",
    "Arial Unicode MS",
    "Hiragino Sans GB",
]


def configure_chart_font() -> str | None:
    """配置中文字体：项目字体目录优先注册，再按候选名回退；均无则告警（中文将显示为方框）。"""
    if _FONTS_DIR.is_dir():
        for font_file in sorted([*_FONTS_DIR.glob("*.ttf"), *_FONTS_DIR.glob("*.otf")]):
            try:
                font_manager.fontManager.addfont(str(font_file))
            except Exception:  # noqa: BLE001 — 单个字体损坏不应阻断渲染
                logger.warning("图表字体加载失败：%s", font_file.name)
    available = {f.name for f in font_manager.fontManager.ttflist}
    chosen = next((name for name in _FONT_CANDIDATES if name in available), None)
    if chosen:
        plt.rcParams["font.sans-serif"] = [chosen, *plt.rcParams.get("font.sans-serif", [])]
    else:
        logger.warning("未找到中文字体，图表中文可能显示为方框；请在 backend/data/fonts 放置中文字体文件。")
    plt.rcParams["axes.unicode_minus"] = False
    return chosen
