# 积存金监控脚本详细说明

更新日期：2026-07-20

## 1. 脚本用途

`gold_monitor.py` 是一个长期后台运行的积存金价格监控和网格交易提醒脚本。它定时获取黄金报价，根据当前持仓、网格间距、手续费和最低利润要求判断是否产生买入或卖出提醒，并通过企业微信群机器人或 Server酱发送通知。

脚本只负责取价、计算和提醒，不会连接银行账户，也不会自动提交真实订单。

重要行为：当前版本在发出买入或卖出提醒后，默认你已经按提醒成交，并立即修改 `state.json` 中的持仓。如果实际没有操作，必须使用 `bought` / `sold` 命令及时修正状态。

## 2. 文件说明

| 文件 | 作用 |
| --- | --- |
| `gold_monitor.py` | 主程序，全部可修改参数都在文件顶部“配置区”。 |
| `state.json` | 当前锚点、持仓和满仓提醒状态，属于重要业务数据。 |
| `state.json.bak` | 每次更新状态前保留的最近有效备份。 |
| `state.json.lock` | 协调后台进程和命令行操作的文件锁，不要手工编辑。 |
| `gold_monitor.log` | 当前日志，达到 5 MB 后自动轮转。 |
| `gold_monitor.log.1` 等 | 历史轮转日志，最多保留 3 份。 |
| `requirements.txt` | Python 依赖及验证过的版本。 |
| `tests` | 自动化测试。 |

## 3. 配置区

所有参数均硬编码在 `gold_monitor.py` 顶部。修改并保存后，需要重启 `GoldMonitor` 计划任务才能让后台进程加载新值。

### 3.1 交易参数

```python
BUY_FEE_RATE = 0.0
SELL_FEE_RATE = 0.005
MIN_PROFIT_RATE = 0.01
GRID_STEP_PCT = 0.012
LOT_GRAMS = 2
MAX_LOTS = 10
```

| 参数 | 当前值 | 含义 |
| --- | ---: | --- |
| `BUY_FEE_RATE` | `0.0` | 买入手续费率。`0.001` 表示 0.1%。 |
| `SELL_FEE_RATE` | `0.005` | 卖出或赎回手续费率，当前为 0.5%。 |
| `MIN_PROFIT_RATE` | `0.01` | 扣除手续费后要求的最低净利润率，当前为 1%。 |
| `GRID_STEP_PCT` | `0.012` | 买入网格间距，当前每跌 1.2% 触发一格。 |
| `LOT_GRAMS` | `2` | 每份克数，仅用于通知里的预计利润金额。 |
| `MAX_LOTS` | `10` | 最大持仓份数，防止单边下跌时无限补仓。 |

比例参数必须填写小数。例如 1.2% 应写成 `0.012`，不能写 `1.2`。

### 3.2 运行参数

```python
POLL_INTERVAL = 30
MAX_BACKOFF = 900
HEARTBEAT_TICKS = 10
```

| 参数 | 当前值 | 含义 |
| --- | ---: | --- |
| `POLL_INTERVAL` | `30` | 正常情况下每 30 秒取价一次，最小允许值为 5 秒。 |
| `MAX_BACKOFF` | `900` | 连续取价失败时，最长等待 900 秒，也就是 15 分钟。 |
| `HEARTBEAT_TICKS` | `10` | 每成功取价 10 次，记录一条正常行情心跳日志。 |

### 3.3 心跳频率用来做什么

心跳的作用是：**在没有买卖信号、没有错误的普通时段，定期留下一条“程序仍在正常取价”的日志证据，同时避免每次轮询都写日志。**

当前心跳间隔约为：

```text
HEARTBEAT_TICKS × POLL_INTERVAL
= 10 × 30 秒
= 300 秒
= 5 分钟
```

心跳日志示例：

```text
[2026-07-20 10:53:53] 现价 877.17(京东) | 持仓 3 份 | 下格买入 857.79 | 最近卖出 881.30
```

心跳有以下边界：

- 它不是企业微信通知，不会每 5 分钟往群里发消息。
- 它不是 TCP/HTTP 保活，不负责维持网络连接。
- 只有成功取到价格的轮次才累计 `HEARTBEAT_TICKS`。
- 买卖信号、启动、切换备用源、连续失败和恢复会立即写日志，不等待心跳。
- 每分钟记录一次：保持 `POLL_INTERVAL = 30`，设置 `HEARTBEAT_TICKS = 2`。
- 每 10 分钟记录一次：保持 30 秒轮询，设置 `HEARTBEAT_TICKS = 20`。
- 心跳越频繁，排障信息越密集，但日志增长越快；通常 5 分钟比较合适。

### 3.4 通知参数

```python
WECOM_WEBHOOK = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=..."
SERVERCHAN_SENDKEY = ""
```

