# game_io.py
import time

def get_latest_state(conn, retry_limit=None):
    """
    [IO核心 - 阻塞式兜底版]
    这个函数现在承诺：**只要返回，就一定是有效数据。**
    
    它会无限循环等待 connection 的队列里出现数据。
    为了防止程序彻底死锁（比如游戏真挂了），我们可以在内部加一个长时间的警告机制。
    
    :param retry_limit: 以前是重试次数，现在这个参数被忽略，
                        或者作为'多少秒没收到数据就报警'的阈值。
    """
    
    # 1. 快速通道：如果队列里已经有数据，立刻拿走
    state = conn.receive_state(timeout=0.005) # 稍微阻塞 5ms 等待数据
    if state:
        return state
    
    # 2. 慢速通道：如果没有数据，进入死守模式
    # 我们不返回 None，而是持续轮询
    
    wait_start = time.time()
    warning_triggered = False
    
    while True:
        # 尝试阻塞读取 0.1 秒
        state = conn.receive_state(timeout=0.1)
        if state:
            return state
            
        # 如果长时间读不到数据 (比如 5秒)，说明游戏可能卡了或者指令丢了
        # 此时我们可以主动发一个 "state" 唤醒一下
        elapsed = time.time() - wait_start
        
        # 每卡 2 秒主动催一下游戏 (Keep-Alive)
        if elapsed > 2.0:
            if int(elapsed) % 2 == 0: # 简单的节流
                # print(">>> [IO] 等待数据中，主动请求刷新...")
                conn.send_command("state")
                time.sleep(0.1) # 发完稍微等一下
        
        # 极端情况保护：如果 60秒 还没数据，那肯定是游戏崩了
        # 这时候抛出异常比返回 None 要好，因为返回 None 会导致 AttributeError
        if elapsed > 60.0:
            raise RuntimeError("Game IO Timeout: 游戏超过 60 秒未响应指令")