import time
from .game_io import get_latest_state

def wait_for_card_played(conn, prev_state, card_cost=None):
    """
    [战斗锁 - 极速响应版 - 修复缓冲区积压]
    移除循环内的强制 sleep，开启全速读取模式，防止因处理慢导致的 4s 超时。
    """
    try:
        p_c = prev_state['game_state']['combat_state']
        base_e = p_c['player']['energy']
        base_h = len(p_c.get('hand', []))
        base_ids = sorted([c.get('id','') for c in p_c.get('hand', [])])
        base_screen = prev_state.get('game_state', {}).get('screen_type')
        base_powers = len(p_c['player'].get('powers', []))
    except:
        conn.log("[Wait] ❌ 获取基准值失败，默认等待0.5s")
        time.sleep(0.5)
        return

    # 1. 物理冷却 (给游戏一点反应时间，防止读到由于网络延迟还没发出的旧包)
    time.sleep(0.1) 
    
    start_t = time.time()
    last_req_time = 0
    # 保持 4.0 秒超时作为兜底
    while time.time() - start_t < 4.0:
        # 主动请求刷新 (虽然通常不需要，因为游戏会自动发，但为了保险)
        # conn.send_command("state")
        if time.time() - last_req_time > 0.5:
            conn.send_command("state")
            last_req_time = time.time()
        
        # [优化] 减少 retry_limit，改为高频单次读取
        state = get_latest_state(conn, retry_limit=1)
        
        # 如果读取不到任何数据（缓冲区空了），才稍微睡一下避免 CPU 100%
        if not state:
            time.sleep(0.02)
            continue
        
        try:
            g = state.get('game_state', {})
            screen = g.get('screen_type')
            
            # --- 场景 A: 战斗结束 ---
            end_screens = ['VICTORY', 'GAME_OVER', 'COMBAT_REWARD', 'MAP', 'SHOP', 'REST']
            if screen in end_screens:
                return 
            
            if screen not in ['COMBAT', 'NONE'] and screen != base_screen:
                conn.log(f"[Wait] 屏幕切换 {base_screen}->{screen}，判定成功")
                return
            
            c_c = g.get('combat_state')
            if not c_c: 
                # 读到了数据但不是战斗状态，立即读下一条，不 sleep
                time.sleep(0.01)
                continue 

            curr_e = c_c['player']['energy']
            curr_h = len(c_c.get('hand', []))
            
            # --- 场景 B: 判定成功 ---
            
            # 1. 能量变了
            if curr_e != base_e:
                # conn.log(f"[Wait] ✅ 能量变化 ({base_e}->{curr_e})") 
                return

            # 2. 手牌数变少了
            if curr_h != base_h:
                # conn.log(f"[Wait] ✅ 手牌减少 ({base_h}->{curr_h})")
                return

            # 3. 手牌内容变了
            if curr_h == base_h:
                curr_ids = sorted([c.get('id','') for c in c_c.get('hand', [])])
                if curr_ids != base_ids:
                    return
            curr_powers = len(c_c['player'].get('powers', []))
            if curr_powers != base_powers: return
            # --- [核心修改] ---
            # 如果走到了这里，说明读到的这条状态还未满足条件（可能是动画过程中的中间态）。
            # 关键：【不要 sleep！】
            # 直接 continue 进入下一次循环，立刻读取缓冲区里的下一条数据。
            # 这样可以以 1000+ FPS 的速度消耗积压的数据，瞬间追上最新状态。
            
        except Exception:
            pass
        time.sleep(0.01)
        # 只有在发生异常时才 sleep 一小下，防止死循环报错
        # 正常逻辑下，这里不应该有 sleep
    
    conn.log(f"[Wait] ⚠️ 等待卡牌打出超时 (4s) - 强制继续")

# combat.py 新增函数
# combat.py

