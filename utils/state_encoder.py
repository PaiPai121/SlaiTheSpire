import numpy as np
import zlib
from spire_env.definitions import ObservationConfig
# --- 特征维度计算 v3.0 ---
# 1. 玩家: 9个 (基础+状态)
# 2. 手牌: 10张 * 5特征 = 50个
# 3. 怪物: 5只 * 5特征 (原4个 + 1个HashID) = 25个
# 4. [新增] 遗物: 最多看前 10 个遗物 * 1个HashID = 10个
# 5. [新增] 抽牌堆/弃牌堆统计: 20个 (预留一些统计信息)
# 这里为了简单，我们先只加怪物ID和遗物ID
# 总计: 9 + 50 + 25 + 10 = 94
# 为了以后扩展方便，直接开到 120 吧，多余的填 0 没影响
OBSERVATION_SIZE = ObservationConfig.SIZE

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

    # --- 2. 手牌信息 (9-68) ---
    # [新增] "是否升级" 特征
    hand = combat_state.get('hand', [])
    for i in range(10):
        base_idx = 9 + (i * 6) # 步长变成 6
        if i < len(hand):
            card = hand[i]
            obs[base_idx] = card.get('cost', 0)
            
            card_type = card.get('type', 'UNKNOWN')
            obs[base_idx + 1] = 1.0 if card_type == 'ATTACK' else 0.0
            obs[base_idx + 2] = 1.0 if card_type == 'SKILL' else 0.0
            obs[base_idx + 3] = 1.0 if card_type == 'POWER' else 0.0
            
            # 哈希ID
            obs[base_idx + 4] = hash_string(card.get('id', ''))
            
            # [新增] 是否升级 (Upgraded)
            # 游戏里 upgrades > 0 代表是 +1 牌
            obs[base_idx + 5] = 1.0 if card.get('upgrades', 0) > 0 else 0.0
        else:
            obs[base_idx:base_idx+6] = 0
            
    # --- 3. 怪物信息 (69-93) ---
    monsters = combat_state.get('monsters', [])
    for i in range(5):
        base_idx = 69 + (i * 5)
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
                obs[base_idx + 4] = hash_string(m.get('id', ''))
            else:
                obs[base_idx:base_idx+5] = 0
        else:
            obs[base_idx:base_idx+5] = 0

    # --- 4. 遗物信息 (94-103) ---
    relics = game_state.get('relics', [])
    for i in range(10):
        if i < len(relics):
            obs[94 + i] = hash_string(relics[i].get('id', ''))
        else:
            obs[94 + i] = 0

    # --- 5. 牌堆统计 (104-115) ---
    draw_pile = combat_state.get('draw_pile', [])
    discard_pile = combat_state.get('discard_pile', [])
    
    def count_types(pile):
        atk = len([c for c in pile if c.get('type') == 'ATTACK'])
        skill = len([c for c in pile if c.get('type') == 'SKILL'])
        power = len([c for c in pile if c.get('type') == 'POWER'])
        status = len([c for c in pile if c.get('type') == 'STATUS'])
        curse = len([c for c in pile if c.get('type') == 'CURSE'])
        return [atk, skill, power, status, curse]

    draw_stats = count_types(draw_pile)
    discard_stats = count_types(discard_pile)
    
    obs[104] = len(draw_pile)
    obs[105:110] = draw_stats
    obs[110] = len(discard_pile)
    obs[111:116] = discard_stats

    # --- 6. [新增] 宏观信息 (116-117) ---
    # 金币 (归一化)
    obs[116] = game_state.get('gold', 0) / 2000.0 
    # 层数 (归一化，最高50层)
    obs[117] = game_state.get('floor', 0) / 50.0

    # --- 7. [新增] 药水栏 (118-120) ---
    # 简单记录有没有药水，未来可以扩充药水ID
    potions = game_state.get('potions', [])
    for i in range(3):
        if i < len(potions):
            # 只要不是 "Potion Slot" (空位)，就算有药
            has_potion = 1.0 if potions[i].get('id') != 'Potion Slot' else 0.0
            obs[118 + i] = has_potion
        else:
            obs[118 + i] = 0.0


    return obs