from spire_env.definitions import ActionConfig

class ActionMapper:
    def __init__(self):
        self.cfg = ActionConfig

    def get_mask(self, state):
        """
        [精准掩码 V2]
        根据 ActionConfig (67维) 生成合法动作掩码。
        能够区分指向性卡牌和非指向性卡牌。
        """
        mask = [False] * self.cfg.TOTAL_ACTIONS
        if not state: return mask
        
        cmds = state.get('available_commands', [])
        game = state.get('game_state', {})
        
        # --- 场景 A: 战斗 (Combat) ---
        if 'play' in cmds:
            combat = game.get('combat_state', {})
            hand = combat.get('hand', [])
            monsters = combat.get('monsters', [])
            player = combat.get('player', {})
            energy = player.get('energy', 0)
            
            # 1. 检查特殊状态 (缠身 Entangled)
            is_entangled = False
            for p in player.get('powers', []):
                if p.get('id') == 'Entangled':
                    is_entangled = True; break
            
            # 2. 遍历手牌 (0-9)
            for i, card in enumerate(hand):
                if i >= self.cfg.MAX_HAND_CARDS: break
                
                # 基础检查：能量够 + 游戏允许打出
                cost = card.get('cost', 0)
                req_cost = cost if cost >= 0 else 0
                if not card.get('is_playable') or cost == -2 or energy < req_cost:
                    continue
                
                # 特殊检查：缠身不能打攻击
                if is_entangled and card.get('type') == 'ATTACK':
                    continue
                
                # 特殊检查：交锋 (Clash)
                if card.get('id') == 'Clash':
                    has_non_attack = any(c.get('type') != 'ATTACK' for c in hand)
                    if has_non_attack: continue

                # --- 目标处理逻辑 ---
                base_idx = i * self.cfg.MAX_MONSTERS
                has_target = card.get('has_target', False)
                
                if has_target:
                    # 指向性卡牌：激活所有活着的怪物对应的动作
                    for m_idx, m in enumerate(monsters):
                        if m_idx >= self.cfg.MAX_MONSTERS: break
                        # 只有怪活着且不是半死状态，才能选为目标
                        if not m.get('is_gone') and not m.get('half_dead'):
                            mask[base_idx + m_idx] = True
                else:
                    # 非指向性卡牌 (AOE/能力/自身Buff)：
                    # 只激活 [Target 0] 作为默认动作，其他 Target 屏蔽
                    # 这样 AI 只有 1 个选项，不会产生歧义
                    mask[base_idx + 0] = True
            
            # 3. 药水 (50-64)
            potions = game.get('potions', [])
            for i, pot in enumerate(potions):
                if i >= self.cfg.MAX_POTIONS: break
                if not pot.get('can_use'): continue
                if pot.get('id') == 'Potion Slot': continue
                
                base_idx = self.cfg.POTION_ACTION_START + (i * self.cfg.MAX_MONSTERS)
                requires_target = pot.get('requires_target', False)
                
                if requires_target:
                    for m_idx, m in enumerate(monsters):
                        if m_idx >= self.cfg.MAX_MONSTERS: break
                        if not m.get('is_gone') and not m.get('half_dead'):
                            mask[base_idx + m_idx] = True
                else:
                    mask[base_idx + 0] = True
            
            # 4. 结束回合 (65)
            if 'end' in cmds:
                mask[self.cfg.END_TURN_IDX] = True

        # --- 场景 B: 选择 (Choice) ---
        elif 'choose' in cmds:
            choices = game.get('choice_list', [])
            # 复用卡牌动作的前 N 个位置
            # Action 0 -> choose 0, Action 1 -> choose 1 ...
            for i in range(len(choices)):
                if i < self.cfg.TOTAL_ACTIONS:
                    mask[i] = True
            
            # 允许取消/跳过
            prio_cmds = ['cancel', 'leave', 'return', 'proceed', 'skip', 'confirm']
            if any(c in cmds for c in prio_cmds):
                mask[self.cfg.END_TURN_IDX] = True
                mask[self.cfg.CANCEL_IDX] = True

        # --- 场景 C: 纯过场 ---
        elif any(c in cmds for c in ['proceed', 'confirm', 'leave', 'skip', 'return', 'start']):
            mask[self.cfg.END_TURN_IDX] = True
            if 'return' in cmds or 'cancel' in cmds:
                mask[self.cfg.CANCEL_IDX] = True
        
        else:
            # 兜底：如果卡住了，允许点 END_TURN 尝试刷新
            mask[self.cfg.END_TURN_IDX] = True

        return mask

    def decode_action(self, action, state):
        """
        将 0-66 的数字翻译回游戏指令
        """
        if not state: return "state"
        cmds = state.get('available_commands', [])
        
        # 1. 通用指令 (End/Confirm)
        if action == self.cfg.END_TURN_IDX:
            for c in ['end', 'confirm', 'proceed', 'leave', 'skip', 'start', 'next']:
                if c in cmds: return c
            return "state"
            
        # 2. 取消指令 (Cancel)
        if action == self.cfg.CANCEL_IDX:
            for c in ['cancel', 'return', 'leave']:
                if c in cmds: return c
            return "state"

        # 3. 战斗指令
        if 'play' in cmds:
            # --- 卡牌 (0-49) ---
            if action < self.cfg.CARD_ACTION_SIZE:
                card_idx = action // self.cfg.MAX_MONSTERS
                target_idx = action % self.cfg.MAX_MONSTERS
                
                # 越界检查
                hand = state['game_state']['combat_state']['hand']
                if card_idx >= len(hand): return None
                
                card = hand[card_idx]
                if card.get('has_target'):
                    return f"play {card_idx + 1} {target_idx}"
                else:
                    # 不需要目标的卡，忽略 target_idx，直接打出
                    return f"play {card_idx + 1}"
            
            # --- 药水 (50-64) ---
            if self.cfg.POTION_ACTION_START <= action < self.cfg.END_TURN_IDX:
                offset = action - self.cfg.POTION_ACTION_START
                potion_idx = offset // self.cfg.MAX_MONSTERS
                target_idx = offset % self.cfg.MAX_MONSTERS
                
                return f"potion use {potion_idx} {target_idx}"

        # 4. 选择指令 (复用低位 Action ID)
        if 'choose' in cmds:
            # 简单映射：Action 0 -> choose 0
            # 注意：这可能会和 Card Action 混淆，但由 mask 保证唯一性
            return f"choose {action}"

        return "state"
    
    def get_action_name(self, action, state):
        """调试用：显示人类可读的动作名"""
        if action == self.cfg.END_TURN_IDX: return "【继续/结束】"
        if action == self.cfg.CANCEL_IDX: return "【取消/返回】"
        
        if action < self.cfg.CARD_ACTION_SIZE:
            c_idx = action // self.cfg.MAX_MONSTERS
            t_idx = action % self.cfg.MAX_MONSTERS
            try:
                c_name = state['game_state']['combat_state']['hand'][c_idx]['name']
                return f"打出: {c_name} (目标{t_idx})"
            except:
                return f"卡牌 {c_idx} (目标{t_idx})"
                
        if action < self.cfg.END_TURN_IDX:
            offset = action - self.cfg.POTION_ACTION_START
            p_idx = offset // self.cfg.MAX_MONSTERS
            return f"药水 {p_idx} (目标{offset % self.cfg.MAX_MONSTERS})"
            
        return f"未知 ({action})"