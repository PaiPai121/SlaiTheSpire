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
        super().reset(seed=seed)
        self.steps_since_reset = 0
        self.conn.log(">>> 环境重置 >>>")
        start_time = time.time(); last_action_time = 0
        while True:
            if time.time() - start_time > 60:
                self.conn.send_command("return")
                if time.time() - start_time > 65: raise RuntimeError("Reset timeout")
            self.conn.send_command("state")
            state = game_io.get_latest_state(self.conn, retry_limit=2)
            if not state: time.sleep(0.5); continue
            g = state.get('game_state') or {}; s = g.get('screen_type'); cmds = state.get('available_commands', [])
            ready = (s in ['MAP','COMBAT','SHOP','REST']) or (s == 'EVENT' and any(c in cmds for c in ['choose','proceed','leave'])) or ('play' in cmds)
            if ready:
                self.conn.log(f">>> 就绪 ({s}) <<<")
                self.last_state = state; break
            if 'start' in cmds:
                if time.time() - last_action_time < 4.0: continue
                self.conn.log("Start Ironclad..."); self.conn.send_command("start ironclad"); last_action_time = time.time(); continue
            nav = None; prio = ['confirm', 'proceed', 'return', 'leave', 'click', 'skip']
            if 'return' in cmds and 'proceed' in cmds: prio = ['return', 'confirm', 'proceed', 'leave', 'click', 'skip']
            for c in prio: 
                if c in cmds: nav = c; break
            if nav:
                cd = 1.0 if nav == 'click' else 1.5
                if time.time() - last_action_time < cd: continue
                self.conn.log(f"Reset清理: {nav}"); self.conn.send_command(nav); last_action_time = time.time(); continue
            time.sleep(0.5)
        self.last_state = navigator.process_non_combat(self.conn, self.last_state)
        return encode_state(self.last_state), {}

    def step(self, action):
        self.steps_since_reset += 1
        prev = self.last_state
        prev_turn = prev['game_state']['combat_state']['turn'] if 'combat_state' in prev['game_state'] else 0

        try:
            aname = self.mapper.get_action_name(action, prev)
            mask = self.mapper.get_mask(prev)
            valid = [self.mapper.get_action_name(i, prev) for i, m in enumerate(mask) if m]
            if len(valid) > 6: valid = valid[:6] + ['...']
            combat_st = prev.get('game_state', {}).get('combat_state', {})
            e = combat_st.get('player', {}).get('energy', '?')
            h = len(combat_st.get('hand', []))
            self.conn.log(f"┌─ [State] E:{e} H:{h} | 可选: {valid}")
            self.conn.log(f"└─ [Decision] AI选: {aname}")
        except: pass

        cmd = self.mapper.decode_action(action, prev) or "state"
        self.conn.send_command(cmd)
        
        # --- 诊断逻辑 ---
        if "play" in cmd: 
            card_cost = 0
            try:
                if action <= 9:
                    hand = prev['game_state']['combat_state']['hand']
                    if action < len(hand):
                        card_cost = hand[action].get('cost', 0)
            except: pass
            
            # 记录我们试图打几费牌
            self.conn.log(f"[Step] 尝试打出 {card_cost} 费牌 -> 进入等待")
            combat.wait_for_card_played(self.conn, prev, card_cost)
            
        elif "end" in cmd: 
            combat.wait_for_new_turn(self.conn, prev_turn)
        else: 
            time.sleep(0.05); self.conn.send_command("state")

        self.conn.send_command("state")
        curr = game_io.get_latest_state(self.conn, retry_limit=20)
        if not curr: return encode_state(prev), 0, True, False, {}

        final = navigator.process_non_combat(self.conn, curr)
        rew = reward.calculate_reward(prev, final)
        if abs(rew) > 0.01: self.conn.log(f"==> [Reward] {rew:.2f}")
        
        self.last_state = final
        done = False
        if final['game_state'].get('screen_type') in ['GAME_OVER', 'VICTORY']:
            done = True
            rew += 100 if final['game_state']['screen_type'] == 'VICTORY' else -10
            self.conn.log(f"Game Over: {final['game_state']['screen_type']}")

        return encode_state(final), rew, done, self.steps_since_reset > 2000, {}

    def action_masks(self): return self.mapper.get_mask(self.last_state)