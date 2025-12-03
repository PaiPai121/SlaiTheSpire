import time
def get_latest_state(conn, retry_limit=5):
    """
    [IO核心 - 修复死锁版]
    读取最新状态。
    注意：移除了 'Drain' (continue) 逻辑，因为 stdin.readline 是阻塞的。
    贪婪读取会导致脚本在无数据时挂起，形成死锁。
    现在的策略是：读到一条有效数据就立刻返回。
    """
    for i in range(retry_limit):
        s = conn.receive_state()
        
        # 只要 JSON 结构包含 available_commands 就视为有效
        if s and isinstance(s, dict) and 'available_commands' in s:
            return s  # [关键修复] 读到就撤，绝不贪心
        
        # 如果没读到(None)或者读到了无效数据(空行/报错)
        # 稍微等一下让数据传输过来
        time.sleep(0.05)
        
        # 偶数次重试时，发送心跳包主动请求
        if i % 2 == 1: 
            conn.send_command("state")
    
    return None