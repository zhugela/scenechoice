import json

from app.schemas.story_blueprint import StoryBlueprint


SYSTEM_PROMPT = """你是互动短剧的故事规划 Agent。只输出符合 JSON Schema 的单个 JSON 对象，不要 Markdown。
规则：完整规划指定集数；每集两个有实质差异的选择；规则决定状态变化；最终集收束主冲突；结局必须含 low、high、mixed 且条件可达。
所有 id 使用稳定的英文小写 snake_case。内容使用简体中文。"""


def initial_messages(inspiration: str, episode_count: int) -> list[dict[str, str]]:
    schema = json.dumps(StoryBlueprint.model_json_schema(), ensure_ascii=False)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"用户灵感：{inspiration}\n集数：{episode_count}\n严格遵循此 JSON Schema：{schema}",
        },
    ]


def repair_messages(
    original_messages: list[dict[str, str]], previous_output: str, issues: list[str]
) -> list[dict[str, str]]:
    safe_output = previous_output[:12000]
    return original_messages + [
        {"role": "assistant", "content": safe_output},
        {
            "role": "user",
            "content": "上次输出未通过校验。修复全部问题并只返回完整 JSON：\n- " + "\n- ".join(issues[:30]),
        },
    ]
