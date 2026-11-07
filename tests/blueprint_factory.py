def valid_blueprint_data(episode_count: int = 3) -> dict:
    episodes = []
    for number in range(1, episode_count + 1):
        episodes.append(
            {
                "number": number,
                "objective": f"推进第 {number} 集",
                "conflict": "主播必须在真相与流量之间选择",
                "character_ids": ["anchor", "rival"],
                "required_events": ["出现新的直播证据"],
                "cliffhanger": "幕后账号突然上线" if number < episode_count else None,
                "resolution": "证据公开，直播事故得到收束" if number == episode_count else None,
                "choices": [
                    {
                        "id": f"e{number}_truth",
                        "text": "立即公开证据",
                        "intent": "选择真相",
                        "effects": [{"metric_id": "reputation", "delta": 12}],
                        "consequence_hint": "短期争议上升但获得信任",
                    },
                    {
                        "id": f"e{number}_traffic",
                        "text": "顺势制造悬念",
                        "intent": "选择流量",
                        "effects": [
                            {"metric_id": "reputation", "delta": -8},
                            {"metric_id": "mindset", "delta": -5},
                        ],
                        "consequence_hint": "热度上升但心态受损",
                    },
                ],
            }
        )
    return {
        "title": "麦克风没有关",
        "logline": "一名小主播因误开全队麦卷入舆论风暴。",
        "genre": "直播职场",
        "theme": "真相与流量",
        "episode_count": episode_count,
        "characters": [
            {
                "id": "anchor",
                "name": "阿川",
                "role": "新人主播",
                "goal": "保住直播事业",
                "secret": "保存了完整录音",
                "personality": ["冲动", "讲义气"],
            },
            {
                "id": "rival",
                "name": "老K",
                "role": "竞争主播",
                "goal": "抢走流量",
                "secret": "参与了恶意剪辑",
                "personality": ["精明"],
            },
        ],
        "metrics": [
            {
                "id": "reputation",
                "name": "观众口碑",
                "description": "观众对主播的信任",
                "initial_value": 50,
                "low_label": "全网质疑",
                "high_label": "获得信任",
            },
            {
                "id": "mindset",
                "name": "主播心态",
                "description": "面对压力时的稳定程度",
                "initial_value": 50,
                "low_label": "濒临失控",
                "high_label": "冷静坚定",
            },
        ],
        "episodes": episodes,
        "endings": [
            {
                "id": "quit",
                "title": "黯然退网",
                "summary": "主播失去信任并选择离开。",
                "category": "low",
                "conditions": [{"metric_id": "reputation", "operator": "lt", "value": 30}],
                "priority": 1,
            },
            {
                "id": "comeback",
                "title": "逆风翻盘",
                "summary": "真相带来长期信任。",
                "category": "high",
                "conditions": [{"metric_id": "reputation", "operator": "gte", "value": 70}],
                "priority": 2,
            },
            {
                "id": "survive",
                "title": "带伤前行",
                "summary": "主播保住工作但付出代价。",
                "category": "mixed",
                "conditions": [
                    {"metric_id": "reputation", "operator": "gte", "value": 30},
                    {"metric_id": "reputation", "operator": "lt", "value": 70},
                ],
                "priority": 3,
            },
        ],
    }
