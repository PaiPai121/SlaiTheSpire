import os
import sys
from sb3_contrib import MaskablePPO
from sb3_contrib.common.wrappers import ActionMasker
from stable_baselines3.common.logger import configure
from stable_baselines3.common.callbacks import CheckpointCallback
from spire_env.env import SlayTheSpireEnv
n_steps = 2048
# --- [新增] 自定义回调函数：存档并写日志 ---
class SmartCheckpointCallback(CheckpointCallback):
    def __init__(self, save_freq, save_path, name_prefix, connection):
        super().__init__(save_freq, save_path, name_prefix)
        self.connection = connection  # 把日志连接器传进来

    def _on_step(self) -> bool:
        # 调用父类的保存逻辑
        super()._on_step()
        # [新增] 实时步数监控
            # 这里的 n_steps 是你在 model 初始化时设置的 buffer 大小 (比如 2048)
            # 打印格式： "Step: 1520 / 2048"
            # 当左边的数达到右边的数时，就会触发一次 Update 和 TensorBoard 写入
        if self.num_timesteps % 20 == 0:
            self.connection.log(f">>> Global Step: {self.num_timesteps} / {n_steps}")
            self.connection.log(f">>> Current ncalls: {self.n_calls} / {n_steps}")
        
        # 如果这一步触发了保存 (n_calls 是当前步数)
        if self.n_calls % self.save_freq == 0:
            # 拼接文件名 (参考 SB3 的命名规则)
            filename = f"{self.name_prefix}_{self.num_timesteps}_steps"
            msg = f"【自动存档】步数: {self.num_timesteps} | 已保存至: models/{filename}.zip"
            
            # 1. 写进 ai_debug_log.txt (给你看)
            self.connection.log(msg)
            # 2. 打印到控制台 (给上帝看)
            # print(msg)
            
        return True

def mask_fn(env):
    return env.action_masks()

def main():
    # --- 1. 路径配置 ---
    current_dir = os.path.dirname(os.path.abspath(__file__))
    models_dir = os.path.join(current_dir, "models")
    logs_dir = os.path.join(current_dir, "logs", "sb3")
    
    os.makedirs(models_dir, exist_ok=True)
    os.makedirs(logs_dir, exist_ok=True)

    latest_model_path = os.path.join(models_dir, "spire_ai_latest.zip")

    # --- 2. 创建环境 ---
    env = SlayTheSpireEnv()
    env = ActionMasker(env, mask_fn)
    try:
        num_envs = env.num_envs
        env.conn.log(f"【PPO 更新检查】检测到环境数量: {num_envs}")
        env.conn.log(f"【PPO 更新检查】总收集步数阈值: {model.n_steps * num_envs}")
    except AttributeError:
        # 如果不是 VecEnv，会抛出 AttributeError，通常 num_envs = 1
        env.conn.log(f"【PPO 更新检查】环境为单实例 (num_envs = 1)。阈值为 {n_steps} 步。")
    # --- 3. 模型加载/初始化 ---
    model = None
    reset_timesteps = True

    if os.path.exists(latest_model_path):
        try:
            env.conn.log(f"检测到存档，正在加载: {latest_model_path}")
            model = MaskablePPO.load(latest_model_path, env=env)
            reset_timesteps = False
            print(">>> 模型加载完毕，继续之前的训练进度 <<<")
        except Exception as e:
            print(f"模型加载失败，将重新开始: {e}")
            model = None

    if model is None:
        print("初始化新模型...")
        model = MaskablePPO(
            "MlpPolicy",
            env,
            verbose=1,
            device="cuda",          # 确保你有 GPU，没有就写 "cpu"
            learning_rate=3e-4,     # 经典学习率
            
            # [关键修改] 视野要远
            gamma=0.995,            # 0.99 -> 0.995。因为爬塔一局很长，我们需要 AI 关注更长远的未来
            
            # [关键修改] 鼓励探索
            ent_coef=0.02,          # 熵系数。0.01 -> 0.02。
                                    # 动作空间变大了 (67维)，AI 很容易陷入“只会打目标0”的局部最优。
                                    # 加大熵系数能逼它多尝试其他目标。
            
            batch_size=256,         # 稍微加大 Batch
            n_steps=n_steps,           # 每次收集更多步数再更新
            policy_kwargs=dict(
                net_arch=[512, 512] # 网络加宽。输入有1200维，256的层有点窄了，建议 512x512
            )
        )
        reset_timesteps = True

    # 配置日志
    new_logger = configure(logs_dir, ["csv", "tensorboard"])
    model.set_logger(new_logger)


    # 打印模型当前的步数，以确定何时会触发下一次更新
    env.conn.log(f"当前模型步数 (num_timesteps): {model.num_timesteps}")
    next_update_step = model.num_timesteps - (model.num_timesteps % model.n_steps) + model.n_steps
    env.conn.log(f"下次更新/日志写入预计在步数: {next_update_step}")

    # --- [关键修改] 配置智能存档回调 ---
    # save_freq=5000: 每 5000 步存一次 (约 10-20 分钟)
    # 这样就算直接关游戏，最多也只损失几分钟的进度
    auto_save_callback = SmartCheckpointCallback(
        save_freq=1000, 
        save_path=models_dir,
        name_prefix="spire_ckpt",
        connection=env.env.conn # 把底层的 connection 对象传进去用于写日志
    )

    # --- 4. 训练循环 ---
    print("\n" + "="*40)
    print(" 训练开始！")
    print(" 每 5000 步会自动存档并记录日志")
    print(" 直接关闭游戏窗口也没关系，只会损失最后一点进度")
    print("="*40 + "\n")

    try:
        model.learn(
            total_timesteps=500000, 
            callback=auto_save_callback, 
            reset_num_timesteps=reset_timesteps
        )
        # 训练跑满后的正常保存
        model.save(latest_model_path)
        env.conn.log("训练目标达成，最终模型已保存。")

    except KeyboardInterrupt:
        # 这个通常只有你在终端按 Ctrl+C 才会触发
        print("检测到 Ctrl+C，正在紧急保存...")
        model.save(latest_model_path)
    
    except Exception as e:
        print(f"\n检测到程序错误: {e}")
        # [修改] 加上 encoding='utf-8' 防止写日志时二次崩溃
        with open(os.path.join(current_dir, "crash_log.txt"), "a", encoding='utf-8') as f:
            f.write(f"Crash Error: {str(e)}\n")
            
    finally:
        # 尝试最后的挣扎保存 (如果是被系统强杀，这步可能也不执行，所以上面的自动存档最重要)
        if model:
            try:
                model.save(latest_model_path)
            except:
                pass

if __name__ == '__main__':
    main()