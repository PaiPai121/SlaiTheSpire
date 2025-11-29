import numpy as np
import zlib

# --- 特征维度计算 v3.0 ---
# 1. 玩家: 9个 (基础+状态)
# 2. 手牌: 10张 * 5特征 = 50个
# 3. 怪物: 5只 * 5特征 (原4个 + 1个HashID) = 25个
# 4. [新增] 遗物: 最多看前 10 个遗物 * 1个HashID = 10个
# 5. [新增] 抽牌堆/弃牌堆统计: 20个 (预留一些统计信息)
# 这里为了简单，我们先只加怪物ID和遗物ID
# 总计: 9 + 50 + 25 + 10 = 94
# 为了以后扩展方便，直接开到 120 吧，多余的填 0 没影响
OBSERVATION_SIZE = 120

def get_power_amount(powers, power_id):
    if not powers: return 0
    for p in powers:
        if p['id'] == power_id: return p['amount']
    return 0

def hash_string(text):
    """通用的字符串哈希函数"""
    if not text: return 0.0
    # 归一化到 [-1, 1]
    return (zlib.crc32(text.encode('utf-8')) / (2**32)) * 2.0 - 1.0

def encode_state(state):
    obs = np.zeros(OBSERVATION_SIZE, dtype=np.float32)
    
    if not state or 'game_state' not in state:
        return obs

    game_state = state['game_state']
    combat_state = game_state.get('combat_state', {})
    player = combat_state.get('player', {})
    
    # --- 1. 玩家信息 (0-8) ---
    obs[0] = player.get('current_hp', 0)
    obs[1] = player.get('max_hp', 80)
    obs[2] = player.get('energy', 0)
    obs[3] = player.get('block', 0)
    
    powers = player.get('powers', [])
    obs[4] = get_power_amount(powers, 'Strength')
    obs[5] = get_power_amount(powers, 'Dexterity')
    obs[6] = get_power_amount(powers, 'Vulnerable')
    obs[7] = get_power_amount(powers, 'Weak')
    obs[8] = get_power_amount(powers, 'Frail')

    # --- 2. 手牌信息 (9-58) ---
    hand = combat_state.get('hand', [])
    for i in range(10):
        base_idx = 9 + (i * 5)
        if i < len(hand):
            card = hand[i]
            obs[base_idx] = card.get('cost', 0)
            card_type = card.get('type', 'UNKNOWN')
            obs[base_idx + 1] = 1.0 if card_type == 'ATTACK' else 0.0
            obs[base_idx + 2] = 1.0 if card_type == 'SKILL' else 0.0
            obs[base_idx + 3] = 1.0 if card_type == 'POWER' else 0.0
            obs[base_idx + 4] = hash_string(card.get('id', ''))
        else:
            obs[base_idx:base_idx+5] = 0

    # --- 3. 怪物信息 (59-83) ---
    # [新增] 怪物 ID 哈希
    monsters = combat_state.get('monsters', [])
    for i in range(5):
        base_idx = 59 + (i * 5) # 步长变成 5
        if i < len(monsters):
            m = monsters[i]
            if not m.get('is_gone') and not m.get('half_dead'):
                obs[base_idx] = m.get('current_hp', 0)
                obs[base_idx + 1] = m.get('block', 0)
                intent = m.get('intent', 'NONE')
                obs[base_idx + 2] = 1.0 if 'ATTACK' in intent else 0.0
                dmg = m.get('move_adjusted_damage', 0)
                if obs[base_idx + 2] == 0 or dmg < 0: dmg = 0
                obs[base_idx + 3] = dmg
                
                # [关键] 怪物身份 ID！
                # 这样 AI 就能区分 咔咔(Cultist) 和 虱子(Louse) 了
                obs[base_idx + 4] = hash_string(m.get('id', ''))
            else:
                obs[base_idx:base_idx+5] = 0
        else:
            obs[base_idx:base_idx+5] = 0

    # --- 4. 遗物信息 (84-93) ---
    # [新增] 读取前 10 个遗物
    relics = game_state.get('relics', [])
    for i in range(10):
        if i < len(relics):
            # 记录遗物 ID
            obs[84 + i] = hash_string(relics[i].get('id', ''))
        else:
            obs[84 + i] = 0

    # --- 5. 牌堆宏观统计 (94-119) ---
    # 简单的统计：抽牌堆有多少张牌，弃牌堆有多少张牌
    draw_pile = combat_state.get('draw_pile', [])
    discard_pile = combat_state.get('discard_pile', [])
    # 辅助函数：统计特定类型的牌有多少张
    def count_types(pile):
        atk = len([c for c in pile if c.get('type') == 'ATTACK'])
        skill = len([c for c in pile if c.get('type') == 'SKILL'])
        power = len([c for c in pile if c.get('type') == 'POWER'])
        status = len([c for c in pile if c.get('type') == 'STATUS']) # 状态牌(晕眩/伤口)
        curse = len([c for c in pile if c.get('type') == 'CURSE'])   # 诅咒牌
        return [atk, skill, power, status, curse]

    # 提取特征
    draw_stats = count_types(draw_pile)     # 返回 5 个数字
    discard_stats = count_types(discard_pile) # 返回 5 个数字
    
    # 填入 obs (假设从索引 94 开始)
    # 抽牌堆信息
    obs[94] = len(draw_pile)
    obs[95:100] = draw_stats # 填入5个统计值
    
    # 弃牌堆信息
    obs[100] = len(discard_pile)
    obs[101:106] = discard_stats
    # 剩下的位置留空，未来可以加具体统计（如牌堆里有几张攻击牌）

    return obs