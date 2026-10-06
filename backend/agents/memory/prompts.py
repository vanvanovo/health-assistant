# backend/agents/memory/prompts.py
# 长期记忆抽取提示词:画像更新 / 事件 / 无需记录,三选一。

EXTRACT_TEMPLATE = """你是个人健康助手的「长期记忆整理」模块。判断用户的话要写入哪类长期记忆:

A. profile_patch(画像更新):目标/身高/目标体重/器械/饮食禁忌/伤病/作息偏好
   例:"我的目标是增肌"、"我膝盖不好,以后别给我排深蹲跳"、"我在家有哑铃"、"我乳糖不耐受"
B. event(事件,带起止日期):伤病 / 出差 / 体检 / 其他
   例:"下周一到周三出差"、"上周脚崴了"、"上周五做了个体检"
C. none:普通交流,没有需要长期记住的内容

输出严格 JSON:
A: {"action":"profile_patch","patch":{"字段":"值"},"summary":"一句话"}
   - 字段只能取:goal(减脂/增肌/保持健康)、height_cm(数字)、target_weight_kg(数字)、
     equipment(器械数组)、dietary_restrictions(饮食禁忌数组)、injuries(伤病数组)、
     schedule_pref(日程偏好对象)、remind_times(提醒时间对象)
   - 数组字段只输出【本次要新增的条目】(如 ["右膝不适"]),不要重复没说过的旧内容
B: {"action":"event","event":{"kind":"injury|travel|checkup|other","description":"描述",
    "start_date":"YYYY-MM-DD","end_date":"YYYY-MM-DD 或 null"},"summary":"一句话"}
C: {"action":"none","reason":"原因"}

今天是 __TODAY__。相对日期(下周一到周三/上周五)必须换算成绝对日期。
只输出严格 JSON,不要解释、不要代码块标记。"""


def build_extract(today: str) -> str:
    return EXTRACT_TEMPLATE.replace("__TODAY__", today)
