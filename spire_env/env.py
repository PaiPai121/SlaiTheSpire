import numpy as np
import time
import gymnasium as gym
from gymnasium import spaces
from .interface import Connection
from .definitions import ObservationConfig, ActionIndex
from utils.state_encoder import encode_state
from utils.action_mapper import ActionMapper

from .logic import game_io, combat, navigator, reward

class SlayTheSpireEnv(gym.Env):
    def __init__(self):
        super(SlayTheSpireEnv, self).__init__()
        self.conn = Connection()
        self.mapper = ActionMapper()
        self.action_space = spaces.Discrete(ActionIndex.TOTAL_ACTIONS)
        self.observation_space = spaces.Box(low=-5.0, high=1000.0, shape=(ObservationConfig.SIZE,), dtype=np.float32)
        self.last_state = None
        self.steps_since_reset = 0

    def reset(self, seed=None, options=None):
        """
        [Reset V4 - 智能决策版] 
        不再瞎猜。根据 available_commands 准确判断该点什么。
        核心逻辑：在结算界面，优先处理弹窗 (cancel/confirm)，其次才是继续 (proceed)。
        """
        super().reset(seed=seed)
        self.steps_since_reset = 0
        self.conn.log(">>> [Reset] 正在重置环境... >>>")
        
        start_time = time.time()
        last_action_time = 0
        
        while True:
            # 1. 超时保护
            if time.time() - start_time > 60:
                self.conn.log("⚠️ Reset 超时，尝试强制发送 return")
                self.conn.send_command("return")
                if time.time() - start_time > 65: 
                    raise RuntimeError("Reset timeout - 无法回到游戏状态")

            # 2. 获取状态
            self.conn.send_command("state")
            state = game_io.get_latest_state(self.conn, retry_limit=2)
            
            if not state: 
                time.sleep(0.5); continue

            g = state.get('game_state') or {}
            s = g.get('screen_type')
            cmds = state.get('available_commands', [])
            
            # 3. 退出条件 (成功进入可玩状态)
            # 包括: 地图、战斗、商店、休息处，或者事件界面(且有选项)
            is_ready = False
            if s in ['MAP', 'COMBAT', 'SHOP', 'REST']: is_ready = True
            if s == 'EVENT' and any(c in cmds for c in ['choose','proceed','leave']): is_ready = True
            if 'play' in cmds: is_ready = True
            
            if is_ready:
                self.conn.log(f">>> [Reset] 就绪! 当前界面: {s} <<<")
                self.last_state = state
                break

            # 4. 主菜单逻辑 (快速开始)
            if s == 'MAIN_MENU' or 'start' in cmds:
                if time.time() - last_action_time > 1.2:
                    self.conn.log(">>> [Reset] 主菜单 -> start ironclad")
                    self.conn.send_command("start ironclad")
                    last_action_time = time.time()
                continue

            # ==================================================
            # 5. 确定性清理逻辑 (Smart Cleanup)
            # ==================================================
            
            # 冷却时间：结算界面给 1.5s 动画时间，其他界面 0.5s
            wait_t = 1.5 if s in ['GAME_OVER', 'VICTORY'] else 0.5
            
            if time.time() - last_action_time > wait_t:
                nav = None
                
                # --- [逻辑核心] 结算界面优先级 ---
                if s in ['GAME_OVER', 'VICTORY']:
                    # 1. 最高优先级：关闭解锁弹窗/确认信息
                    # 注意：'return' 在结算界面通常等同于 ESC/Skip，很有用
                    if 'confirm' in cmds: nav = 'confirm'
                    elif 'cancel' in cmds: nav = 'cancel'
                    elif 'return' in cmds: nav = 'return'
                    
                    # 2. 次级优先级：继续流程
                    elif 'proceed' in cmds: nav = 'proceed'
                    
                    # 3. 保底：点击或离开
                    elif 'leave' in cmds: nav = 'leave'
                    elif 'skip' in cmds: nav = 'skip'
                    
                # --- 普通界面优先级 ---
                else:
                    # 标准顺序：确认 > 继续 > 返回 > 离开
                    prio = ['confirm', 'proceed', 'return', 'cancel', 'leave', 'click', 'skip']
                    for c in prio: 
                        if c in cmds: 
                            nav = c; break
                
                # 执行
                if nav:
                    self.conn.log(f"[Reset] 智能清理: {nav} (Screen: {s})")
                    self.conn.send_command(nav)
                    last_action_time = time.time()
            
            time.sleep(0.2)

        self.last_state = navigator.process_non_combat(self.conn, self.last_state)
        return encode_state(self.last_state), {}

    def step(self, action):
        self.steps_since_reset += 1
        prev = self.last_state
        prev_turn = prev['game_state']['combat_state']['turn'] if 'combat_state' in prev['game_state'] else 0

        # --- 日志 ---
        try:
            aname = self.mapper.get_action_name(action, prev)
            mask = self.mapper.get_mask(prev)
            valid = [self.mapper.get_action_name(i, prev) for i, m in enumerate(mask) if m]
            valid_str = str(valid[:6] + ['...']) if len(valid) > 6 else str(valid)
            
            combat_st = prev.get('game_state', {}).get('combat_state', {})
            e = combat_st.get('player', {}).get('energy', '?')
            h = len(combat_st.get('hand', []))
            
            self.conn.log(f"┌─ [State] E:{e} H:{h} | 可选: {valid_str}")
            self.conn.log(f"└─ [Decision] AI选: {aname}")
        except: pass

        # --- 执行 ---
        try:
            cmd = self.mapper.decode_action(action, prev) or "state"
        except:
            cmd = "state"

        self.conn.send_command(cmd)
        
        # --- 诊断与等待 ---
        if "play" in cmd: 
            card_cost = 0
            try:
                if action <= 9:
                    c = prev['game_state']['combat_state']['hand'][action]
                    card_cost = c.get('cost', 0)
            except: pass
            combat.wait_for_card_played(self.conn, prev, card_cost)
            
        elif "end" in cmd: 
            combat.wait_for_new_turn(self.conn, prev_turn)
        else: 
            time.sleep(0.02); self.conn.send_command("state")

        # --- 获取新状态 ---
        self.conn.send_command("state")
        curr = game_io.get_latest_state(self.conn, retry_limit=20)
        
        if not curr: 
            return encode_state(prev), 0, True, False, {}

        final = navigator.process_non_combat(self.conn, curr)
        rew = reward.calculate_reward(prev, final)
        
        self.last_state = final
        done = False
        
        screen = final['game_state'].get('screen_type')
        if screen in ['GAME_OVER', 'VICTORY']:
            done = True
            rew += 100 if screen == 'VICTORY' else -10
            self.conn.log(f"Game Over: {screen}")

        truncated = self.steps_since_reset > 2000

        return encode_state(final), rew, done, truncated, {}

    def action_masks(self): return self.mapper.get_mask(self.last_state)