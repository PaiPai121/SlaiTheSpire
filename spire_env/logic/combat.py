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
    except:
        conn.log("[Wait] ❌ 获取基准值失败，默认等待0.5s")
        time.sleep(0.5)
        return

    # 1. 物理冷却 (给游戏一点反应时间，防止读到由于网络延迟还没发出的旧包)
    time.sleep(0.1) 
    
    start_t = time.time()
    
    # 保持 4.0 秒超时作为兜底
    while time.time() - start_t < 4.0:
        # 主动请求刷新 (虽然通常不需要，因为游戏会自动发，但为了保险)
        conn.send_command("state")
        
        # [优化] 减少 retry_limit，改为高频单次读取
        state = get_latest_state(conn, retry_limit=2)
        
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
            
            c_c = g.get('combat_state')
            if not c_c: 
                # 读到了数据但不是战斗状态，立即读下一条，不 sleep
                continue 

            curr_e = c_c['player']['energy']
            curr_h = len(c_c.get('hand', []))
            
            # --- 场景 B: 判定成功 ---
            
            # 1. 能量变了
            if curr_e != base_e:
                # conn.log(f"[Wait] ✅ 能量变化 ({base_e}->{curr_e})") 
                return

            # 2. 手牌数变少了
            if curr_h < base_h:
                # conn.log(f"[Wait] ✅ 手牌减少 ({base_h}->{curr_h})")
                return

            # 3. 手牌内容变了
            if curr_h == base_h:
                curr_ids = sorted([c.get('id','') for c in c_c.get('hand', [])])
                if curr_ids != base_ids:
                    return
            
            # --- [核心修改] ---
            # 如果走到了这里，说明读到的这条状态还未满足条件（可能是动画过程中的中间态）。
            # 关键：【不要 sleep！】
            # 直接 continue 进入下一次循环，立刻读取缓冲区里的下一条数据。
            # 这样可以以 1000+ FPS 的速度消耗积压的数据，瞬间追上最新状态。
            
        except Exception:
            pass
        
        # 只有在发生异常时才 sleep 一小下，防止死循环报错
        # 正常逻辑下，这里不应该有 sleep
    
    conn.log(f"[Wait] ⚠️ 等待卡牌打出超时 (4s) - 强制继续")

# combat.py 新增函数

def wait_for_potion_used(conn, prev_state, potion_index):
    """
    [药水锁] 确保药水真的被扔出去了。
    原理：监控指定 index 的药水栏位，直到其内容发生变化。
    """
    conn.log(f"[Wait] 正在确认药水 (Slot {potion_index}) 生效...")
    
    # 1. 获取投掷前的药水名字 (用于对比)
    try:
        prev_potions = prev_state['game_state']['combat_state']['potions']
        target_potion = prev_potions[potion_index]
        prev_name = target_potion.get('name', 'N/A')
        
        # 如果本来就是空的，那肯定是由于逻辑错误导致的，直接跳过
        if target_potion.get('id') == 'Potion Slot':
            conn.log("[Wait] ⚠️ 尝试投掷空药水槽，跳过等待")
            return
            
    except Exception as e:
        conn.log(f"[Wait] 获取药水基准值失败: {e}")
        return

    # 2. 循环检测
    start_t = time.time()
    
    # 药水动画通常较长，给 2.0 秒超时
    while time.time() - start_t < 2.0:
        conn.send_command("state")
        # 使用快速读取模式
        state = get_latest_state(conn, retry_limit=2)
        
        if not state:
            time.sleep(0.02); continue
            
        try:
            curr_potions = state['game_state']['combat_state']['potions']
            curr_potion = curr_potions[potion_index]
            curr_name = curr_potion.get('name', 'N/A')
            
            # --- 判定成功条件 ---
            # 1. 名字变了 (比如变成了 "Potion Slot" 或者被替换了)
            # 2. 或者该栏位的 has_target 属性变了 (较少见)
            if curr_name != prev_name:
                # conn.log(f"[Wait] ✅ 药水已消耗: {prev_name} -> {curr_name}")
                return
                
        except: pass
        
        # 极速消耗缓冲区，不要 sleep
        continue

    conn.log(f"[Wait] ⚠️ 药水投掷超时 (可能指令未生效或动画过长)")

def wait_for_new_turn(conn, prev_turn):
    conn.log(f"[Wait] 等待新回合 (Curr:{prev_turn})...")
    time.sleep(0.5) # 给一点初始等待，防止还没按下结束回合就检测
    
    st = time.time()
    while time.time() - st < 60.0:
        conn.send_command("state")
        s = get_latest_state(conn)
        if not s: 
            time.sleep(0.05); continue
        
        g = s.get('game_state', {})
        screen = g.get('screen_type', 'N/A')
        
        end_screens = ['VICTORY', 'GAME_OVER', 'COMBAT_REWARD', 'MAP']
        if screen in end_screens: 
            return
        
        # 检查回合数
        ct = g.get('combat_state', {}).get('turn', 0)
        cmds = s.get('available_commands', [])
        
        # 判定新回合开始的标准：
        # 1. 回合数增加
        # 2. 必须能打牌 (play) —— 这很重要，防止在敌人回合判定开始
        if ct > prev_turn and 'play' in cmds:
            conn.log(f"[Wait] 新回合侦测到: {ct}，等待抽牌稳定...")
            
            # [关键] 在这里卡住，直到手牌抽完！
            # 我们不需要返回值，只是为了在这里阻塞住
            ensure_hand_drawn(conn, s)
            return
                
        time.sleep(0.1)
    
    conn.log("[Wait] ⚠️ 等待回合超时")

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