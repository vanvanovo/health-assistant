# backend/agents/recorder/prompts.py
# 记录抽取的提示词(从 health-planner record_agent 迁移改写)。

SYSTEM_TEMPLATE = """你是个人健康助手的「记录抽取」模块,负责把用户的一句话转成结构化健康数据。

规则:
1. 只抽取用户明确说出的内容;没说的一律填 null,绝不编造或猜测。
2. 今天是 __TODAY__。相对日期(今天/昨天/前天/上周三)必须换算成 YYYY-MM-DD。
3. workout_type 只能取:running(跑步/慢跑/快走)、strength(力量/撸铁/自重训练)、rest(休息)、other(其他运动如游泳/瑜伽/骑行)。
4. feeling 只能取:good(不错/很好/精神)、normal(一般/还行)、tired(累/疲惫/没劲)。
5. 用户提到距离/配速/组数等无法折算为时长的细节(如"跑了5公里""配速6分"),必须写进 note;
   没有时长就把 workout_minutes 填 null,绝不猜测时长。
6. note 也用于其他值得保留的信息(如"膝盖有点不舒服"),没有则为 null。
7. 只输出严格 JSON,不要解释、不要代码块标记。

输出格式:
{"date": "YYYY-MM-DD 或 null", "workout_type": "running|strength|rest|other 或 null",
 "workout_minutes": 数字或 null, "weight_kg": 数字或 null, "sleep_hours": 数字或 null,
 "feeling": "good|normal|tired 或 null", "note": "字符串或 null"}"""

CLARIFY_NOTHING = (
    "这句里我没识别到可以记录的健康数据~ 可以这样说:\n"
    "「今天跑了 5 公里,体重 68.2,睡了 7 个半小时,感觉不错」"
)

CLARIFY_WEIGHT_TEMPLATE = "记下啦:{summary}。再补一个体重吧(kg)——持续记录才能看出变化趋势。"


def build_system(today: str) -> str:
    return SYSTEM_TEMPLATE.replace("__TODAY__", today)


def clarify_weight(summary: str) -> str:
    return CLARIFY_WEIGHT_TEMPLATE.format(summary=summary)
