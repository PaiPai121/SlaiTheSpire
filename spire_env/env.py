import numpy as np
from utils.state_encoder import encode_state, OBSERVATION_SIZE # 引入我们刚写的
import gymnasium as gym
from gymnasium import spaces
import time
from .interface import Connection

class SlayTheSpireEnv(gym.Env):
    def __init__(self):
        super(SlayTheSpireEnv, self).__init__()
        
        self.conn = Connection()
        
        # 动作空间: 0-9(牌), 10(结束/选择), 11-13(药水)
        self.action_space = spaces.Discrete(14)
        
        # 观察空间: 暂时使用 Dict (后续会改为 Box)
        self.observation_space = spaces.Box(
            low=-1.0, 
            high=1000.0, # 随便设个大数
            shape=(OBSERVATION_SIZE,), 
            dtype=np.float32
        )

        self.last_state = None

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self.conn.log("正在重置环境...")
        
        # --- 1. 死循环清理战场 ---
        while True:
            # 1. 询问当前状态
            self.conn.send_command("state")
            state = self.conn.receive_state()
            # self.conn.log("debug")
            if not state:
                self.conn.log("no state") # 打印出来方便调试
                time.sleep(0.001)
                continue
            avail_cmds = state.get('available_commands', [])
            # 2. 终止条件：看到了开始按钮
            if 'start' in avail_cmds:
                self.conn.log("has start") # 打印出来方便调试
                break
                
            # [新增] 关键检查：红绿灯机制
            # 如果游戏说 "ready_for_command": false，说明它正在忙（播动画/转场）
            # 这时候千万别发指令，发了也没用，只会添乱
            if not state.get('ready_for_command', False):
                # self.conn.log("no ready_for_command") # 打印出来方便调试
                # 稍微多睡一会，等动画播完
                time.sleep(0.002)
                continue




            # 3. 点击操作
            if 'proceed' in avail_cmds:
                self.conn.send_command("proceed")
                self.conn.log("点击 Proceed") # 打印出来方便调试
                time.sleep(0.05) 
            elif 'confirm' in avail_cmds:
                self.conn.send_command("confirm")
                self.conn.log("点击 Confirm")
                time.sleep(0.05)
            elif 'leave' in avail_cmds:
                self.conn.send_command("leave")
                self.conn.log("点击 Leave")
                time.sleep(0.05)
            elif 'skip' in avail_cmds:
                self.conn.send_command("skip")
                self.conn.log("skip")
                time.sleep(0.05)
            elif 'return' in avail_cmds:
                self.conn.send_command("return")
                self.conn.log("return")
                time.sleep(0.05)
            else:
                # 既不忙，也没按钮点，这是最尴尬的
                self.conn.log("no anything")
                time.sleep(0.05)

        # --- 2. 自动开始新游戏 ---
        self.conn.log("回到主菜单，自动开始新游戏...")
        self.conn.send_command("start ironclad")
        time.sleep(1) # start 指令后加载时间较长，多睡一会
        
        # --- 3. 获取初始状态 ---
        self.conn.send_command("state")
        raw_state = self.conn.receive_state()
        self.last_state = raw_state
        
        # 确保抽牌动画结束
        self._wait_for_draw()
        
        return encode_state(self.last_state), {}

    def step(self, action):
        prev_state = self.last_state
        prev_game = prev_state.get('game_state', {})
        prev_combat = prev_game.get('combat_state', {})
        prev_hand_count = len(prev_combat.get('hand', []))
        prev_energy = prev_combat.get('player', {}).get('energy', 0)
        # [新增] 记录回合数，用于判断是否真的结束了回合
        prev_turn = prev_combat.get('turn', 0)
        
        cmd = self._action_to_command(action)
        
        if cmd is None:
            self.conn.send_command("state")
            self.last_state = self.conn.receive_state()
            return encode_state(self.last_state), -0.1, False, False, {}
        
        self.conn.send_command(cmd)
        
        # UI 缓冲
        if "play" not in cmd and "end" not in cmd:
            time.sleep(0.15)

        # --- [状态锁] ---
        start_time = time.time()
        timeout = 2.0 
        is_timeout = False
        
        while True:
            self.conn.send_command("state")
            next_state = self.conn.receive_state()
            
            if not next_state: 
                time.sleep(0.01)
                continue
            
            # 超时检查
            if time.time() - start_time > timeout:
                is_timeout = True
                self.last_state = next_state
                break

            curr_avail = next_state.get('available_commands', [])
            curr_game = next_state.get('game_state', {})
            curr_combat = curr_game.get('combat_state', {})
            
            # 1. 忙碌检查
            can_act = any(c in curr_avail for c in ['play', 'choose', 'proceed', 'end', 'confirm', 'leave', 'start'])
            if not can_act:
                time.sleep(0.01)
                continue

            # 2. [打牌锁] 检查手牌/能量变化
            if action < 10 and 'play' in prev_state.get('available_commands', []):
                curr_hand_count = len(curr_combat.get('hand', []))
                curr_energy = curr_combat.get('player', {}).get('energy', 0)
                
                if curr_hand_count == prev_hand_count and curr_energy == prev_energy:
                    time.sleep(0.01)
                    continue

            # 3. [新增：回合锁] 检查回合是否结束
            if action == 10 and 'end' in prev_state.get('available_commands', []):
                curr_turn = curr_combat.get('turn', 0)
                
                # 如果 'end' 还在，且 回合数没变 -> 说明游戏还没处理完 -> 继续等
                # (注意：如果敌人回合极快，可能瞬间跳到下一回合，此时 'end' 会再次出现，但 turn 会+1，所以要校验 turn)
                if 'end' in curr_avail and curr_turn == prev_turn:
                    time.sleep(0.01)
                    continue

            self.last_state = next_state
            break

        # 抽牌等待
        if action == 10:
            self._wait_for_draw(strict=True)
        elif len(self.last_state.get('game_state', {}).get('combat_state', {}).get('hand', [])) == 0:
            self._wait_for_draw(strict=False)
        
        reward = self._calculate_reward(prev_state, self.last_state)
        
        terminated = False
        if self.last_state is None:
            terminated = True
        elif 'game_state' in self.last_state:
            screen = self.last_state['game_state'].get('screen_type')
            if screen in ['GAME_OVER', 'VICTORY']:
                terminated = True
                if screen == 'VICTORY': reward += 100
                else: reward -= 10

        # 日志
        act_desc = self._get_action_name(action, prev_state)
        if reward != 0.1 or action == 10 or "选择" in act_desc or is_timeout:
            timeout_tag = " [超时]" if is_timeout else ""
            self.conn.log(f"执行 -> {act_desc}{timeout_tag} | 得分: {reward:.2f}")

        return encode_state(self.last_state), reward, terminated, False, {}
    def action_masks(self):
        mask = [False] * 14
        
        if not self.last_state: return mask
            
        avail_cmds = self.last_state.get('available_commands', [])
        game_state = self.last_state.get('game_state', {})
        combat_state = game_state.get('combat_state', {})
        
        # --- 场景 A: 战斗中 ---
        if 'play' in avail_cmds:
            hand = combat_state.get('hand', [])
            player_energy = combat_state.get('player', {}).get('energy', 0)
            
            # [调试开关] 如果你想看每一帧的判断细节，把这个设为 True
            # 平时设为 False，不然日志太乱
            debug_mode = False 
            
            # 如果能量为0还在尝试计算，强制开启调试打印
            if player_energy == 0 and len(hand) > 0:
                debug_mode = True
                self.conn.log(f"\n--- [调试: 0能量时刻] ---")

            for i in range(len(hand)):
                if i < 10:
                    card = hand[i]
                    card_name = card.get('name', 'Unknown')
                    is_playable = card.get('is_playable', False)
                    cost = card.get('cost', 0)
                    
                    # 费用计算
                    required_energy = cost if cost >= 0 else 0
                    
                    # 判定逻辑
                    condition_playable = is_playable
                    condition_not_curse = (cost != -2)
                    condition_energy = (player_energy >= required_energy)
                    
                    # 综合结果
                    can_play = condition_playable and condition_not_curse and condition_energy
                    
                    if can_play:
                        mask[i] = True
                    
                    # [关键调试] 打印每一张牌的“判决书”
                    if debug_mode:
                        self.conn.log(f"卡牌[{i}] {card_name}: 费用{cost} | 需要{required_energy} | 当前能量{player_energy}")
                        self.conn.log(f"  -> 游戏允许? {condition_playable} | 非诅咒? {condition_not_curse} | 能量够? {condition_energy}")
                        self.conn.log(f"  -> 最终结果: {'可打' if can_play else ' 屏蔽'}")

            # 结束回合逻辑
            if 'end' in avail_cmds:
                mask[10] = True
            
            # 药水逻辑
            potions = game_state.get('potions', [])
            for i in range(len(potions)):
                if i < 3 and potions[i].get('can_use', False):
                    mask[11 + i] = True

        # --- 非战斗逻辑 (保持不变) ---
        elif 'choose' in avail_cmds:
            choice_list = game_state.get('choice_list', [])
            for i in range(len(choice_list)):
                if i < 10: mask[i] = True
            if any(cmd in avail_cmds for cmd in ['leave', 'cancel', 'return', 'proceed', 'skip', 'confirm']):
                mask[10] = True
            if not any(mask): mask[0] = True
        elif any(cmd in avail_cmds for cmd in ['proceed', 'confirm', 'leave', 'skip', 'return']):
            mask[0] = True
        else:
            if not any(mask): mask[10] = True

        return mask

    def _wait_for_draw(self, strict=True):
        """
        辅助函数：等待手牌填充
        strict=True: (结束回合用) 死等模式。只要牌堆有牌且手牌为空，就一直等。
        strict=False: (打牌用) 试探模式。只等一小会儿，防止是"抽牌卡"带来的延迟。如果超时还没牌，就当做真没牌了。
        """
        # 计数器：防止非严格模式下死循环
        # 如果是打牌产生的空手，我们最多等 20 次 (20 * 0.02s = 0.4s)
        # 对于 SuperFastMode 来说，0.4s 足够抽完牌了
        max_retries = 20 if not strict else 999999
        current_try = 0
        
        while current_try < max_retries:
            if not self.last_state:
                break
            
            avail_cmds = self.last_state.get('available_commands', [])
            # 如果都不允许打牌了（比如怪物死了），就别等了
            if 'play' not in avail_cmds:
                break
                
            game_state = self.last_state.get('game_state', {})
            combat_state = game_state.get('combat_state', {})
            hand = combat_state.get('hand', [])
            draw_pile = combat_state.get('draw_pile', [])
            discard_pile = combat_state.get('discard_pile', [])
            
            # 核心判断：手牌为空 且 还有牌可抽
            if len(hand) == 0 and (len(draw_pile) > 0 or len(discard_pile) > 0):
                self.conn.send_command("state")
                time.sleep(0.02) # 短暂等待
                
                # 更新状态
                new_state = self.conn.receive_state()
                if new_state: 
                    self.last_state = new_state
                
                current_try += 1
            else:
                # 手里有牌了，或者真没牌了 (抽弃牌堆都空)
                break
    def _action_to_command(self, action):
        if not self.last_state: return None
        
        avail_cmds = self.last_state.get('available_commands', [])
        game_state = self.last_state.get('game_state', {})
        combat_state = game_state.get('combat_state', {})
        
        # --- [核心修复] 独立处理结束回合 ---
        # 只要游戏允许 'end'，且 AI 选了 10，就必须执行
        # 不再检查 'play' 是否存在！
        if action == 10 and 'end' in avail_cmds:
            return "end"

        # --- A. 战斗：打牌与药水 ---
        if 'play' in avail_cmds:
            # 药水 (11-13)
            if action >= 11 and action <= 13:
                return f"potion {action - 11} 0"
            
            # 打牌 (0-9)
            if action < 10:
                hand = combat_state.get('hand', [])
                if action >= len(hand): return None
                
                card = hand[action]
                card_idx = action + 1 
                
                if card.get('has_target', False):
                    monsters = combat_state.get('monsters', [])
                    target_idx = 0 
                    for i, m in enumerate(monsters):
                        if not m.get('is_gone') and m.get('current_hp', 0) > 0 and not m.get('half_dead'):
                            target_idx = i
                            break
                    return f"play {card_idx} {target_idx}"
                else:
                    return f"play {card_idx}"

        # --- B. 选择 (商店/事件/奖励) ---
        if 'choose' in avail_cmds:
            if action == 10:
                # 离开/确认/取消
                if 'confirm' in avail_cmds: return "confirm"
                if 'leave' in avail_cmds: return "leave"
                if 'return' in avail_cmds: return "return"
                if 'cancel' in avail_cmds: return "cancel"
                if 'proceed' in avail_cmds: return "proceed"
                if 'skip' in avail_cmds: return "skip"
                # 兜底刷新
                return "state"
                
            return f"choose {action}"

        # --- C. 纯过场 ---
        if 'confirm' in avail_cmds: return "confirm"
        if 'proceed' in avail_cmds: return "proceed"
        if 'leave' in avail_cmds: return "leave"
        if 'skip' in avail_cmds: return "skip"
        if 'return' in avail_cmds: return "return"
        
        # --- D. 主菜单 ---
        if 'start' in avail_cmds:
            return "start ironclad"

        # --- [万能兜底] ---
        # 如果动作是 10，但上面都没匹配上，发个 state 防止报错
        if action == 10:
            return "state"

        return None
    def _get_action_name(self, action, state):
        if not state: return f"未知 ({action})"
            
        avail_cmds = state.get('available_commands', [])
        game_state = state.get('game_state', {}) 
        
        # --- [修改] 判定战斗状态的条件 ---
        # 只要有 'play' 或者 'end'，都算是战斗状态
        # 这样就能正确识别 "只能结束回合" 的特殊时刻
        is_combat = 'play' in avail_cmds or 'end' in avail_cmds
        
        # --- 情况 A: 非战斗状态 ---
        if not is_combat:
            if action == 10:
                if 'proceed' in avail_cmds: return "【继续/前进】"
                if 'confirm' in avail_cmds: return "【确认】"
                if 'leave' in avail_cmds: return "【离开】"
                if 'skip' in avail_cmds: return "【跳过】"
                if 'return' in avail_cmds: return "【返回】"
                return "【等待/兜底】"
            
            if 'choose' in avail_cmds:
                choice_list = game_state.get('choice_list', [])
                if action < len(choice_list):
                    choice_text = str(choice_list[action])
                    if len(choice_text) > 20: choice_text = choice_text[:20] + "..."
                    return f"选择: {choice_text}"
            
            return f"非战斗交互 (Action {action})"

        # --- 情况 B: 战斗状态 ---
        if action == 10:
            return "【结束回合】"
        
        if action >= 11 and action <= 13:
            return f"使用药水: 槽位{action - 11}"

        try:
            combat_state = game_state.get('combat_state', {})
            hand = combat_state.get('hand', [])
            if action < len(hand):
                card = hand[action]
                name = card.get('name', 'Unknown')
                cost = card.get('cost', 0)
                if cost == -1: c_str = "X"
                elif cost == -2: c_str = "禁"
                else: c_str = str(cost)
                return f"打出: {name} ({c_str}费)"
            else:
                return f"无效索引 {action} (手牌{len(hand)}张)"
        except:
            return f"解析异常 ({action})"
    def _calculate_reward(self, prev_json, next_json):
        """
        奖励公式：
        + (怪物掉血量 * 1.0)  -> 鼓励进攻
        - (玩家掉血量 * 2.0)  -> 鼓励防御 (痛感加倍)
        + 50.0               -> 击杀奖励
        + 0.1                -> 鼓励存活
        """
        if not prev_json or not next_json:
            return 0
            
        reward = 0.1 # 基础存活分
        
        try:
            # 1. 安全提取 game_state，如果提取失败直接跳过
            game_prev = prev_json.get('game_state', {})
            game_next = next_json.get('game_state', {})
            
            # 确保 combat_state 存在 (防止在地图/商店界面报错)
            if 'combat_state' not in game_prev or 'combat_state' not in game_next:
                return reward

            combat_prev = game_prev['combat_state']
            combat_next = game_next['combat_state']
            
            # --- 2. 计算玩家掉血惩罚 ---
            p_prev = combat_prev.get('player', {}).get('current_hp', 0)
            p_next = combat_next.get('player', {}).get('current_hp', 0)
            
            if p_next < p_prev:
                loss = p_prev - p_next
                reward -= (loss * 2.0) # 掉血惩罚
                
            # --- 3. 计算怪物掉血奖励 ---
            m_prev = combat_prev.get('monsters', [])
            m_next = combat_next.get('monsters', [])
            
            # 计算总血量 (只计算活着的)
            # 使用 .get 确保安全
            hp_sum_prev = sum([m.get('current_hp', 0) for m in m_prev if not m.get('is_gone', False)])
            hp_sum_next = sum([m.get('current_hp', 0) for m in m_next if not m.get('is_gone', False)])
            
            if hp_sum_next < hp_sum_prev:
                damage = hp_sum_prev - hp_sum_next
                reward += (damage * 1.0) # 伤害奖励

            # --- 4. 击杀奖励 (Kill Bonus) ---
            # 统计“真正活着”的怪物 (排除已逃跑 is_gone 和 濒死 is_dying)
            alive_prev = len([m for m in m_prev if not m.get('is_gone', False) and not m.get('is_dying', False)])
            alive_next = len([m for m in m_next if not m.get('is_gone', False) and not m.get('is_dying', False)])
            
            if alive_next < alive_prev:
                kill_count = alive_prev - alive_next
                reward += (kill_count * 50.0) # 击杀大奖

        except Exception:
            # 如果中间任何一步解析出问题（比如转场时数据不全），
            # 就只返回基础分，保证程序不崩
            pass

        return reward