- `WECOM_WEBHOOK`：企业微信群机器人的完整 webhook。
- `SERVERCHAN_SENDKEY`：可选的 Server酱 SendKey，不使用时保持空字符串。
- 两个渠道可以同时配置，脚本会分别发送并分别记录结果。
- webhook 等同于群机器人发送凭据。不要公开脚本或提交到公开仓库；泄露后应在企业微信后台删除旧机器人并重新创建。

## 4. 买入逻辑

### 4.1 空仓

空仓时，`anchor` 是买入锚点。价格上涨时锚点跟随上涨，价格下跌时锚点不下移。

首次买入触发价：

```text
anchor × (1 - GRID_STEP_PCT)
```

例如锚点为 900 元/克、网格为 1.2%，触发价约为：

```text
900 × (1 - 0.012) = 889.20 元/克
```

### 4.2 已有持仓

已有持仓时，脚本使用最后一笔持仓价格作为下一格参考价。价格跌满一格时提醒买入一份。

如果一次跳跌跨过多格，脚本会一次提醒买入多份，但不会超过 `MAX_LOTS`；这些份额以本次实际行情价格记录。

达到 `MAX_LOTS` 后只提醒一次“持仓已满”，此后不再重复提醒，直到持仓减少或重新出现可买空间。

## 5. 卖出与手续费逻辑

每一笔持仓单独计算目标卖出价。

```text
买入实际成本 = 买入价 × (1 + BUY_FEE_RATE)

回本价 = 买入实际成本 ÷ (1 - SELL_FEE_RATE)

目标卖出价 = 买入实际成本 × (1 + MIN_PROFIT_RATE)
             ÷ (1 - SELL_FEE_RATE)
```

只有当前价格达到该笔持仓的目标卖出价，才会生成卖出提醒。利润通知已经扣除买入和卖出手续费。

如果同一轮出现卖出信号，脚本优先生成卖出提醒，并跳过该轮买入判断，避免同一个价格同时通知买入和卖出。

## 6. 状态文件

示例：

```json
{
  "anchor": 900.92,
  "lots": [
    {
      "price": 889.53,
      "time": "2026-07-13 09:26"
    }
  ]
}
```

- `anchor`：空仓时使用的最高跟随锚点。
- `lots`：每笔持仓记录。
- `price`：该笔买入价。
- `time`：记录时间。
- `manual`：通过 `bought` 命令添加时为 `true`，不影响计算。
- `full_warned`：达到最大持仓后的内部去重标记，可能不存在。

后台监控和 `bought` / `sold` 命令都会先取得 `state.json.lock`，完成读、改、写后再释放。写入采用临时文件和原子替换，写入前会保留有效的 `state.json.bak`。

如果主状态损坏，程序尝试读取备份；主文件和备份都无效时，程序会退出，而不是把持仓错误地当成空仓。

## 7. 数据源和故障处理

取价顺序：

1. 京东金融积存金接口：`ms.jr.jd.com`。
2. 京东失败后切换新浪 Au(T+D)：`hq.sinajs.cn`。

日志和通知会注明当前使用“京东”还是“新浪”。两个报价品种并不完全相同，备用源主要用于主接口短时不可用；极端情况下需要人工核对报价差异。

GET 请求会对连接错误、读取错误、HTTP 429 和常见 5xx 错误进行有限重试。主备源都失败后，等待时间按连续失败次数增长：

```text
第 1 次失败：60 秒
第 2 次失败：120 秒
第 3 次失败：240 秒
第 4 次失败：480 秒
第 5 次及以后：最多 900 秒
```

成功恢复后，轮询间隔回到 30 秒，并记录恢复日志。

## 8. 日志

日志采用 UTF-8 编码。单个 `gold_monitor.log` 达到 5 MB 后轮转，最多保留：

```text
gold_monitor.log
gold_monitor.log.1
gold_monitor.log.2
gold_monitor.log.3
```

主要日志包括启动、心跳、数据源切换、取价失败与恢复、买卖提醒、通知结果、状态恢复和未处理异常 traceback。

## 9. 日常命令

在 `E:\code\py\monitor\gold` 目录执行：

```powershell
# 查看行情、持仓和触发价，不修改状态
python .\gold_monitor.py status

# 发送一条真实测试通知
python .\gold_monitor.py --test

# 记录实际买入 1 份
python .\gold_monitor.py bought 899.5

# 记录实际买入 2 份
python .\gold_monitor.py bought 899.5 2

# 删除买入价最接近 899.5 的一笔持仓
python .\gold_monitor.py sold 899.5

# 删除所有持仓
python .\gold_monitor.py sold all

# 清空持仓并重置锚点，谨慎执行
python .\gold_monitor.py clear
```

