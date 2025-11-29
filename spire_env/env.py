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
        
        # 动作空间: 0-9 打手牌, 10 结束回合
        self.action_space = spaces.Discrete(11) 
        
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
            
            if not state:
                time.sleep(0.01)
                continue
            
            # [新增] 关键检查：红绿灯机制
            # 如果游戏说 "ready_for_command": false，说明它正在忙（播动画/转场）
            # 这时候千万别发指令，发了也没用，只会添乱
            if not state.get('ready_for_command', False):
                # 稍微多睡一会，等动画播完
                time.sleep(0.02)
                continue

            avail_cmds = state.get('available_commands', [])
            
            # 2. 终止条件：看到了开始按钮
            if 'start' in avail_cmds:
                break
                
            # 3. 点击继续/确认/离开
            # 这里加长了 sleep 时间，因为转场通常都很慢
            if 'proceed' in avail_cmds:
                self.conn.send_command("proceed")
                time.sleep(0.05) 
            elif 'confirm' in avail_cmds:
                self.conn.send_command("confirm")
                time.sleep(0.05)
            elif 'leave' in avail_cmds:
                self.conn.send_command("leave")
                time.sleep(0.05)
            else:
                time.sleep(0.05)

        # --- 2. 自动开始新游戏 ---
        self.conn.log("回到主菜单，自动开始新游戏...")
        self.conn.send_command("start ironclad")
        time.sleep(2.0) # start 指令后加载时间较长，多睡一会
        
        # --- 3. 获取初始状态 ---
        self.conn.send_command("state")
        raw_state = self.conn.receive_state()
        self.last_state = raw_state
        
        # 确保抽牌动画结束
        self._wait_for_draw()
        
        return encode_state(self.last_state), {}

    def step(self, action):
        # 1. [关键] 记录上一帧的状态，这是“动作发生前”的照片
        prev_state = self.last_state
        
        # 2. 翻译动作
        cmd = self._action_to_command(action)
        
        # --- 情况 A: 无效动作 (cmd is None) ---
        if cmd is None:
            self.conn.send_command("state")
            raw_state = self.conn.receive_state()
            if raw_state: self.last_state = raw_state
            
            # 给予轻微惩罚
            return encode_state(self.last_state), -0.05, False, False, {}
        
        # --- 情况 B: 有效动作 ---
        self.conn.send_command(cmd)
        
        # 3. 读取新状态 (这是“动作发生后”的照片)
        next_state = self.conn.receive_state()
        self.last_state = next_state
        
        # 4. [关键] 等待抽牌动画
        self._wait_for_draw()
        
        # 5. [关键] 计算奖励 (对比 前后 状态)
        reward = self._calculate_reward(prev_state, self.last_state)
        
        # 6. 判定游戏结束
        terminated = False
        if self.last_state is None:
            terminated = True
        elif 'game_state' in self.last_state:
            screen = self.last_state['game_state'].get('screen_type')
            if screen in ['GAME_OVER', 'VICTORY']:
                terminated = True
                if screen == 'VICTORY':
                    reward += 100
                else:
                    reward -= 10

        # --- [修改点] 日志打印 ---
        # 关键修改：传入 prev_state (旧照片)！
        # 这样翻译官才能看到刚才打出去的那张牌叫什么名字
        act_desc = self._get_action_name(action, prev_state)
        
        self.conn.log(f"执行 -> {act_desc} | 得分: {reward:.2f}")

        # 7. 编码状态并返回 (返回给神经网络的必须是最新状态)
        obs = encode_state(self.last_state)

        return obs, reward, terminated, False, {}
    def action_masks(self):
        """
        返回一个布尔数组，True 表示该动作合法，False 表示非法。
        对应 action_space 的 11 个动作 (0-9:打牌, 10:结束/互动)
        """
        # 初始化：默认全部非法 (False)
        mask = [False] * 11
        
        if not self.last_state:
            return mask
            
        avail_cmds = self.last_state.get('available_commands', [])
        game_state = self.last_state.get('game_state', {})
        combat_state = game_state.get('combat_state', {})
        
        # --- 场景 A: 战斗中 ---
        if 'play' in avail_cmds:
            hand = combat_state.get('hand', [])
            has_playable_card = False
            
            # 1. 检查每一张手牌
            for i in range(len(hand)):
                if i < 10:
                    card = hand[i]
                    is_playable = card.get('is_playable', False)
                    cost = card.get('cost', 0)
                    
                    # [关键修改] 增加 cost != -2 的判断
                    # 即使游戏说能打(比如有蓝蜡烛遗物)，我们暂时也强制不让AI打诅咒，
                    # 避免它为了贪那点出牌分把自己烧死。
                    if is_playable and cost != -2:
                        mask[i] = True
                        has_playable_card = True
            
            # 2. 结束回合逻辑 (贪婪模式：没牌打才能结束)
            if 'end' in avail_cmds:
                if has_playable_card:
                    mask[10] = False
                else:
                    mask[10] = True
        # --- 场景 B: 非战斗 (选路、事件、商店) ---
        else:
            # 在非战斗界面，我们之前约定：
            # 动作 0 代表 "choose 0" / "proceed" / "confirm"
            # 所以只要不是在打牌，我们就开放动作 0
            if any(cmd in avail_cmds for cmd in ['choose', 'proceed', 'confirm', 'leave']):
                mask[0] = True
                
            # 如果什么指令都没有 (比如 wait)，为了防止报错，至少开放一个动作(比如10)
            # 让它空转一轮
            if not any(mask):
                mask[10] = True

        return mask
    def _wait_for_draw(self):
        """
        辅助函数：防止在抽牌动画还没结束时就让 AI 决策
        如果处于 play 阶段，但手牌是空的，说明正在抽牌，强制循环等待
        """
        while True:
            # 如果没有状态，或者不在 play 阶段，直接放行
            if not self.last_state:
                break
            
            avail_cmds = self.last_state.get('available_commands', [])
            if 'play' not in avail_cmds:
                break
                
            game_state = self.last_state.get('game_state', {})
            combat_state = game_state.get('combat_state', {})
            hand = combat_state.get('hand', [])
            draw_pile = combat_state.get('draw_pile', [])
            discard_pile = combat_state.get('discard_pile', [])
            
            # 核心判断：
            # 如果轮到我打牌(play)，且手牌为空(hand==0)，且牌堆里还有牌(draw+discard > 0)
            # 说明牌还在路上，必须等！
            if len(hand) == 0 and (len(draw_pile) > 0 or len(discard_pile) > 0):
                # 发送 state 刷新状态，不要发 wait，wait 可能会跳过某些帧
                self.conn.send_command("state")
                time.sleep(0.05) # 稍等一下
                self.last_state = self.conn.receive_state()
            else:
                # 手牌有了，或者真的没牌了，放行
                break
    def _action_to_command(self, action):
        """核心翻译逻辑：数字 -> 字符串"""
        if not self.last_state:
            return None
        
        avail_cmds = self.last_state.get('available_commands', [])
        game_state = self.last_state.get('game_state', {})
        combat_state = game_state.get('combat_state', {})
        
        # --- 优先处理：结束回合 (Action 10) ---
        # 只要游戏允许结束回合，无论能不能打牌，都应该允许 AI 选这个
        if action == 10 and 'end' in avail_cmds:
            return "end"

        # --- 场景 A: 打牌 (Action 0-9) ---
        # 只有当游戏允许 'play' 时，才尝试打牌
        if action < 10 and 'play' in avail_cmds:
            hand = combat_state.get('hand', [])
            
            # 安全检查：防止数组越界
            if action >= len(hand):
                return None
            
            card = hand[action]
            card_idx = action + 1 
            
            # 智能目标选择
            if card.get('has_target', False):
                monsters = combat_state.get('monsters', [])
                target_idx = -1
                for i, m in enumerate(monsters):
                    if not m.get('is_gone') and m.get('current_hp', 0) > 0 and not m.get('half_dead'):
                        target_idx = i
                        break
                
                if target_idx != -1:
                    return f"play {card_idx} {target_idx}"
                else:
                    return None
            else:
                return f"play {card_idx}"

        # --- 场景 B: 选路/事件/篝火 ---
        if 'proceed' in avail_cmds:
            return "proceed"

        # [修改点 2] 其次：确认/离开
        if 'confirm' in avail_cmds:
            return "confirm"
            
        if 'leave' in avail_cmds:
            return "leave"

        # [修改点 3] 最后：如果没有别的路可走，再去选选项
        # 比如刚进商店房间，没有 proceed，只有 choose，这时候才去点商人
        if 'choose' in avail_cmds and action != 10:
            return "choose 0"

        return None
    def _get_action_name(self, action, state):
        """
        [修改] 增加 state 参数，允许查阅指定的历史状态
        """
        if not state:
            return f"未知 ({action})"
            
        avail_cmds = state.get('available_commands', [])
        
        # --- 情况 A: 非战斗状态 ---
        if 'play' not in avail_cmds:
            if action == 10: return "【等待/跳过】"
            return f"非战斗交互 (选项 {action})"

        # --- 情况 B: 战斗状态 ---
        if action == 10:
            return "【结束回合】"
        
        try:
            # 从传入的 state (prev_state) 里查手牌
            # 这时候牌还在手里，所以能查到名字
            game_state = state.get('game_state', {})
            combat_state = game_state.get('combat_state', {})
            hand = combat_state.get('hand', [])
            
            if action < len(hand):
                card = hand[action]
                name = card.get('name', 'Unknown')
                cost = card.get('cost', 0)
                return f"打出: {name} ({cost}费)"
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