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
        [Reset V7 - 慢速稳健版] 
        修复了 "点击太快导致卡死" 的问题。
        1. 结算界面等待时间延长至 1.5s (等待动画)。
        2. 引入 stuck_counter，如果 proceed 点了没反应，自动切换尝试 return。
        """
        super().reset(seed=seed)
        self.steps_since_reset = 0
        self.conn.log(">>> [Reset] 正在重置环境... >>>")
        
        start_time = time.time()
        last_action_time = 0
        stuck_counter = 0 # 重新引入卡顿计数器
        
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
            # 5. 清理逻辑 (慢速版)
            # ==================================================
            
            # [关键修改] 将结算界面的等待时间大幅延长到 1.5s
            # 只有等动画播完了，点击才有效。
            wait_t = 1.5 if s in ['GAME_OVER', 'VICTORY'] else 0.5
            
            if time.time() - last_action_time > wait_t:
                nav = None
                
                # --- A. 结算界面逻辑 ---
                if s in ['GAME_OVER', 'VICTORY']:
                    stuck_counter += 1 # 每次尝试操作都计数
                    
                    # 1. 最高优先级：确认弹窗 (解锁信息)
                    if 'confirm' in cmds:
                        nav = 'confirm'
                        stuck_counter = 0 # 成功点到确认，重置计数
                    
                    # 2. 尝试继续 (Proceed)
                    elif 'proceed' in cmds:
                        # 策略：前 5 次尝试点 proceed，如果还没退出去，说明卡住了
                        if stuck_counter <= 5:
                            nav = 'proceed'
                        else:
                            # 既然 proceed 没用，尝试用 ESC (return) 强退
                            nav = 'return'
                            if stuck_counter > 8:
                                stuck_counter = 0 # 重置循环，再试 proceed

                    # 3. 如果没有 proceed，尝试其他
                    elif 'return' in cmds:
                        nav = 'return'
                    elif 'leave' in cmds: 
                        nav = 'leave'
                    elif 'skip' in cmds:
                        nav = 'skip'
                        
                    if nav:
                        self.conn.log(f"[Reset] 结算处理: {nav} (第{stuck_counter}次尝试)")
                
                # --- B. 普通界面逻辑 ---
                else:
                    stuck_counter = 0 # 离开了结算界面，重置计数
                    prio = ['confirm', 'proceed', 'return', 'cancel', 'leave', 'click', 'skip']
                    for c in prio: 
                        if c in cmds: 
                            nav = c; break
                
                # 执行
                if nav:
                    if s not in ['GAME_OVER', 'VICTORY']: # 减少刷屏，只有非结算才详细打 log
                        self.conn.log(f"[Reset] 清理: {nav}")
                    self.conn.send_command(nav)
                    last_action_time = time.time()
            
            time.sleep(0.1)

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
        if "play" in cmd:
            time.sleep(0.01)
        self.conn.send_command(cmd)
        
        if "potion" in cmd:
            # 解析药水索引 (例如 "potion 0 0" -> index 0)
            try:
                parts = cmd.split()
                # parts[0] is 'potion', parts[1] is potion_index
                if len(parts) >= 2:
                    p_idx = int(parts[1])
                    # 调用刚才写的等待函数
                    combat.wait_for_potion_used(self.conn, prev, p_idx)
                else:
                    time.sleep(0.5) # 兜底
            except:
                time.sleep(0.5) # 解析失败的兜底
            
            # 刷新一次状态以确保后续逻辑读到最新的
            self.conn.send_command("state") 
            game_io.get_latest_state(self.conn)
        # --- 诊断与等待 ---
        elif "play" in cmd: 
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