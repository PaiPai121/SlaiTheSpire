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
        [Reset V2] 包含防卡死变招逻辑
        """
        super().reset(seed=seed)
        self.steps_since_reset = 0
        self.conn.log(">>> [Reset] 正在重置环境... >>>")
        
        start_time = time.time()
        last_action_time = 0
        last_screen = None
        same_screen_count = 0 
        
        while True:
            # 1. 超时保护
            if time.time() - start_time > 60:
                self.conn.log("⚠️ Reset 超时，尝试强制发送 return/cancel")
                self.conn.send_command("return")
                self.conn.send_command("cancel")
                if time.time() - start_time > 70: 
                    raise RuntimeError("Reset timeout - 无法回到游戏状态")

            # 2. 获取状态
            self.conn.send_command("state")
            state = game_io.get_latest_state(self.conn, retry_limit=2)
            
            if not state: 
                time.sleep(0.5); continue

            g = state.get('game_state') or {}
            s = g.get('screen_type')
            cmds = state.get('available_commands', [])
            
            # 卡顿计数
            if s == last_screen: same_screen_count += 1
            else: same_screen_count = 0; last_screen = s

            if same_screen_count > 10 and same_screen_count % 10 == 0:
                 self.conn.log(f"[Reset滞留] Screen: {s} | Count: {same_screen_count} | Cmds: {cmds}")

            # 3. 退出条件
            is_event_ready = (s == 'EVENT' and any(c in cmds for c in ['choose','proceed','leave']))
            is_standard_screen = s in ['MAP', 'COMBAT', 'SHOP', 'REST']
            has_play_cmd = 'play' in cmds
            
            if is_standard_screen or is_event_ready or has_play_cmd:
                self.conn.log(f">>> [Reset] 就绪! 当前界面: {s} <<<")
                self.last_state = state
                break

            # 4. 主菜单逻辑
            if s == 'MAIN_MENU' or 'start' in cmds:
                if time.time() - last_action_time > 1.0:
                    self.conn.log(">>> [Reset] 主菜单 -> start ironclad")
                    self.conn.send_command("start ironclad")
                    last_action_time = time.time()
                continue

            # 5. 智能清理
            nav = None
            if s in ['GAME_OVER', 'VICTORY'] and same_screen_count > 5:
                # 变招逻辑
                cycle = same_screen_count % 4
                if cycle == 0: nav = 'confirm'
                elif cycle == 1: nav = 'return'
                elif cycle == 2: nav = 'key enter'
                else: nav = 'proceed'
                self.conn.log(f"⚠️ [Reset] 界面卡死 ({s})，尝试变招: {nav}")
            else:
                prio = ['confirm', 'proceed', 'return', 'cancel', 'leave', 'click', 'skip']
                if s in ['GAME_OVER', 'VICTORY']:
                    if 'proceed' in cmds: nav = 'proceed'
                    elif 'confirm' in cmds: nav = 'confirm'
                else:
                    for c in prio: 
                        if c in cmds: nav = c; break
            
            if nav:
                cd = 0.8
                if time.time() - last_action_time > cd:
                    if not (s in ['GAME_OVER', 'VICTORY'] and same_screen_count > 5):
                        self.conn.log(f"[Reset] 清理界面: {nav} (Screen: {s})")
                    self.conn.send_command(nav)
                    last_action_time = time.time()
                continue
            
            time.sleep(0.3)

        self.last_state = navigator.process_non_combat(self.conn, self.last_state)
        return encode_state(self.last_state), {}

    def step(self, action):
        self.steps_since_reset += 1
        prev = self.last_state
        prev_turn = prev['game_state']['combat_state']['turn'] if 'combat_state' in prev['game_state'] else 0

        # --- [恢复日志] 打印战斗状态和决策 ---
        try:
            aname = self.mapper.get_action_name(action, prev)
            mask = self.mapper.get_mask(prev)
            valid = [self.mapper.get_action_name(i, prev) for i, m in enumerate(mask) if m]
            
            if len(valid) > 6: valid_str = str(valid[:6] + ['...'])
            else: valid_str = str(valid)
            
            combat_st = prev.get('game_state', {}).get('combat_state', {})
            e = combat_st.get('player', {}).get('energy', '?')
            h = len(combat_st.get('hand', []))
            
            # 恢复这两行日志：
            self.conn.log(f"┌─ [State] E:{e} H:{h} | 可选: {valid_str}")
            self.conn.log(f"└─ [Decision] AI选: {aname}")
        except: pass

        # --- 执行动作 ---
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