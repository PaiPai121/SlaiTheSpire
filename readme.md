# 🗡️ Slay the Spire Reinforcement Learning (RL) Agent

基于 **Gymnasium** 和 **Stable-Baselines3 (Maskable PPO)** 构建的《杀戮尖塔》强化学习训练环境。

本项目实现了一个与游戏 **[CommunicationMod](https://github.com/ForgottenArbiter/CommunicationMod)** 交互的 Python 环境，在这个环境中实现对AI的训练。

## 🛠️ 目录结构

```text
Project Root/
├── main.py                 # 训练入口，配置模型与回调函数
├── spire_env/              # Gym 环境包
│   ├── env.py              # 主环境类 (SlayTheSpireEnv)，负责组装各模块
│   ├── definitions.py      # 动作空间与观察空间定义
│   ├── interface.py        # 底层 Stdout/Stdin 通讯接口
│   └── logic/              # [核心] 逻辑处理模块
│       ├── game_io.py      # 状态读取与缓冲区清洗
│       ├── combat.py       # 战斗同步与防抖逻辑
│       ├── navigator.py    # 非战斗场景自动导航 (地图/事件/商店)
│       └── reward.py       # 奖励函数计算
└── utils/
    ├── action_mapper.py    # 动作编解码与 Mask 生成
    └── state_encoder.py    # 状态特征提取 (State -> Vector)
```

## 🚀 环境搭建与运行

### 1. 游戏端准备
1.  安装 Steam 版 **Slay the Spire**。
2.  订阅并启用以下创意工坊 Mod：
    * **ModTheSpire** (加载器)
    * **BaseMod** (基础库)
    * **[CommunicationMod](https://github.com/ForgottenArbiter/CommunicationMod)** (通讯接口)
    * *(可选) SuperFastMode (极速模式，推荐开启以加快训练)*

### 2. 配置 CommunicationMod
你需要修改配置，让游戏知道如何启动 Python 脚本。

1.  找到配置文件 `communication_mod.config.properties`。
    * 默认位置通常在游戏安装目录下的 `preferences` 文件夹内。
    * 如果找不到，请参考 Wiki 获取不同系统的具体路径：[ModTheSpire Wiki - SpireConfig](https://github.com/kiooeht/ModTheSpire/wiki/SpireConfig)
2.  使用记事本打开，修改 `command` 字段指向你的 Python 解释器和项目路径：

```properties
# Windows 示例 (注意路径分隔符)
command=D:/Anaconda/envs/spire_ai/python.exe D:/Projects/SlayTheSpireAI/main.py
```

### 3. Python 环境准备
建议使用 `venv` 创建虚拟环境，并通过 `requirements.txt` 安装依赖：

```bash
# 1. 创建虚拟环境
python -m venv venv

# 2. 激活虚拟环境
# Windows:
.\venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# 3. 安装项目依赖
pip install -r requirements.txt
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt # 使用清华源
```

### 4. 开始训练
1.  启动 **Slay the Spire**。
2.  在 Mod 启动器中勾选上述 Mod，点击 **Play**。
3.  游戏启动后，CommunicationMod 会自动拉起 Python 脚本。
4.  观察 Python 控制台或 `logs/ai_debug_log.txt`，看到 `>>> 环境重置 >>>` 即代表训练开始。

> **💡 性能提示**：训练开始后，建议将游戏窗口**最小化**。这可以停止游戏的图形渲染，显著降低 CPU 占用，从而提升训练 FPS。

## 📊 训练监控 (Visualization)

本项目集成了 TensorBoard 记录训练曲线（奖励变化、Loss 等）。
在训练过程中，可以在终端运行以下命令启动监控面板：

```bash
tensorboard --logdir logs/sb3
```

启动后，在浏览器访问 http://localhost:6006 即可查看实时图表。

## 📈 奖励设计 (Reward Shaping)

目前的奖励函数 (`logic/reward.py`) 包含：
* **伤害奖励**: 对敌人造成伤害 (+)。
* **格挡奖励**: 获得有效格挡（不超过敌人攻击力）(+)。
* **击杀奖励**: 消灭敌人 (++)。
* **过层奖励**: 爬到下一层 (+)。
* **受伤惩罚**: 自身掉血 (-)。

## 📝 TODO / 未来计划
* [ ] 完善商店购买逻辑（目前是强制跳过）。
* [ ] 增加更复杂的事件决策逻辑（目前多为随机或固定）。
* [ ] 接入 LSTM/Transformer 以处理长短期记忆。
* [ ] 适配其他角色（目前主要适配铁甲战士）。

---

**License**: MIT


## 🧠 Core Architecture: The "Brain" Upgrade

This project has evolved from a naive bot to a strategic agent through three fundamental architectural shifts: **Perception, Precision, and Values**.

### 1. Perception: From Hash to One-Hot (State Encoder)
* **The Problem**: Previously, cards were encoded using `zlib.crc32` hashing. To the Neural Network, "Strike" (Hash: 0.12) and "Perfected Strike" (Hash: -0.98) looked like completely unrelated random numbers. The AI was effectively "face-blind" to card identities.
* **The Solution**: We implemented a **One-Hot Encoding** system with a fixed vocabulary.
    * Each card now has a dedicated input dimension (neuron).
    * **Energy** is encoded as a One-Hot vector (0-5+) rather than a scalar, allowing the network to learn non-linear thresholds (e.g., "I can play this heavy card ONLY when energy is at state 4").
    * **Gold** is scaled using `Log10` to make the AI sensitive to early-game economy differences (50 vs 150 gold) while ignoring late-game inflation.

### 2. Decision: Action Space Flattening (Action Mapper)
* **The Problem**: The original action space was `Discrete(14)` (Card 1-10, Potion 1-3). The AI could decide *which* card to play, but not *who* to target. It defaulted to attacking the first monster, making it impossible to prioritize high-threat enemies (e.g., killing the Snecko first).
* **The Solution**: We flattened the action space to `Discrete(67)`.
    * **Formula**: `ActionID = (CardIndex * 5_Targets) + TargetIndex`.
    * This gives the AI a "sniper scope," allowing it to output specific commands like "Play Bash on Monster #2."
    * A smart `ActionMapper` dynamically masks invalid targets (dead monsters) to prune the search space.

### 3. Values: The "Fear Factor" (Reward Shaping)
* **The Problem**: A standard linear reward function treats all HP loss equally. Losing 5 HP when at 80/80 health is a minor inconvenience; losing 5 HP at 6/80 health is fatal. A linear agent often dies because it greedily trades health for damage.
* **The Solution**: We introduced a **Non-Linear Survival Penalty**.
    * **The Formula**: 
      $$R_{loss} = \text{BaseLoss} \times (1 + 2 \times (1 - \text{HPRatio})^2)$$
    * **Behavior**:
        * At **100% HP**: The penalty multiplier is ~1.0x. (Aggressive)
        * At **10% HP**: The penalty multiplier spikes to ~2.6x. (Defensive)
    * **Resource Management**: Using a potion now incurs a small negative reward (-3.0). This teaches the AI a concept of "Cost," encouraging it to save potions for Elite/Boss fights rather than wasting them on weak minions.

## 🔄 更新日志 (Changelog)
### v1.0.4 - Action Space Upgrade 
* **Targeted Capability**: The agent is no longer limited to attacking the first monster. It can now choose specific targets for cards and potions.
    * *Mechanism*: Action space flattened to `Discrete(67)`.
    * *Logic*: `ActionID = (CardIndex * 5) + TargetIndex`.
* **Smart Masking**: The `ActionMapper` now intelligently masks invalid targets (e.g., dead monsters) for targeted cards, while automatically defaulting to "Target 0" for AOE/Power cards to reduce search space.

### v1.0.3 - Perception Refactor 

#### 🧠 模型架构变更 (AI Model Architecture)
* **状态编码重构 (State Encoder Overhaul)**:
    * **From Hash to One-Hot**: 以前使用随机哈希值代表卡牌（如 `Strike = 0.123`），导致神经网络难以收敛。现在构建了固定词表，使用 **One-Hot Encoding** 独立维度表示每张卡牌。
    * *Effect*: AI 现在能像人类一样准确区分“打击”和“防御”，而不是处理模糊的浮点数。
* **特征工程优化 (Feature Engineering)**:
    * **Gold (金币)**: 线性归一化 $\rightarrow$ **对数缩放 (`log10`)**。提高了模型对低金币数量变动的敏感度。
    * **Energy (能量)**: 标量数值 $\rightarrow$ **One-Hot 向量**。帮助模型理解能量的非线性阈值（如 3费和 4费的质变）。
    * **HP (血量)**: 新增 **"濒死状态" (Critical Health)** 布尔特征（HP < 15%），强化生存本能。