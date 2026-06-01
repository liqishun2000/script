# AlphaZero-lite 中国象棋自对弈训练

本目录实现了一套 **AlphaZero 式**的自我对弈强化学习管线，可在本地跑通
「自对弈生成数据 → 训练策略/价值网络 → 用更强的网络继续自对弈」的完整闭环。

> 定位说明：本实现重在**让你学懂并跑通整条训练流程**。用默认/小参数能在 CPU 上
> 几分钟内看到训练在运行；但要练到「远超人类」的棋力，需要的算力是另一个数量级
> （见下方「算力现实」）。

## 文件结构

| 文件 | 作用 |
|---|---|
| `config.py` | 所有超参数（网络大小、MCTS 模拟数、对局数、学习率、路径等） |
| `network.py` | 策略-价值网络（ResNet）：输入 15×10×9，输出 8100 维策略 + 标量价值 |
| `mcts.py` | PUCT 蒙特卡洛树搜索，由网络引导 |
| `selfplay.py` | 用「网络 + MCTS」自我对弈，产出训练样本 (棋面, 落子分布π, 胜负z) |
| `train.py` | 主循环：自对弈 → 训练 → 保存断点（支持 Ctrl+C 续训） |
| `az_player.py` | 把训练好的模型包装成棋手，供主程序 GUI 调用 |

## 安装依赖

```bash
py -m pip install -r az/requirements.txt
```

> Windows 上若 `import torch` 报 `c10.dll` 加载失败（WinError 1114），是缺少
> **Microsoft Visual C++ 运行库**，安装一次即可：
> `winget install --id Microsoft.VCRedist.2015+.x64 -e`

## 开始训练

```bash
# 在 game 目录下运行
py az/train.py                       # 用默认配置开始（可随时 Ctrl+C 中断）
py az/train.py --iters 5             # 只跑 5 轮迭代
py az/train.py --games 4 --sims 40 --steps 100   # 自定义规模

# 快速验证整条管线能跑通（棋力低，仅冒烟测试）：
py az/train.py --iters 1 --games 8 --sims 12 --steps 4 --max-moves 18
```

- 训练断点保存在 `az/checkpoints/`（`latest.pt` 续训用，`best.pt` 供对弈用）。
- 经验回放保存在 `az/data/replay.pkl`。
- **中断后再次运行会自动从断点继续**。

## 在 GUI 中对战训练出的模型

主程序 `chinese_chess.py` 右侧「AI 引擎」选择 **AlphaZero** 即可。
- 若已有 `checkpoints/best.pt`，会加载它；
- 若还没训练，会用随机初始化网络（很弱），仅用于验证链路。

难度（简单/普通/困难/大师）对应对弈时的 MCTS 模拟次数（50 / 200 / 600 / 1200）。

## 关键设计

- **状态编码**：15 个 10×9 平面（己方 7 种子力 + 对方 7 种 + 走子方标记）。
- **动作空间**：`from*90 + to` 共 8100，非法走法在 MCTS 中通过合法走法集合屏蔽。
- **价值视角**：网络输出的 value 是「当前走子方」的预期胜负，MCTS 回溯时逐层取反。
- **探索**：根节点加狄利克雷噪声，前 `TEMP_MOVES` 步按访问次数温度采样。

## 算力现实（务必了解）

- AlphaZero 当年用 **数千块 TPU** 自对弈训练。象棋状态空间比围棋小，但
  **单机消费级 GPU 从零训练到超越人类仍不现实**（需要百万级对局、数周到数月）。
- 本实现的瓶颈在**纯 Python 的走法生成**（`xiangqi_core.legal_moves` 每步要克隆棋盘并判将）。
  要做认真的训练，应先把它换成**位棋盘 / C 扩展 / Cython**，并用**多进程并行自对弈**，
  通常能提速几十到上百倍。
- 想直接获得「远超人类」的对手，最划算的是用现成的超强引擎 **Pikafish**
  （主程序「AI 引擎」选 Pikafish，见 `../pikafish_engine.py` 的下载说明）。

## 可继续改进的方向

1. 走法生成位棋盘化 / 写成 C 扩展，自对弈多进程并行。
2. 加入**评估对局**：新模型 vs 旧 best，胜率达标才替换 best（更稳）。
3. 引入**长将判负 / 重复局面判和**等完整规则，避免和棋样本过多。
4. 用更大的网络（更多残差块、更宽通道）与更多 MCTS 模拟。
5. 模型导出为 NNUE，接入 alpha-beta 搜索（更接近现代强引擎做法）。