def wait_for_potion_used(conn, prev_state, potion_index, original_cmd_str):
    """
    [药水锁 - 战斗结束兼容版]
    1. 增加屏幕检测：如果药水导致战斗结束 (VICTORY/REWARD)，立即视为成功。
    2. 保持 'potion use' 语法的重试逻辑。
    """
    # --- 1. 获取基准值 ---
    target_potion_name = "N/A"
    try:
        gs = prev_state.get('game_state', {})
        potions = gs.get('combat_state', {}).get('potions') or gs.get('potions')
        target_potion_name = potions[potion_index].get('name', 'N/A')
        if potions[potion_index].get('id') == 'Potion Slot': return 
    except:
        time.sleep(1.0); return

    conn.log(f"[Wait] 正在投掷 {target_potion_name} (Slot {potion_index})...")

    # --- 2. 准备指令 ---
    cmd_full = original_cmd_str
    cmd_simple = f"potion use {potion_index}"
    
    # --- 3. 稳健循环 ---
    start_t = time.time()
    last_send_t = start_t
    retry_count = 0
    time.sleep(0.01)
    last_req_time = 0
    while time.time() - start_t < 4.0:
        time.sleep(0.1) # 稍微快一点的检测
        
        # conn.send_command("state")
        # 流量控制：每 0.5s 发一次 state，防止刷屏
        if time.time() - last_req_time > 0.5:
            conn.send_command("state")
            last_req_time = time.time()

        state = get_latest_state(conn, retry_limit=1)
        if not state:
            time.sleep(0.02); continue
        
        if state:
            g = state.get('game_state', {})
            screen = g.get('screen_type', 'N/A')
            
            # [核心修复] 如果屏幕变了(战斗结束)，说明药水肯定生效了(或者不需要了)
            # 比如扔了火焰药水怪死了，进入 COMBAT_REWARD
            if screen in ['VICTORY', 'COMBAT_REWARD', 'MAP', 'GAME_OVER']:
                conn.log(f"[Wait] ✅ 检测到战斗结束 ({screen})，药水动作视为完成")
                return

            # 常规检测：检查药水槽是否变空
            try:
                # 尝试获取药水列表
                c_potions = g.get('combat_state', {}).get('potions') or g.get('potions')
                
                if c_potions:
                    curr_name = c_potions[potion_index].get('name', 'N/A')
                    # 名字变了（变空或变其他），说明成功
                    if curr_name != target_potion_name:
                        # ==========================================================
                        # 【插入点】在此处处理特殊药水的硬直
                        # ==========================================================
                        is_chaos = "Chaos" in target_potion_name or "混沌" in target_potion_name
                        is_brew = "Entropic" in target_potion_name or "乱酿" in target_potion_name
                        
                        if is_chaos:
                            conn.log(f"[Wait] 检测到【精炼混沌】，强制等待特效结算 (3.5s)...")
                            # 强制睡眠，不发任何指令，让游戏把 3 张牌打完
                            time.sleep(3.5)
                            # 这里不需要 return，循环结束自然会退出，
                            # 或者你可以加上 return 明确退出
                            return

                        elif is_brew:
                            conn.log(f"[Wait] 检测到【乱酿】，等待药水栏填充 (1.5s)...")
                            time.sleep(1.5)
                            return
                        
                        # 普通药水，直接返回

                        if retry_count > 0:
                            conn.log(f"[Wait] ✅ 药水在第 {retry_count} 次重试后生效")
                        return
                    if time.time() - last_send_t < 1.5:
                        time.sleep(0.01)
                        continue
            except: 
                # 如果读取报错（比如数据结构变了），不要立即认为失败，继续下一轮
                pass
        
        # --- 重试机制 ---
        if time.time() - last_send_t > 0.8:
            retry_count += 1
            
            # 发送 cancel 并不是撤销药水，而是撤销可能的“卡牌悬停”状态
            # 这有助于让药水指令重新生效
            conn.send_command("cancel")
            time.sleep(0.1)
            
            # 轮换指令
            cmd_to_send = cmd_simple if (retry_count % 2 == 1) else cmd_full
            
            conn.log(f"[Wait] ⚠️ 无反应，尝试重发 -> {cmd_to_send}")
            conn.send_command(cmd_to_send)
            last_send_t = time.time()

    conn.log(f"[Wait] ❌ 药水投掷检测超时 (最终状态: {target_potion_name})")

