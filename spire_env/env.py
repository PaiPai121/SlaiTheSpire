import numpy as np
import time
import gymnasium as gym
from gymnasium import spaces
from .interface import Connection
from .definitions import ObservationConfig, ActionIndex
from utils.state_encoder import encode_state
from utils.action_mapper import ActionMapper

# 引入逻辑模块
from .logic import game_io, combat, navigator, reward

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

    # =========================================================================
    # Reset (核心重构：事件驱动代替固定等待)
    # =========================================================================
    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self.steps_since_reset = 0
        self.conn.log(">>> 环境重置 (极速版) >>>")
        
        start_time = time.time()
        
        while True:
            # 1. 超时熔断
            if time.time() - start_time > 60:
                self.conn.send_command("return")
                if time.time() - start_time > 65: raise RuntimeError("Reset timeout")

            # 2. 读取状态
            # Reset 阶段不需要 drain 太多，读到最新的就行
            self.conn.send_command("state")
            state = game_io.get_latest_state(self.conn, retry_limit=2)
            
            if not state: 
                time.sleep(0.1); continue # 短等待

            g = state.get('game_state') or {}
            s = g.get('screen_type', 'NONE')
            cmds = state.get('available_commands', [])
            
            # --- 就绪判定 ---
            # 地图/战斗/商店/篝火 -> 就绪
            # 事件(EVENT)且有选项/前进/离开 -> 就绪 (跳过了纯对话阶段)
            ready = (s in ['MAP','COMBAT','SHOP','REST']) or \
                    (s == 'EVENT' and any(c in cmds for c in ['choose','proceed','leave'])) or \
                    ('play' in cmds)
            
            if ready:
                self.conn.log(f">>> 就绪 ({s}) <<<")
                self.last_state = state
                break

            # --- 自动操作 ---
            action = None
            
            # A. 主菜单
            if 'start' in cmds:
                action = "start ironclad"
                self.conn.log("开始游戏...")

            # B. 过场/对话/结算
            # 优先级：确认 > 继续 > 点击(对话) > 离开
            if not action:
                for c in ['confirm', 'proceed', 'click', 'return', 'leave', 'skip']:
                    if c in cmds: 
                        action = c
                        break
            
            # --- 执行与智能等待 ---
            if action:
                # 记录操作前的特征
                prev_screen = s
                prev_cmds = cmds
                
                self.conn.send_command(action)
                
                # [关键逻辑] 动态等待状态变化
                # 不再 sleep(4.0)，而是死循环检查状态是否变了
                # 只要变了，立刻进行下一步。适配加速Mod。
                wait_start = time.time()
                
                # 超时设置：普通操作 2s，结算画面/开始游戏给 5s (容忍加载慢)
                wait_limit = 5.0 if (s in ['GAME_OVER', 'VICTORY'] or action.startswith('start')) else 2.0
                
                while time.time() - wait_start < wait_limit:
                    self.conn.send_command("state")
                    next_s = game_io.get_latest_state(self.conn, retry_limit=1)
                    
                    if next_s:
                        ng = next_s.get('game_state', {})
                        ns = ng.get('screen_type')
                        nc = next_s.get('available_commands')
                        
                        # 如果屏幕变了，或者指令变了，说明操作生效，立即跳出
                        if ns != prev_screen or nc != prev_cmds:
                            break
                    
                    # 极速轮询间隔
                    time.sleep(0.05)
            else:
                # 没操作可做，稍微等一下避免空转
                time.sleep(0.2)

        # 重置完成后，交给导航器处理开局 (如 Neow 选项)
        self.last_state = navigator.process_non_combat(self.conn, self.last_state)
        return encode_state(self.last_state), {}

    # =========================================================================
    # Step (保持不变)
    # =========================================================================
    def step(self, action):
        self.steps_since_reset += 1
        prev = self.last_state
        prev_turn = prev['game_state']['combat_state']['turn'] if 'combat_state' in prev['game_state'] else 0

        # Log
        try:
            aname = self.mapper.get_action_name(action, prev)
            self.conn.log(f"[Decision] {aname}")
        except: pass

        cmd = self.mapper.decode_action(action, prev) or "state"
        self.conn.send_command(cmd)
        
        # Wait
        if "play" in cmd: combat.wait_for_card_played(self.conn, prev)
        elif "end" in cmd: combat.wait_for_new_turn(self.conn, prev_turn)
        else: time.sleep(0.05); self.conn.send_command("state")

        # Get State
        self.conn.send_command("state")
        curr = game_io.get_latest_state(self.conn, retry_limit=20)
        if not curr: return encode_state(prev), 0, True, False, {}

        # Nav
        final = navigator.process_non_combat(self.conn, curr)
        
        # Reward
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