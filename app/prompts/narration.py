"""Prompts for the player-facing narration.

The context object is built by :mod:`app.services.narrator`; this module only
decides how it reaches the model. Two rules are load-bearing and are repeated
here so a future edit cannot silently drop them:

* Character ``secret`` values never enter this module. The context carries
  names and roles only, because the narrator speaks before the player has
  unlocked the secret.
* Metric changes arrive as semantic phrases (``观众口碑明显上升``), never as
  numbers. The model is told to write consequences, not read out the state
  machine.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.narrator import NarrationContext


SYSTEM_PROMPT = """你是互动短剧的旁白。玩家刚刚从两个选项里做了一个选择，请写出这个选择带来的下一段情节。
硬性要求：
1. 只输出纯文本。不要 Markdown，不要代码围栏，不要 JSON，不要标题，不要用引号包裹整段文字。
2. 120～400 个汉字。太短没有信息量，太长玩家不会读。
3. 用第二人称「你」描写玩家刚才的选择带来了什么，落到具体动作、对白或环境。
4. 不要复述数字，不要出现「指标」「数值」「+10」这类游戏系统词。
5. 只使用给定的人物名字与身份，不要编造或提前揭示任何人物尚未公开的秘密。"""


def build_messages(context: "NarrationContext") -> list[dict[str, str]]:
    """Render one narration request from already-redacted context."""
    character_lines = "\n".join(
        f"- {character.name}（{character.role}）" for character in context.characters
    )
    if context.metric_shifts:
        shift_lines = "\n".join(
            f"- {shift.description}" for shift in context.metric_shifts
        )
    else:
        shift_lines = "- 这一选择没有带来明显变化"

    user_content = (
        f"故事标题：{context.title}\n"
        f"类型：{context.genre}\n"
        f"主题：{context.theme}\n"
        f"第 {context.episode_number} 集目标：{context.episode_objective}\n"
        f"本集冲突：{context.episode_conflict}\n"
        f"出场人物（只可用这些名字与身份）：\n{character_lines}\n"
        f"玩家刚才的选择：{context.choice_text}\n"
        f"这一步的后果提示：{context.consequence_hint}\n"
        f"状态变化（只可这样理解，不要写数值）：\n{shift_lines}\n\n"
        "请写一段旁白，从玩家做出选择的那一刻接着往下写。"
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def repair_messages(
    base_messages: list[dict[str, str]],
    previous_output: str,
    issues: list[str],
) -> list[dict[str, str]]:
    """Ask for a rewrite, naming every reason the previous text was rejected."""
    return base_messages + [
        # Truncate so a runaway reply cannot turn every repair into a larger
        # prompt than the one before it.
        {"role": "assistant", "content": previous_output[:4000]},
        {
            "role": "user",
            "content": (
                "上一段旁白没有通过校验，问题如下：\n- "
                + "\n- ".join(issues[:10])
                + "\n请按硬性要求重写，只输出纯文本。"
            ),
        },
    ]
