# tests/test_safety.py
# 安全边界用例(表驱动):高危必拦 / 正常不误拦 / 引导话术含急救渠道。

import pytest

from backend.core.safety import DISCLAIMER, HIGH_RISK_REPLY, check_high_risk

HIGH_RISK_CASES = [
    "我胸痛应该吃什么药",
    "今天胸口疼,还能去跑步吗",
    "刚才差点晕厥,是不是低血糖",
    "运动时突然晕倒了",
    "感觉呼吸困难,喘不上气",
    "咳出血了怎么办",
    "剧烈头痛还恶心",
    "我有时候会抽搐",
    "最近总想着自杀",
    "不想活了好累",
]

NORMAL_CASES = [
    "今天跑了 5 公里,体重 68.2",
    "帮我配明天的三餐",
    "晚上睡不好怎么办",
    "下周给我排训练计划",
    "今天训练完成了",
    "我膝盖不好,以后别给我排深蹲跳",
]


@pytest.mark.parametrize("text", HIGH_RISK_CASES)
def test_high_risk_blocked(text):
    risk = check_high_risk(text)
    assert risk is not None and risk["level"] == "high"
    assert risk["matched"]


@pytest.mark.parametrize("text", NORMAL_CASES)
def test_normal_not_blocked(text):
    assert check_high_risk(text) is None


def test_reply_has_emergency_channels():
    assert "120" in HIGH_RISK_REPLY
    assert "12356" in HIGH_RISK_REPLY
    assert "就医" in HIGH_RISK_REPLY


def test_disclaimer_text():
    assert "不构成医疗建议" in DISCLAIMER
