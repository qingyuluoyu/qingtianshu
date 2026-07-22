# Tushare Pro 使用说明

本文档说明如何在清数智算项目中使用 Tushare Pro 兼容数据接口。

当前项目使用的是 [Tushare Proxy 指南](https://teajoin.com/guide) 中的代理服务：

- SDK：`tushare`
- 代理地址：`https://teajoin.com`
- 主要返回格式：`pandas.DataFrame`
- 当前项目已配置的验证接口：`daily`

> 本文只说明数据接口调用方式，不构成任何投资建议。实时行情、历史分钟行情和特色接口是否可用，以当前账号实际权限为准。

## 1. 安装依赖

项目已经把依赖写入 `pyproject.toml` 和 `uv.lock`。

使用项目环境安装：

```bash
cd /Users/chr/Documents/青树金融交易/qingshu-agent-demo
uv sync
```

如果使用一键启动脚本，需要把依赖安装到脚本实际使用的 Hermes Python 环境：

```bash
uv pip install \
  --python /Users/chr/.hermes/hermes-agent/venv/bin/python \
  'tushare>=1.4' 'python-dotenv>=1.0'
```

## 2. 配置 Token

在项目根目录创建 `.env`：

```dotenv
TUSHARE_ENABLED=true
TUSHARE_TOKEN=YOUR_API_KEY
TUSHARE_API_URL=https://teajoin.com
TUSHARE_TIMEOUT_SECONDS=20
```

说明：

- `TUSHARE_TOKEN` 填写兑换或申请得到的 API Key。
- `TUSHARE_API_URL` 必须使用 `https://teajoin.com`，不要改成 Tushare 官方默认地址。
- 项目会自动加载 `/Users/chr/Documents/青树金融交易/qingshu-agent-demo/.env`。
- `.env` 已被 `.gitignore` 忽略，禁止提交到 Git、发到群聊或写入截图。
- `.env.example` 只放变量名和占位符，不放真实密钥。

## 3. 使用项目封装客户端

推荐在项目代码中使用 `TushareClient`，不要在业务模块中重复初始化 SDK：

```python
from app.config import Settings
from app.providers.tushare import TushareClient

settings = Settings.from_env()
client = TushareClient.from_settings(settings)

daily = client.daily(
    ts_code="000001.SZ",
    start_date="20260101",
    end_date="20260110",
)

print(daily)
```

也可以调用已支持的任意 Tushare 接口：

```python
stock_basic = client.query(
    "stock_basic",
    exchange="",
    list_status="L",
    fields="ts_code,symbol,name,area,industry,list_date",
)
```

`TushareClient` 会：

1. 从环境变量读取 Token；
2. 使用 Tushare SDK 初始化 `pro` 客户端；
3. 将 SDK 请求地址切换到 `https://teajoin.com`；
4. 将接口结果统一转换为 `pandas.DataFrame`；
5. 在错误信息中避免输出 Token。

## 4. 直接使用 Tushare SDK

在独立脚本中，也可以直接初始化：

```python
import os

import tushare as ts
from dotenv import load_dotenv

load_dotenv()

token = os.environ["TUSHARE_TOKEN"]
api_url = os.getenv("TUSHARE_API_URL", "https://teajoin.com").rstrip("/")

ts.set_token(token)
pro = ts.pro_api(token)

# 代理服务兼容 Tushare Pro 协议，但请求地址需要手动改写。
pro._DataApi_token = token
pro._DataApi__http_url = api_url

df = pro.daily(
    ts_code="000001.SZ",
    start_date="20260101",
    end_date="20260110",
)
print(df)
```

使用 `ts.pro_bar()` 等模块级函数时，必须显式传入已经改写过地址的 `pro`：

```python
df = ts.pro_bar(
    ts_code="002594.SZ",
    api=pro,
    start_date="20260101",
    end_date="20260110",
    adj="qfq",
)
```

## 5. 连通性验证

项目已经提供只读验证脚本：

```bash
cd /Users/chr/Documents/青树金融交易/qingshu-agent-demo
PYTHONPATH=. /Users/chr/.hermes/hermes-agent/venv/bin/python scripts/verify_tushare.py
```

成功时会输出类似：

```text
Tushare 连通性校验通过：5 行
字段：ts_code, trade_date, open, high, low, close, pre_close, change, pct_chg, vol, amount
最新交易日：20260109
```

验证脚本不会输出 Token，也不会写入交易指令。

## 6. 常用接口

| 接口 | 用途 | 常用参数 |
| --- | --- | --- |
| `daily` | 股票日线行情 | `ts_code`, `start_date`, `end_date` |
| `weekly` | 股票周线行情 | `ts_code`, `start_date`, `end_date` |
| `monthly` | 股票月线行情 | `ts_code`, `start_date`, `end_date` |
| `daily_basic` | 每日估值与交易指标 | `ts_code`, `trade_date` |
| `stock_basic` | 股票基础信息 | `exchange`, `list_status` |
| `trade_cal` | 交易日历 | `exchange`, `start_date`, `end_date` |
| `index_daily` | 指数日线行情 | `ts_code`, `start_date`, `end_date` |
| `income` | 利润表 | `ts_code`, `start_date`, `end_date` |
| `balancesheet` | 资产负债表 | `ts_code`, `start_date`, `end_date` |
| `cashflow` | 现金流量表 | `ts_code`, `start_date`, `end_date` |
| `moneyflow` | 个股资金流向 | `ts_code`, `trade_date` |
| `limit_list_d` | 每日涨跌停列表 | `trade_date`, `ts_code` |

具体字段和权限以 [Tushare 接口文档](https://tushare.pro/document/2) 及代理服务实际返回为准。

## 7. 数据格式约定

### 股票代码

使用 Tushare 格式：

```text
000001.SZ   # 深交所
600519.SH   # 上交所
830799.BJ   # 北交所
```

### 日期

日期统一使用 `YYYYMMDD`：

```text
20260110
```

### 日线字段

常见字段包括：

- `ts_code`：证券代码
- `trade_date`：交易日期
- `open`、`high`、`low`、`close`：开高低收
- `pre_close`：昨收价
- `change`：涨跌额
- `pct_chg`：涨跌幅
- `vol`：成交量，通常以手为单位
- `amount`：成交额，通常以千元为单位

不同接口的单位和字段定义可能不同，计算前应先核对接口文档。

## 8. 请求频率与批量下载

按照当前代理指南：

- 最高频率为每分钟 450 次；
- 批量请求建议每次至少间隔 0.2 秒；
- 不要无限并发下载全市场数据；
- 长任务应按日期或股票代码分批，并保存进度；
- 出现临时错误时使用有限次数重试和递增等待；
- 空 DataFrame 可能表示该接口在当前权限下无数据，不一定是程序异常。

推荐的批量调用结构：

```python
import time

import pandas as pd

frames = []
for ts_code in ["000001.SZ", "600519.SH"]:
    try:
        frames.append(
            client.daily(
                ts_code=ts_code,
                start_date="20260101",
                end_date="20260131",
            )
        )
    except Exception as exc:
        print(f"跳过 {ts_code}：{type(exc).__name__}")
    time.sleep(0.2)

result = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
```

## 9. 常见问题

### `未配置 TUSHARE_TOKEN`

检查项目根目录是否存在 `.env`，以及是否包含：

```dotenv
TUSHARE_TOKEN=YOUR_API_KEY
```

修改 `.env` 后，需要重新启动 Python 进程。

### `ModuleNotFoundError: No module named 'tushare'`

在当前实际运行环境安装依赖：

```bash
uv pip install \
  --python /Users/chr/.hermes/hermes-agent/venv/bin/python \
  'tushare>=1.4'
```

### 返回空数据

依次检查：

1. 股票代码是否为 Tushare 格式；
2. 日期范围是否为交易日；
3. 接口名称和参数是否正确；
4. 当前账号是否开通该接口；
5. 代理服务是否返回了权限或频率限制信息。

### 实时或分钟数据不可用

通用日线权限不等于实时行情或历史分钟权限。遇到此情况，不要把空结果解释成“市场没有数据”，应先确认接口权限和服务清单。

## 10. 安全边界

- 不要把真实 Token 写进 Python、Notebook、README、测试代码或 Dockerfile。
- 不要在日志、异常详情、截图或提交记录中输出 Token。
- 不要把 Token 放进前端 JavaScript 或浏览器请求参数。
- 本项目的 Tushare 接入目前是只读数据访问，不包含下单、资金操作或交易权限配置。
- Tushare 返回的数据应保留接口名称、请求时间和数据日期，便于后续审计。
