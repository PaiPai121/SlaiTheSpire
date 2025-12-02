import numpy as np
import time
import gymnasium as gym
from gymnasium import spaces
from .interface import Connection
from .definitions import ObservationConfig, ActionIndex
from utils.state_encoder import encode_state
from utils.action_mapper import ActionMapper

class SlayTheSpireEnv(gym.Env):
    def __init__(self):
        super(SlayTheSpireEnv, self).__init__()
        self.conn = Connection()
        self.mapper = ActionMapper()
        
        self.action_space = spaces.Discrete(ActionIndex.TOTAL_ACTIONS)
        self.observation_space = spaces.Box(
            low=-5.0, high=1000.0, 
            shape=(ObservationConfig.SIZE,), 
            dtype=np.float32
        )
        
        self.last_state = None
        self.steps_since_reset = 0

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self.steps_since_reset = 0
        self.conn.log(">>> 环境重置 >>>")
        
        # 1. 强力重置连接
        self.conn.send_command("state")
        state = self._get_latest_state(retry_limit=10)
        
        if not state:
            self.conn.send_command("ready")
            time.sleep(1.0)
            state = self._get_latest_state()

        if not state:
            raise RuntimeError("无法连接到游戏，请确保 CommunicationMod 已启动")

        self.last_state = state
        
        # 2. 启动逻辑
        cmds = state.get('available_commands', [])
        if 'start' in cmds:
            self.conn.send_command("start ironclad")
            time.sleep(2.0)
            state = self._get_latest_state()
        
        # 3. 进入自动导航
        self.last_state = self._process_non_combat(state)
        
        return encode_state(self.last_state), {}

    def step(self, action):
        self.steps_since_reset += 1
        prev_state = self.last_state
        
        # --- 1. 执行 AI 动作 ---
        cmd = self.mapper.decode_action(action, prev_state)
        
        # 如果当前状态已经是 None，说明上一步出问题了，强制刷新
        if not cmd:
            self.conn.log(f"⚠️ 动作解码失败 (Action {action})，尝试刷新状态...")
            self.conn.send_command("state")
            cmd = "state"
        
        self.conn.send_command(cmd)
        
        # 动画等待逻辑
        if "play" in cmd:
            self._wait_for_animation(0.6)
        elif "end" in cmd:
            self._wait_for_new_turn()
        elif "potion" in cmd:
            self._wait_for_animation(0.5)
        else:
            time.sleep(0.2)

        # --- 2. 获取新状态 ---
        # 这里是关键：必须死等拿到有效状态
        current_state = self._get_latest_state(retry_limit=20)
        
        if not current_state:
            # 如果真的拿不到状态，说明游戏可能崩了，或者 Mod 死了
            self.conn.log("⚠️ 严重：连续多次获取状态失败！")
            # 此时返回上一次的状态避免报错，但在 reward 里给个惩罚
            return encode_state(prev_state), 0, True, False, {}

        # --- 3. 处理非战斗环节 (自动导航) ---
        # 这会一直运行直到下一次战斗开始
        final_state = self._process_non_combat(current_state)
        
        # --- 4. 计算奖励 ---
        step_reward = self._calculate_reward(prev_state, final_state)
        
        # 累加：如果在 process_non_combat 期间发生变化（如回血、进阶），也算分
        # 注意：这里简化了，只对比 step 前后的状态
        
        self.last_state = final_state
        
        # --- 5. 终止条件 ---
        terminated = False
        if final_state and 'game_state' in final_state:
            screen = final_state['game_state'].get('screen_type', 'NONE')
            if screen in ['GAME_OVER', 'VICTORY']:
                terminated = True
                if screen == 'VICTORY': step_reward += 100
                else: step_reward -= 10
                self.conn.log(f"游戏结束: {screen}")

        truncated = self.steps_since_reset > 2000

        return encode_state(final_state), step_reward, terminated, truncated, {}

    # =========================================================================
    # 核心修复：更鲁棒的非战斗处理
    # =========================================================================
    def _process_non_combat(self, state):
        """
        死循环处理非战斗状态，直到：
        1. 进入战斗 (COMBAT)
        2. 游戏结束 (GAME_OVER/VICTORY)
        3. 真的卡住了 (抛出异常或死等)
        """
        stuck_counter = 0
        
        while True:
            # 0. 状态有效性检查 (防御性编程)
            if not state or 'game_state' not in state or 'available_commands' not in state:
                self.conn.log(f"⚠️ 状态无效 (None 或 缺字段)，正在重试... ({stuck_counter})")
                self.conn.send_command("state")
                time.sleep(0.5)
                state = self._get_latest_state()
                stuck_counter += 1
                if stuck_counter > 10:
                    # 如果连续 10 次都拿不到状态，尝试发个 return 盲修
                    self.conn.send_command("return") 
                continue

            game_state = state['game_state']
            screen = game_state.get('screen_type')
            cmds = state.get('available_commands', [])
            room_phase = game_state.get('room_phase', '')

            # 1. 判定是否为战斗
            # 只有当 screen 是 COMBAT 且 指令里确实有 play/end 时，才算准备好了
            # 仅仅 screen=COMBAT 但 cmds=[] 是不行的
            is_combat_screen = (screen == 'COMBAT') or (room_phase == 'COMBAT')
            can_combat_act = ('play' in cmds) or ('end' in cmds)
            
            # 如果是游戏结束，直接返回
            if screen in ['GAME_OVER', 'VICTORY']:
                return state

            # 如果确实进入了战斗模式，并且可以操作
            if is_combat_screen and can_combat_act:
                # 再次确认手牌
                state = self._ensure_hand_drawn(state)
                return state
            
            # 如果显示是战斗，但没指令 (比如正在发牌动画中)，等待
            if is_combat_screen and not can_combat_act:
                self.conn.log("进入战斗界面，但在等待指令...")
                time.sleep(0.5)
                self.conn.send_command("state")
                state = self._get_latest_state()
                continue

            # 2. 非战斗决策
            action_cmd = None
            
            # 优先点确认/继续
            for kw in ['confirm', 'proceed', 'leave', 'start', 'next']:
                if kw in cmds: 
                    action_cmd = kw; break
            
            # 其次选选项
            if not action_cmd and 'choose' in cmds:
                action_cmd = "choose 0"
            
            # 再次尝试 return/skip
            if not action_cmd:
                if 'return' in cmds: action_cmd = 'return'
                elif 'skip' in cmds: action_cmd = 'skip'

            # 3. 执行决策
            if action_cmd:
                self.conn.log(f"[Auto] {screen} -> {action_cmd}")
                self.conn.send_command(action_cmd)
                stuck_counter = 0 # 重置卡死计数器
                
                # 动态等待：地图稍微久一点
                wait_t = 0.5 if screen == 'MAP' else 0.2
                time.sleep(wait_t)
                state = self._get_latest_state()
            else:
                # [关键修复] 如果没指令，千万不要 return，而是死等刷新
                stuck_counter += 1
                if stuck_counter % 5 == 0:
                    self.conn.log(f"⚠️ 卡在界面: {screen}, Cmds: {cmds} | 正在重试...")
                
                self.conn.send_command("state")
                time.sleep(0.5)
                state = self._get_latest_state()
                
        return state

    # =========================================================================
    # 辅助函数优化
    # =========================================================================
    
    def _get_latest_state(self, retry_limit=5):
        """
        获取状态，带有极强的重试机制。
        只有当返回的 JSON 包含 'available_commands' 时才视为有效。
        """
        for i in range(retry_limit):
            s = self.conn.receive_state()
            
            # 检查是否为有效状态
            if s and isinstance(s, dict) and 'available_commands' in s:
                return s
            
            # 如果无效，稍微等一下再读（可能是粘包或者还在传输）
            time.sleep(0.1)
            
            # 每 3 次失败主动请求一次刷新
            if i % 3 == 2:
                self.conn.send_command("state")
                
        return None # 真的拿不到

    def _ensure_hand_drawn(self, state):
        for _ in range(20):
            combat = state.get('game_state', {}).get('combat_state', {})
            hand = combat.get('hand', [])
            draw = combat.get('draw_pile', [])
            discard = combat.get('discard_pile', [])
            
            if len(hand) > 0 or (len(draw) == 0 and len(discard) == 0):
                return state
            
            time.sleep(0.1)
            self.conn.send_command("state")
            state = self._get_latest_state() or state
        return state

    def _wait_for_animation(self, duration):
        time.sleep(duration)

    def _wait_for_new_turn(self):
        # 简单粗暴的等待：发 end 后，一直查状态，直到 'play' 出现
        time.sleep(0.5)
        for _ in range(50): # 10秒超时
            self.conn.send_command("state")
            state = self._get_latest_state()
            if not state: continue
            
            cmds = state.get('available_commands', [])
            screen = state.get('game_state', {}).get('screen_type')
            
            if screen in ['GAME_OVER', 'VICTORY']: return
            if 'play' in cmds: return # 我的回合
            
            time.sleep(0.2)

    def action_masks(self):
        return self.mapper.get_mask(self.last_state)

    def _calculate_reward(self, prev, curr):
        if not prev or not curr: return 0
        r = 0
        try:
            # 简单的血量/杀怪逻辑
            game_p = prev.get('game_state', {})
            game_c = curr.get('game_state', {})
            
            # 进层奖励
            if game_c.get('floor', 0) > game_p.get('floor', 0):
                r += 5.0

            if 'combat_state' in game_p and 'combat_state' in game_c:
                cp = game_p['combat_state']
                cc = game_c['combat_state']
                
                # 杀怪
                mon_p = [m for m in cp.get('monsters',[]) if not m['is_gone']]
                mon_c = [m for m in cc.get('monsters',[]) if not m['is_gone']]
                if len(mon_c) < len(mon_p):
                    r += 20.0
                
                # 掉血惩罚
                hp_p = cp['player']['current_hp']
                hp_c = cc['player']['current_hp']
                if hp_c < hp_p:
                    r -= (hp_p - hp_c) * 0.2
        except: pass
        return r