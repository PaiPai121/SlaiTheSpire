import time
import os
from sb3_contrib import MaskablePPO
from sb3_contrib.common.wrappers import ActionMasker
from spire_env.env import SlayTheSpireEnv

def mask_fn(env):
    return env.action_masks()

def main():
    # 1. 创建环境
    env = SlayTheSpireEnv()
    env = ActionMasker(env, mask_fn)
    
    # 2. 加载模型
    # 这里你可以选你想看的任何一个存档，比如 30000 步的那个
    model_path = "models/spire_ckpt_30000_steps.zip"
    
    # 如果找不到指定步数的，就找 latest
    if not os.path.exists(model_path):
        model_path = "models/spire_ai_latest.zip"

    print(f"正在加载模型: {model_path} ...")
    model = MaskablePPO.load(model_path, env=env)
    
    # 3. 开始表演
    obs, _ = env.reset()
    
    print("开始观战！(按 Ctrl+C 退出)")
    
    while True:
        # [关键] deterministic=True
        # 意思是：不要随机探索，永远只选概率最大的那个动作（AI 的最强形态）
        action, _states = model.predict(obs, action_masks=env.action_masks(), deterministic=True)
        
        obs, reward, terminated, truncated, info = env.step(action)
        
        # 如果游戏结束，自动重开
        if terminated or truncated:
            obs, _ = env.reset()

if __name__ == '__main__':
    main()