`bought` 不允许非正份数，也不允许记录后超过 `MAX_LOTS`。`sold` 的价格匹配容差为 1%，避免误删差异过大的持仓。

## 10. 修改配置后生效

保存 `gold_monitor.py` 后，已经运行的后台进程不会自动加载新代码。执行：

```powershell
Stop-ScheduledTask -TaskName GoldMonitor
Start-ScheduledTask -TaskName GoldMonitor
Get-ScheduledTask -TaskName GoldMonitor | Select-Object TaskName, State
Get-Content -Encoding UTF8 -Tail 20 .\gold_monitor.log
```

任务应显示 `Running`，日志应出现新的“启动监控”和通知发送结果。

## 11. 测试和 IDE 导入

`monitor`、`gold` 和 `tests` 都是标准 Python 包。测试使用：

```python
from monitor.gold import gold_monitor as gm
```

PyCharm 项目根目录应为 `E:\code\py`。不要单独把 `tests` 目录作为项目打开，否则 IDE 无法从项目根找到 `monitor` 包。

从项目根目录 `E:\code\py` 执行：

```powershell
python -m unittest monitor.gold.tests.test_gold_monitor -v
python -m py_compile monitor\gold\gold_monitor.py
python -m pip check
```

测试使用临时状态目录，不修改真实 `state.json`，也不会发送真实买卖通知。

## 12. 当前开机自启配置

当前程序不是系统级 Windows Service，而是任务计划程序中的登录自启任务：

| 项目 | 当前值 |
| --- | --- |
| 任务名 | `GoldMonitor` |
| 触发器 | Windows 用户登录时 |
| 程序 | `C:\Users\a\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe` |
| 参数 | `"E:\code\py\monitor\gold\gold_monitor.py"` |
| 工作目录 | `E:\code\py\monitor\gold` |
| 重复实例 | 忽略新实例 |
| 失败重启 | 每 1 分钟一次，最多 99 次 |

它必须在用户登录后才运行。电脑停在登录界面或用户注销后不会运行。

## 13. 换电脑重新配置

### 13.1 旧电脑停止任务

```powershell
Stop-ScheduledTask -TaskName GoldMonitor
```

确认停止后再复制项目，避免新旧电脑同时运行并分别修改状态。

### 13.2 必须复制的文件

```text
gold_monitor.py
state.json
requirements.txt
monitor\__init__.py
monitor\gold\__init__.py
monitor\gold\tests（建议）
README.md
```

不需要复制 `__pycache__`、`.venv` 和日志。复制后必须核对 `state.json` 与真实持仓。

### 13.3 安装环境

```powershell
$ProjectDir = 'E:\code\py\monitor\gold'
Set-Location $ProjectDir
py -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
& .\.venv\Scripts\python.exe .\gold_monitor.py status
```

确认状态正确后，可执行 `--test` 发送真实测试通知。

### 13.4 创建登录自启任务

```powershell
$TaskName = 'GoldMonitor'
$ProjectDir = 'E:\code\py\monitor\gold'
$Pythonw = Join-Path $ProjectDir '.venv\Scripts\pythonw.exe'
$Script = Join-Path $ProjectDir 'gold_monitor.py'
$User = "$env:USERDOMAIN\$env:USERNAME"

$Action = New-ScheduledTaskAction `
    -Execute $Pythonw `
    -Argument ('"{0}"' -f $Script) `
    -WorkingDirectory $ProjectDir

$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $User
$Principal = New-ScheduledTaskPrincipal `
    -UserId $User -LogonType Interactive -RunLevel Limited

$Settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -RestartCount 99 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

$Task = New-ScheduledTask `
    -Action $Action `
    -Trigger $Trigger `
    -Principal $Principal `
    -Settings $Settings `
    -Description '积存金网格监控 - 登录自启后台常驻'

Register-ScheduledTask -TaskName $TaskName -InputObject $Task -Force
Start-ScheduledTask -TaskName $TaskName
```

验收：

```powershell
Get-ScheduledTask -TaskName GoldMonitor
Get-ScheduledTaskInfo -TaskName GoldMonitor
Get-Content -Encoding UTF8 -Tail 30 .\gold_monitor.log
```

任务状态应为 `Running`。`LastTaskResult` 为 `267009` / `0x41301` 表示任务正在运行，不是故障。

## 14. 安全和备份

- webhook 明文保存在脚本中，便利性高但泄露风险也高，不要公开脚本或仓库。
- 每次手工买卖后核对真实持仓与 `state.json`。
- 定期外部备份 `gold_monitor.py`、`state.json`、`requirements.txt` 和本说明文档。
- 不要只依赖 `state.json.bak`；它用于单次文件损坏恢复，不是长期备份。
- 换机或修改策略后，第一次启动前必须人工核对持仓、费率、网格和通知地址。
