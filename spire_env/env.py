import numpy as np
import time
import gymnasium as gym
from gymnasium import spaces
from .interface import Connection
from utils.state_encoder import encode_state, OBSERVATION_SIZE

class SlayTheSpireEnv(gym.Env):
    def __init__(self):
        super(SlayTheSpireEnv, self).__init__()
        self.conn = Connection()
        self.action_space = spaces.Discrete(14)
        self.observation_space = spaces.Box(low=-1.0, high=1000.0, shape=(OBSERVATION_SIZE,), dtype=np.float32)
        self.last_state = None

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self.conn.log("正在重置环境...")
        self.conn.send_command("ready")
        
        start_time = time.time()
        while True:
            # 30秒超时熔断
            if time.time() - start_time > 30:
                self.conn.log("重置超时，强行启动...")
                break

            self.conn.send_command("state")
            state = self.conn.receive_state()
            if not state:
                time.sleep(0.05); continue
            
            cmds = state.get('available_commands', [])
            
            # 1. 看到 Start 直接开
            if 'start' in cmds: break
                
            # 2. 过场点击 (稳健版)
            # [修改] 将等待时间从 0.1 改为 0.5
            # 给游戏足够的喘息时间来处理转场动画，防止点击被吞
            if 'proceed' in cmds: self.conn.send_command("proceed"); time.sleep(0.5)
            elif 'confirm' in cmds: self.conn.send_command("confirm"); time.sleep(0.5)
            elif 'leave' in cmds: self.conn.send_command("leave"); time.sleep(0.5)
            elif 'skip' in cmds: self.conn.send_command("skip"); time.sleep(0.5)
            elif 'return' in cmds: self.conn.send_command("return"); time.sleep(0.5)
            else: time.sleep(0.1)

        self.conn.log("发送 Start 指令...")
        self.conn.send_command("start ironclad")
        
        # 地图生成等待 (保持 1.0 或 0.8)
        time.sleep(1.0) 
        
        self._block_until_interaction()
        self._ensure_combat_ready()
        
        if not self.last_state:
            return np.zeros(OBSERVATION_SIZE, dtype=np.float32), {}
        return encode_state(self.last_state), {}
    def step(self, action):
        prev_state = self.last_state
        
        # --- [新增] 计算当前允许的所有动作 (Debug用) ---
        # 我们临时把 prev_state 设为 current 来计算 mask，算完还原
        temp_state = self.last_state
        self.last_state = prev_state
        current_mask = self.action_masks()
        self.last_state = temp_state
        
        # 把 [True, False, True...] 转换成 [0, 2...]
        valid_actions = [i for i, m in enumerate(current_mask) if m]
        valid_str = str(valid_actions)
        
        # 翻译指令
        cmd = self._action_to_command(action)
        
        # --- 无效处理 ---
        if cmd is None:
            self._block_until_interaction()
            self.conn.log(f"⚠️ [无效] Action {action} 不在许可列表 {valid_str} 中")
            return encode_state(self.last_state), -0.1, False, False, {}
        
        # --- 执行 ---
        self.conn.send_command(cmd)
        
        if "play" not in cmd and "end" not in cmd:
            time.sleep(0.15)

        # 智能阻塞
        if action == 10 and "end" in cmd:
            self._wait_for_turn_change(prev_state)
        elif action < 10 and "play" in cmd:
            self._wait_for_card_played(prev_state)
        else:
            self._block_until_interaction()
            
        # 战斗再次确认手牌
        self._ensure_combat_ready()

        # --- 结算 ---
        reward = self._calculate_reward(prev_state, self.last_state)
        
        terminated = False
        if self.last_state and 'game_state' in self.last_state:
            screen = self.last_state['game_state'].get('screen_type')
            if screen in ['GAME_OVER', 'VICTORY']:
                terminated = True
                if screen == 'VICTORY': reward += 100
                else: reward -= 10

        # --- 日志 ---
        act_desc = self._get_action_name(action, prev_state)
        status_desc = self._get_status_desc(prev_state)
        
        # [修改] 打印更详细的信息：状态 + 可选动作 + AI选择
        # 只要有得分，或者动作是结束回合，或者处于战斗中，都打印
        if reward != 0 or action == 10 or "战斗" in status_desc:
            self.conn.log(f"{status_desc} | 可选:{valid_str} | AI选:{act_desc} | 得分:{reward:.2f}")

        if not self.last_state:
            return np.zeros(OBSERVATION_SIZE, dtype=np.float32), 0, True, False, {}
            
        return encode_state(self.last_state), reward, terminated, False, {}

    # =========================================================================
    # 辅助函数
    # =========================================================================
    
    def _get_status_desc(self, state):
        """[修复版] 优先利用指令列表判断状态，解决转场时的显示Bug"""
        if not state: return "[无数据]"
        
        cmds = state.get('available_commands', [])
        game = state.get('game_state', {})
        screen = game.get('screen_type', 'UNK')
        
        # [核心修改] 只要能打牌或能结束回合，那就是战斗！
        # 这比 screen_type 更准，因为指令是实时的
        if 'play' in cmds or 'end' in cmds:
            combat = game.get('combat_state', {})
            player = combat.get('player', {})
            hand = combat.get('hand', [])
            e = player.get('energy', '?')
            hp = player.get('current_hp', '?')
            return f"[战斗 HP:{hp} E:{e} 手牌:{len(hand)}]"
        
        # 非战斗状态判断
        if screen == 'MAP': return "[地图选择]"
        elif screen == 'EVENT': return "[随机事件]"
        elif screen == 'SHOP': return f"[商店 Gold:{game.get('gold',0)}]"
        elif 'REST': return "[篝火休息]"
        elif 'COMBAT_REWARD' in screen or 'BOSS_REWARD' in screen: return "[战利品]"
        
        return f"[{screen}]"

    def _block_until_interaction(self):
        timeout = 60.0; start_t = time.time()
        while True:
            self.conn.send_command("state")
            state = self.conn.receive_state()
            if not state: time.sleep(0.02); continue
            cmds = state.get('available_commands', [])
            can_act = any(c in cmds for c in ['play', 'choose', 'proceed', 'end', 'confirm', 'leave', 'start'])
            if can_act:
                self.last_state = state; break
            if time.time() - start_t > timeout: self.last_state = state; break
            time.sleep(0.02)

    def _wait_for_turn_change(self, prev_state):
        timeout = 60.0; start_t = time.time()
        prev_turn = prev_state.get('game_state', {}).get('combat_state', {}).get('turn', 0)
        while True:
            self.conn.send_command("state")
            state = self.conn.receive_state()
            if not state: time.sleep(0.02); continue
            cmds = state.get('available_commands', [])
            
            # 战斗结束
            if any(c in cmds for c in ['proceed', 'confirm', 'leave', 'start']):
                self.last_state = state; break
            
            # 回合改变
            curr_turn = state.get('game_state', {}).get('combat_state', {}).get('turn', 0)
            if curr_turn > prev_turn and 'play' in cmds:
                self.last_state = state
                self._ensure_combat_ready() # 确保新回合牌发下来了
                break
                
            if time.time() - start_t > timeout: self.last_state = state; break
            time.sleep(0.05)

    def _wait_for_card_played(self, prev_state):
        timeout = 2.0; start_t = time.time()
        prev_hand = len(prev_state.get('game_state', {}).get('combat_state', {}).get('hand', []))
        while True:
            self.conn.send_command("state")
            state = self.conn.receive_state()
            if not state: time.sleep(0.02); continue
            curr_hand = len(state.get('game_state', {}).get('combat_state', {}).get('hand', []))
            if curr_hand != prev_hand: self.last_state = state; break
            if 'play' not in state.get('available_commands', []): self.last_state = state; break
            if time.time() - start_t > timeout: self.last_state = state; break
            time.sleep(0.02)

    def _ensure_combat_ready(self):
        """
        [增强版] 战斗就绪检查
        只要处于战斗状态，就必须死等手牌填充完毕，防止 AI 开局空过。
        """
        if not self.last_state: return
        
        # 1. 判定是否处于战斗中
        # 使用 room_phase 判断更准确，因为它比 available_commands 更早更新
        game = self.last_state.get('game_state', {})
        room_phase = game.get('room_phase', '')
        cmds = self.last_state.get('available_commands', [])
        
        is_combat = (room_phase == 'COMBAT') or ('play' in cmds) or ('end' in cmds)
        
        if not is_combat:
            return
        
        # 2. 循环检查手牌
        # 如果是战斗开始，或者新回合，手牌通常不为0
        # 除非牌堆和弃牌堆真的都没牌了
        for _ in range(100): # 最多等 5 秒 (足够了吧？)
            combat = self.last_state.get('game_state', {}).get('combat_state', {})
            hand = combat.get('hand', [])
            draw = combat.get('draw_pile', [])
            discard = combat.get('discard_pile', [])
            
            # 核心通过条件：
            # A. 手里有牌了 -> OK
            # B. 手里没牌，但抽牌堆和弃牌堆也都空了 (真的没牌可抽) -> OK
            if len(hand) > 0:
                return
            if len(draw) == 0 and len(discard) == 0:
                return
                
            # 还在发牌动画中，继续等
            time.sleep(0.05)
            self.conn.send_command("state")
            self.last_state = self.conn.receive_state()
            
        # 如果超时了还是一张牌都没有，那可能是出 bug 了或者真的是空手流
        # 打印个警告，然后放行
        self.conn.log("警告：战斗发牌等待超时 (手牌仍为0)")

    def _action_to_command(self, action):
        if not self.last_state: return None
        cmds = self.last_state.get('available_commands', [])
        combat = self.last_state.get('game_state', {}).get('combat_state', {})
        
        if action == 10 and 'end' in cmds: return "end"
        
        if 'play' in cmds:
            # [核心修复] 药水指令格式修正
            if 11 <= action <= 13:
                potion_idx = action - 11
                # 寻找第一个活着的怪物作为目标
                target_idx = 0
                monsters = combat.get('monsters', [])
                for i, m in enumerate(monsters):
                    if not m.get('is_gone') and not m.get('half_dead'):
                        target_idx = i
                        break
                # 正确格式: potion use [槽位] [目标]
                return f"potion use {potion_idx} {target_idx}"
            if action < 10:
                hand = combat.get('hand', [])
                if action >= len(hand): return None
                card = hand[action]
                target = 0
                if card.get('has_target'):
                    monsters = combat.get('monsters', [])
                    for i, m in enumerate(monsters):
                        if not m.get('is_gone') and not m.get('half_dead'):
                            target = i; break
                    return f"play {action+1} {target}"
                return f"play {action+1}"

        if 'choose' in cmds:
            if action == 10:
                for c in ['confirm', 'leave', 'return', 'cancel', 'proceed', 'skip']:
                    if c in cmds: return c
                return "state"
            return f"choose {action}"

        for c in ['proceed', 'confirm', 'leave', 'skip', 'return', 'start']:
            if c in cmds: return c
            
        if action == 10: return "state"
        return None

    def action_masks(self):
        mask = [False] * 14
        if not self.last_state: return mask
        
        cmds = self.last_state.get('available_commands', [])
        game = self.last_state.get('game_state', {})
        
        # --- [核心修复] 全局检查 End ---
        # 无论处于什么模式 (Play/Choose/Confirm)，只要有 'end' 指令，就允许动作 10
        if 'end' in cmds:
            mask[10] = True

        # --- 场景 A: 战斗 (打牌/喝药) ---
        if 'play' in cmds:
            combat = game.get('combat_state', {})
            hand = combat.get('hand', [])
            energy = combat.get('player', {}).get('energy', 0)
            
            for i in range(len(hand)):
                if i < 10:
                    c = hand[i]
                    cost = c.get('cost', 0)
                    req = cost if cost >= 0 else 0
                    if c.get('is_playable') and cost != -2 and energy >= req:
                        mask[i] = True
            
            # 药水
            pots = game.get('potions', [])
            for i in range(len(pots)):
                if i < 3 and pots[i].get('can_use'): mask[11+i] = True

        # --- 场景 B: 选择 (商店/事件) ---
        elif 'choose' in cmds:
            choices = game.get('choice_list', [])
            for i in range(len(choices)): 
                if i < 10: mask[i] = True
            
            # 允许离开/取消 (叠加在动作 10 上)
            if any(c in cmds for c in ['leave', 'cancel', 'return', 'proceed', 'skip', 'confirm']):
                mask[10] = True
            
            if not any(mask): mask[0] = True

        # --- 场景 C: 过场 (Confirm/Proceed...) ---
        # 注意：这里改成了 if 而不是 elif，防止上面的逻辑没覆盖到
        # 但为了避免逻辑冲突，通常保持 elif，但在内部补全 mask[0]
        elif any(c in cmds for c in ['proceed', 'confirm', 'leave', 'skip', 'return', 'start']):
            mask[0] = True
            
            # [双保险] 如果这里有 confirm，通常动作 0 是 confirm
            # 但如果同时也有 end (如你遇到的情况)，上面的全局检查已经开启了 mask[10]
            # 所以 AI 既可以选 0 (confirm) 也可以选 10 (end)
        
        else:
            # 兜底：如果上面都没命中，且没有 end (mask[10]还是False)，那就强制开一个
            if not any(mask): mask[10] = True

        return mask

    def _get_action_name(self, action, state):
        if not state: return f"未知 ({action})"
        cmds = state.get('available_commands', [])
        
        if 'play' in cmds or 'end' in cmds:
            if action == 10: return "【结束回合】"
            if 11 <= action <= 13: return f"药水 {action-11}"
            try:
                hand = state['game_state']['combat_state']['hand']
                if action < len(hand): return f"打出: {hand[action].get('name')}"
            except: pass
            return f"战斗操作 {action}"
            
        if action == 10: return "【离开/继续】"
        if 'choose' in cmds:
            try:
                c = state['game_state']['choice_list'][action]
                return f"选择: {str(c)[:15]}"
            except: pass
        return f"交互 {action}"

    def _calculate_reward(self, prev_json, next_json):
        if not prev_json or not next_json: return 0
        reward = 0.0
        try:
            game_prev = prev_json.get('game_state', {})
            game_next = next_json.get('game_state', {})
            
            f_prev = game_prev.get('floor', 0)
            f_next = game_next.get('floor', 0)
            if f_next > f_prev: reward += 5.0

            if 'combat_state' not in game_prev or 'combat_state' not in game_next: return reward
            combat_prev = game_prev['combat_state']
            combat_next = game_next['combat_state']
            
            hp_p = combat_prev.get('player', {}).get('current_hp', 0)
            hp_n = combat_next.get('player', {}).get('current_hp', 0)
            if hp_n < hp_p: reward -= (hp_p - hp_n) * 2.0
            
            m_prev = combat_prev.get('monsters', [])
            m_next = combat_next.get('monsters', [])
            alive_p = len([m for m in m_prev if not m.get('is_gone') and not m.get('is_dying')])
            alive_n = len([m for m in m_next if not m.get('is_gone') and not m.get('is_dying')])
            if alive_n < alive_p: reward += (alive_p - alive_n) * 50.0
                
            def get_total_hp(monsters):
                return sum([m.get('current_hp', 0) for m in monsters if not m.get('is_gone') and not m.get('is_dying')])
            dmg = get_total_hp(m_prev) - get_total_hp(m_next)
            if dmg > 0: reward += dmg * 1.0 
        except: pass
        return reward