def wait_for_new_turn(conn, prev_turn):
    """
    [等待回合 V3 - 兼容无牌/无法打牌的情况]
    修复了当手牌为0或全为状态牌(无法play)时，AI 无法识别新回合导致卡顿 20+ 秒的问题。
    """
    conn.log(f"[Wait] 等待新回合 (Curr:{prev_turn})...")
    
    # 稍微给一点时间让回合结束动画开始
    time.sleep(0.5) 
    
    st = time.time()
    while time.time() - st < 60.0:
        conn.send_command("state")
        
        # 使用极速读取，不 sleep，快速消耗缓冲区
        s = get_latest_state(conn, retry_limit=1)
        
        if not s: 
            time.sleep(0.02); continue
        
        g = s.get('game_state', {})
        screen = g.get('screen_type', 'N/A')
        
        # 1. 战斗结束检测
        end_screens = ['VICTORY', 'GAME_OVER', 'COMBAT_REWARD', 'MAP', 'SHOP', 'REST']
        if screen in end_screens: 
            return
        
        # 2. 回合数检测
        ct = g.get('combat_state', {}).get('turn', 0)
        cmds = s.get('available_commands', [])
        
        # [核心修复] 判定条件放宽：
        # 只要能 'play' (打牌) 或者能 'end' (结束回合)，都说明是我方回合
        can_act = ('play' in cmds) or ('end' in cmds)
        
        if ct > prev_turn and can_act:
            conn.log(f"[Wait] 新回合侦测到: {ct}，等待抽牌稳定...")
            ensure_hand_drawn(conn, s)
            return
        
        # 极速循环：如果还没到新回合，基本不等待，快速过掉旧数据
        time.sleep(0.01)
    
    conn.log("[Wait] ⚠️ 等待回合超时")

# [combat.py] 新增函数

def wait_for_choice_result(conn):
    """
    [选牌锁] 专门用于解决 Burning Pact / Armaments 等需要 'Choose -> Confirm' 的卡牌。
    发送 choose 后，循环等待，直到：
    1. 'confirm' 按钮出现 (最常见情况)
    2. 屏幕发生了变化 (比如有些卡选完直接就结算了)
    3. 超时 (防止死锁)
    """
    start_t = time.time()
    
    while time.time() - start_t < 2.0: # 给 2秒 足够了
        # 极速读取，不 sleep，捕捉那一瞬间的状态变化
        conn.send_command("state")
        state = get_latest_state(conn, retry_limit=1)
        
        if not state: 
            time.sleep(0.05); continue
            
        cmds = state.get('available_commands', [])
        screen = state.get('game_state', {}).get('screen_type')
        
        # 1. 成功看到确认按钮 -> 任务完成，交给 Navigator 去点
        if 'confirm' in cmds:
            # conn.log("[Wait] ✅ 选牌成功，确认按钮已出现")
            return
            
        # 2. 屏幕变了 (说明不需要确认，直接结算了，或者已经退出了选牌界面)
        # 注意：这里假设选牌界面是 HAND_SELECT 或 GRID
        if screen not in ['HAND_SELECT', 'GRID']:
            # conn.log(f"[Wait] ✅ 选牌结束，界面已切换至 {screen}")
            return

        # 还在原来的界面，且没有 confirm，说明动画还在播，继续等...
        time.sleep(0.05)
        
    # conn.log("[Wait] ⚠️ 等待选牌确认超时 (可能无需确认或卡顿)")
def ensure_hand_drawn(conn, state):
    """
    [核心修复] 等待手牌完全抽完（状态稳定）
    防止在抽牌动画过程中急着出牌导致指令被吞。
    """
    # 1. 先确保至少有 1 张牌 (原有逻辑)
    for i in range(20):
        c = state.get('game_state', {}).get('combat_state', {})
        hand = c.get('hand', [])
        if len(hand) > 0: 
            break
        time.sleep(0.1)
        conn.send_command("state")
        state = get_latest_state(conn)

    # 2. [新增] 确保手牌数量稳定不再变化
    # 连续检测 3 次，如果手牌数一样，说明抽完了
    stable_check_count = 0
    last_hand_count = len(state.get('game_state', {}).get('combat_state', {}).get('hand', []))
    
    start_t = time.time()
    while time.time() - start_t < 2.0: # 最多等 2 秒稳定期
        time.sleep(0.15) # 间隔稍微长一点，覆盖动画帧
        conn.send_command("state")
        new_state = get_latest_state(conn)
        
        if not new_state: continue
        
        curr_hand_count = len(new_state.get('game_state', {}).get('combat_state', {}).get('hand', []))
        
        if curr_hand_count == last_hand_count:
            stable_check_count += 1
            if stable_check_count >= 2: # 连续两次检测一致，认为稳定
                return new_state
        else:
            # 手牌还在变（还在抽），重置计数器
            stable_check_count = 0
            last_hand_count = curr_hand_count
            # conn.log(f"[Wait] 手牌增加中: {curr_hand_count}...") # 调试用
            
    return state