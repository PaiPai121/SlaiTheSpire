from spire_env.definitions import ActionIndex

class ActionMapper:
    def __init__(self):
        pass

    def get_mask(self, state):
        """
        计算当前状态下的合法动作掩码
        """
        mask = [False] * ActionIndex.TOTAL_ACTIONS
        if not state: return mask
        
        cmds = state.get('available_commands', [])
        game = state.get('game_state', {})
        
        # --- 场景 A: 战斗 ---
        if 'play' in cmds:
            combat = game.get('combat_state', {})
            hand = combat.get('hand', [])
            energy = combat.get('player', {}).get('energy', 0)
            
            # 1. 卡牌 (0-9)
            for i in range(len(hand)):
                if i <= ActionIndex.CARD_END:
                    c = hand[i]
                    cost = c.get('cost', 0)
                    # 规则：能量够 + 不是诅咒 + 游戏允许
                    req = cost if cost >= 0 else 0
                    if c.get('is_playable') and cost != -2 and energy >= req:
                        mask[i] = True
            
            # 2. 结束回合 (10) - 永远开放
            if 'end' in cmds: 
                mask[ActionIndex.END_TURN] = True
            
            # 3. 药水 (11-13)
            pots = game.get('potions', [])
            for i in range(len(pots)):
                idx = ActionIndex.POTION_START + i
                if idx <= ActionIndex.POTION_END and pots[i].get('can_use'):
                    mask[idx] = True

        # --- 场景 B: 选择 (商店/事件) ---
        elif 'choose' in cmds:
            choices = game.get('choice_list', [])
            # 开放对应数量的选项
            for i in range(len(choices)):
                if i <= ActionIndex.CARD_END:
                    mask[i] = True
            
            # 允许离开/取消 (动作10)
            if any(c in cmds for c in ['leave', 'cancel', 'return', 'proceed', 'skip', 'confirm']):
                mask[ActionIndex.END_TURN] = True
            
            # 保底
            if not any(mask): mask[0] = True

        # --- 场景 C: 纯过场 ---
        elif any(c in cmds for c in ['proceed', 'confirm', 'leave', 'skip', 'return', 'start']):
            mask[0] = True
        
        # --- 兜底 ---
        else:
            mask[ActionIndex.END_TURN] = True

        return mask

    def decode_action(self, action, state):
        """
        将数字动作翻译为游戏指令字符串
        """
        if not state: return None
        cmds = state.get('available_commands', [])
        combat = state.get('game_state', {}).get('combat_state', {})
        
        # 1. 结束回合 (最高优先级)
        if action == ActionIndex.END_TURN and 'end' in cmds: 
            return "end"
        
        # 2. 战斗指令
        if 'play' in cmds:
            # 药水
            if ActionIndex.POTION_START <= action <= ActionIndex.POTION_END:
                return f"potion {action - ActionIndex.POTION_START} 0"
            
            # 打牌
            if action <= ActionIndex.CARD_END:
                hand = combat.get('hand', [])
                if action >= len(hand): return None
                
                # 智能目标选择
                card = hand[action]
                target = 0
                if card.get('has_target'):
                    monsters = combat.get('monsters', [])
                    for i, m in enumerate(monsters):
                        if not m.get('is_gone') and not m.get('half_dead'):
                            target = i; break
                    return f"play {action+1} {target}"
                return f"play {action+1}"

        # 3. 选择指令
        if 'choose' in cmds:
            if action == ActionIndex.END_TURN:
                for c in ['confirm', 'leave', 'return', 'cancel', 'proceed', 'skip']:
                    if c in cmds: return c
                return "state"
            return f"choose {action}"

        # 4. 过场指令
        for c in ['proceed', 'confirm', 'leave', 'skip', 'return', 'start']:
            if c in cmds: return c
            
        if action == ActionIndex.END_TURN: return "state"
        return None

    def get_action_name(self, action, state):
        """
        获取动作的人类可读描述
        """
        if not state: return f"未知 ({action})"
        cmds = state.get('available_commands', [])
        is_combat = 'play' in cmds or 'end' in cmds
        
        if is_combat:
            if action == ActionIndex.END_TURN: return "【结束回合】"
            if ActionIndex.POTION_START <= action <= ActionIndex.POTION_END:
                return f"药水 {action - ActionIndex.POTION_START}"
            try:
                hand = state['game_state']['combat_state']['hand']
                if action < len(hand): return f"打出: {hand[action].get('name')}"
            except: pass
            return f"战斗操作 {action}"
            
        if action == ActionIndex.END_TURN: return "【离开/继续】"
        if 'choose' in cmds:
            try:
                c = state['game_state']['choice_list'][action]
                return f"选择: {str(c)[:15]}"
            except: pass
        return f"交互 {action}"