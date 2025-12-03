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
        self.conn.log(">>> 环境重置 (正在尝试开启新游戏) >>>")
        
        start_time = time.time()
        last_start_sent_time = 0
        
        # [新增] 同一个界面卡顿计数器
        last_screen_type = None
        stuck_retries = 0
        
        while True:
            # 1. 超时熔断
            if time.time() - start_time > 45: # 放宽到45秒
                self.conn.log("重置超时，强制发送 return 尝试破局...")
                self.conn.send_command("return")
                time.sleep(1.0)
                # 抛异常前最后挣扎一下
                if time.time() - start_time > 50:
                    raise RuntimeError("无法进入新游戏 (卡在菜单/结算界面)")

            # 2. 获取状态
            self.conn.send_command("state")
            state = self._get_latest_state(retry_limit=3)
            
            if not state:
                self.conn.send_command("ready")
                time.sleep(0.5)
                continue

            cmds = state.get('available_commands', [])
            game_state = state.get('game_state', {})
            screen = game_state.get('screen_type')
            
            # --- 计数器逻辑：检测是否卡在同一个界面 ---
            if screen == last_screen_type:
                stuck_retries += 1
            else:
                stuck_retries = 0
                last_screen_type = screen

            # --- 情况 A: 成功进入游戏 ---
            if screen in ['MAP', 'COMBAT', 'EVENT', 'SHOP', 'REST']:
                self.conn.log(f">>> 新游戏已就绪 ({screen})，开始训练 <<<")
                self.last_state = state
                break

            # --- 情况 B: 在主菜单 ---
            if 'start' in cmds:
                if time.time() - last_start_sent_time < 5.0:
                    self.conn.log("等待游戏加载中 (忽略旧状态)...")
                    time.sleep(1.0)
                    continue
                
                self.conn.log("检测到主菜单 -> 发送 Start")
                self.conn.send_command("start ironclad")
                last_start_sent_time = time.time()
                time.sleep(3.0) # 主菜单进游戏要久一点
                
                # 激进清理管道
                self.conn.send_command("state")
                self._get_latest_state() 
                continue

            # --- 情况 C: 清理结算/死亡画面 (智能版) ---
            nav_cmd = None
            # 优先级
            for c in ['proceed', 'return', 'confirm', 'leave']:
                if c in cmds:
                    nav_cmd = c
                    break
            
            # [特殊处理] 如果卡在 GAME_OVER 很久，尝试用 confirm 替代 proceed
            if stuck_retries > 3 and 'confirm' in cmds:
                self.conn.log(f"界面卡顿 ({screen}) -> 切换尝试 confirm")
                nav_cmd = 'confirm'
            
            if nav_cmd:
                self.conn.log(f"清理界面 ({screen}) -> {nav_cmd} (Attempt {stuck_retries})")
                self.conn.send_command(nav_cmd)
                
                # [关键修改] 根据界面类型决定等多久
                if screen in ['GAME_OVER', 'VICTORY']:
                    # 死亡/胜利动画很长，多等一会，避免连点无效
                    time.sleep(2.5) 
                elif stuck_retries > 0:
                    # 如果已经卡住了，就慢点点
                    time.sleep(1.5)
                else:
                    time.sleep(1.0)
                continue
            
            time.sleep(0.5)

        # 重置完成后，处理涅奥的选项
        self.last_state = self._process_non_combat(self.last_state)
        
        return encode_state(self.last_state), {}

    def step(self, action):
        self.steps_since_reset += 1
        prev_state = self.last_state
        
        # 获取当前的回合数 (用于后续同步)
        prev_turn = 0
        try:
            prev_turn = prev_state['game_state']['combat_state']['turn']
        except: pass

        # ============================================================
        # [日志阶段 1] 决策
        # ============================================================
        state_desc = self._get_state_summary(prev_state)
        valid_mask = self.mapper.get_mask(prev_state)
        valid_actions_idx = [i for i, m in enumerate(valid_mask) if m]
        valid_names = [self.mapper.get_action_name(i, prev_state) for i in valid_actions_idx]
        action_name = self.mapper.get_action_name(action, prev_state)
        
        self.conn.log(f"┌─ [Decision] {state_desc}")
        self.conn.log(f"├─ 可选: {valid_names}")
        self.conn.log(f"└─ AI选: {action_name} (Idx: {action})")

        # ============================================================
        # [执行阶段]
        # ============================================================
        cmd = self.mapper.decode_action(action, prev_state)
        if not cmd:
            self.conn.log(f"⚠️ 动作解码无效，尝试刷新")
            cmd = "state"
        
        self.conn.send_command(cmd)
        
        # --- 关键修改：智能等待 ---
        if "play" in cmd: 
            self._wait_for_animation(0.6)
        elif "end" in cmd: 
            # [Fix] 传入之前的回合数，强制等待回合数增加
            self._wait_for_new_turn(prev_turn) 
        elif "potion" in cmd: 
            self._wait_for_animation(0.5)
        else: 
            time.sleep(0.2)
        # ============================================================
        # [关键修复] 死锁解除
        # ============================================================
        # 在 _wait_for_new_turn 返回后，管道里的数据可能已经被读空了。
        # 此时如果直接调 _get_latest_state 里的 receive_state，会因为阻塞读取而卡死。
        # 所以必须先发一个 state 请求，推游戏一把。
        self.conn.send_command("state")
        # 获取新状态
        current_state = self._get_latest_state(retry_limit=20)
        
        if not current_state:
            self.conn.log("⚠️ 严重：获取状态失败")
            return encode_state(prev_state), 0, True, False, {}

        # 处理自动过图
        final_state = self._process_non_combat(current_state)
        
        # ============================================================
        # [日志阶段 2] 结果
        # ============================================================
        step_reward = self._calculate_reward(prev_state, final_state)
        self.last_state = final_state
        
        if step_reward != 0:
            self.conn.log(f"==> [Result] 获得奖励: {step_reward:.2f}")

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
    # [核心修复] 基于回合数判定的等待逻辑
    # =========================================================================
    def _wait_for_new_turn(self, prev_turn_num):
        """
        一直等待，直到：
        1. 游戏结束
        2. 战斗结束 (怪物死光)
        3. 现在的回合数 > 之前的回合数
        """
        self.conn.log(f"等待回合结束 (当前 Turn {prev_turn_num})...")
        
        # 给游戏一点时间去反应 'end' 指令
        time.sleep(0.5)
        
        timeout = 20.0 # 敌人回合可能会很长
        start_t = time.time()
        
        while time.time() - start_t < timeout:
            self.conn.send_command("state")
            state = self._get_latest_state()
            if not state: continue
            
            game = state.get('game_state', {})
            screen = game.get('screen_type')
            
            # 1. 游戏/战斗结束 -> 停止等待
            if screen in ['GAME_OVER', 'VICTORY', 'MAP', 'COMBAT_REWARD']:
                return
                
            # 2. 检查回合数
            curr_turn = 0
            if 'combat_state' in game:
                curr_turn = game['combat_state'].get('turn', 0)
            
            # [核心判断] 只有回合数增加了，才算等到位了
            if curr_turn > prev_turn_num:
                # 再稍微等一下让抽牌动画播完
                time.sleep(0.5)
                # 再次确认是否有 play 指令 (双保险)
                if 'play' in state.get('available_commands', []):
                    self.conn.log(f"新回合开始! (Turn {curr_turn})")
                    return
            
            # 如果回合数没变，说明还在敌人回合，或者 'end' 指令丢包了
            # 这里可以做一个兜底：如果过了 5 秒回合还没变，可能 end 没点上，补发一个
            if time.time() - start_t > 5.0 and (time.time() - start_t) < 5.5:
                # 只有在确实还在这一回合且看起来卡住时才补发
                if curr_turn == prev_turn_num and 'end' in state.get('available_commands', []):
                    self.conn.log("⚠️ 检测到回合未切换，补发 end 指令...")
                    self.conn.send_command("end")

            time.sleep(0.3)
    # --- 辅助函数：状态简报 (修复版) ---
    def _get_state_summary(self, state):
        if not state: return "Unknown"
        game = state.get('game_state', {})
        screen = game.get('screen_type', 'Unknown')
        
        # 只要看起来像战斗（即便是 Combat Reward 之前的瞬间）
        if screen == 'COMBAT' or 'combat_state' in game:
            try:
                combat = game.get('combat_state')
                # 1. 这种情况下可能 combat_state 是 None
                if not combat: 
                    return f"[战斗] (数据同步中...)"
                
                # 2. 安全读取玩家数据
                p = combat.get('player', {})
                hp = p.get('current_hp', '?')
                max_hp = p.get('max_hp', '?')
                e = p.get('energy', '?')
                
                # 3. 安全读取怪物数据
                m_list = combat.get('monsters', [])
                if m_list:
                    alive_m = len([m for m in m_list if not m.get('is_gone') and not m.get('is_dying')])
                else:
                    alive_m = 0
                    
                return f"[战斗] HP:{hp}/{max_hp} E:{e} 怪:{alive_m}只"
            except Exception as e:
                # 如果还是报错，打印具体是什么错，方便排查
                return f"[战斗] (Err: {str(e)})"
        
        return f"[{screen}]"

    # --- 以下保持之前的逻辑不变 ---
    def _process_non_combat(self, state):
        stuck_counter = 0
        while True:
            if not state or 'game_state' not in state or 'available_commands' not in state:
                # self.conn.log(f"⚠️ 状态无效重试 ({stuck_counter})") # 稍微减少刷屏
                self.conn.send_command("state"); time.sleep(0.5)
                state = self._get_latest_state(); stuck_counter += 1
                if stuck_counter > 10: self.conn.send_command("return") 
                continue

            game_state = state['game_state']
            screen = game_state.get('screen_type')
            cmds = state.get('available_commands', [])
            room_phase = game_state.get('room_phase', '')

            is_combat_screen = (screen == 'COMBAT') or (room_phase == 'COMBAT')
            can_combat_act = ('play' in cmds) or ('end' in cmds)
            
            if screen in ['GAME_OVER', 'VICTORY']: return state
            if is_combat_screen and can_combat_act:
                state = self._ensure_hand_drawn(state)
                return state
            
            if is_combat_screen and not can_combat_act:
                # self.conn.log("等待指令...") # 减少刷屏
                time.sleep(0.5); self.conn.send_command("state")
                state = self._get_latest_state(); continue

            action_cmd = None
            for kw in ['confirm', 'proceed', 'leave', 'start', 'next']:
                if kw in cmds: action_cmd = kw; break
            if not action_cmd and 'choose' in cmds: action_cmd = "choose 0"
            if not action_cmd:
                if 'return' in cmds: action_cmd = 'return'
                elif 'skip' in cmds: action_cmd = 'skip'

            if action_cmd:
                self.conn.log(f"[Auto] {screen} -> {action_cmd}")
                self.conn.send_command(action_cmd)
                stuck_counter = 0
                wait_t = 0.5 if screen == 'MAP' else 0.2
                time.sleep(wait_t); state = self._get_latest_state()
            else:
                stuck_counter += 1
                self.conn.send_command("state"); time.sleep(0.5)
                state = self._get_latest_state()
        return state

    def _get_latest_state(self, retry_limit=5):
        for i in range(retry_limit):
            s = self.conn.receive_state()
            if s and isinstance(s, dict) and 'available_commands' in s: return s
            time.sleep(0.1)
            if i % 3 == 2: self.conn.send_command("state")
        return None

    def _ensure_hand_drawn(self, state):
        for _ in range(20):
            combat = state.get('game_state', {}).get('combat_state', {})
            hand = combat.get('hand', [])
            draw = combat.get('draw_pile', [])
            discard = combat.get('discard_pile', [])
            if len(hand) > 0 or (len(draw) == 0 and len(discard) == 0): return state
            time.sleep(0.1); self.conn.send_command("state")
            state = self._get_latest_state() or state
        return state

    def _wait_for_animation(self, duration):
        time.sleep(duration)


    def action_masks(self):
        return self.mapper.get_mask(self.last_state)

    def _calculate_reward(self, prev, curr):
        if not prev or not curr: return 0
        r = 0
        try:
            game_p = prev.get('game_state', {})
            game_c = curr.get('game_state', {})
            
            # --- 1. 探索奖励 (过层) ---
            if game_c.get('floor', 0) > game_p.get('floor', 0): 
                r += 10.0

            if 'combat_state' in game_p and 'combat_state' in game_c:
                cp = game_p['combat_state']
                cc = game_c['combat_state']
                
                # --- A. 计算怪物总威胁 (Incoming Damage) ---
                # 我们需要查看上一帧(prev)怪物的意图，来判断刚才那个动作是否明智
                monsters = cp.get('monsters', [])
                total_incoming_dmg = 0
                for m in monsters:
                    if not m.get('is_gone') and 'ATTACK' in m.get('intent', ''):
                        # move_adjusted_damage 是计算过易伤/虚弱后的最终伤害
                        dmg = m.get('move_adjusted_damage', 0)
                        times = m.get('move_hits', 1) #有些怪是连击
                        total_incoming_dmg += (dmg * times)

                # --- 2. 进攻奖励 (造成伤害) ---
                def get_total_mon_hp(combat_st):
                    return sum([m['current_hp'] for m in combat_st.get('monsters',[]) if not m['is_gone']])
                
                dmg_dealt = get_total_mon_hp(cp) - get_total_mon_hp(cc)
                if dmg_dealt > 0:
                    r += dmg_dealt * 0.15  # 稍微提高伤害权重，鼓励进攻
                
                # --- 3. [关键优化] 有效防御奖励 ---
                block_p = cp['player'].get('block', 0)
                block_c = cc['player'].get('block', 0)
                block_gained = block_c - block_p
                
                if block_gained > 0:
                    # 情况1: 敌人要打我 10血，我叠了 5甲 -> 有效防御 5
                    # 情况2: 敌人要打我 5血， 我叠了 20甲 -> 有效防御 5 (多余的浪费了)
                    # 情况3: 敌人不打我 (0血)，我叠了 5甲 -> 有效防御 0
                    
                    # 计算之前的缺口 (还需要多少甲才能防住)
                    needed = max(0, total_incoming_dmg - block_p)
                    
                    # 真正的有效格挡是：我获得的甲 和 我还需要的甲 之间的较小值
                    effective_block = min(block_gained, needed)
                    
                    if effective_block > 0:
                        r += effective_block * 0.15 # 奖励有效防御
                    else:
                        # 如果完全是无效防御 (敌人没打我，或者甲已经溢出了还叠)
                        # 给一个小小的惩罚，告诉AI不要浪费能量
                        r -= 0.05 

                # --- 4. 击杀奖励 ---
                mon_p = [m for m in cp.get('monsters',[]) if not m['is_gone']]
                mon_c = [m for m in cc.get('monsters',[]) if not m['is_gone']]
                if len(mon_c) < len(mon_p):
                    r += 20.0 

                # --- 5. 受伤惩罚 (这个最重要，教会它保命) ---
                hp_p = cp['player']['current_hp']
                hp_c = cc['player']['current_hp']
                if hp_c < hp_p:
                    loss = hp_p - hp_c
                    # 掉血惩罚系数要大，痛了才长记性
                    r -= loss * 1.0 

        except Exception as e:
            pass
            
        return r