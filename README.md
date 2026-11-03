# 股票分析 Telegram 机器人（附 AI 基金经理圆桌）

支持 🇲🇾 大马、🇺🇸 美股、🇮🇩 印尼股票。发一个股票代码，机器人会回复：
数据报告（技术面 + 基本面 + 新闻情绪）、走势图、5 位 AI 基金经理的看法，以及投资委员会主席总结。

有两种用法：**Telegram 机器人**（`bot.py`）和**网页版**（`app.py`，见下面「🌐 网页版」）。

**0 预算方案：** 在你自己的电脑上运行 + 用 Groq 免费 AI。全程不用花钱、不用信用卡。

---

## 一步一步安装教程（约 20-30 分钟）

### 第 1 步：安装 Python

1. 去 https://www.python.org/downloads/ 下载最新版 Python（3.10 以上）。
2. **Windows 用户：** 安装时第一个画面**一定要勾选 "Add python.exe to PATH"**，再按 Install Now。
3. 安装好后打开"命令提示字元"（按 Windows 键，打 `cmd`，按 Enter），输入：
   ```
   python --version
   ```
   看到 `Python 3.xx.x` 就成功了。（Mac 用户打开"终端 Terminal"，用 `python3` 代替 `python`。）

### 第 2 步：准备项目文件夹

1. 在桌面建一个文件夹，例如 `stock-bot`。
2. 把这些文件全部放进去：
   `bot.py`、`app.py`、`scanner.py`、`screener.py`、`klci.py`、`fundamentals.py`、`company.py`、`analysis.py`、`managers.py`、`portfolio.py`、`requirements.txt`、`README.md`、`.env.example`、`.gitignore`
   （网页版另外需要 `.streamlit/secrets.toml.example`；每日自动报告需要 `.github/workflows/market-reports.yml`，见下面说明）
3. 在这个文件夹里打开命令提示字元：
   - **Windows：** 打开文件夹，点一下上面的地址栏，把路径删掉，打 `cmd`，按 Enter。
   - **Mac：** 在 Finder 对文件夹按右键 → "在文件夹位置新建终端窗口"。
4. 安装需要的工具包：
   ```
   pip install -r requirements.txt
   ```
   等它跑完（1-3 分钟）。出现红字错误的话，先试 `python -m pip install -r requirements.txt`。

### 第 3 步：在 Telegram 创建你的机器人（免费）

1. 打开 Telegram，搜索 **@BotFather**（有蓝色勾勾的那个）。
2. 发送 `/newbot`。
3. 它问名字 → 随便取，例如 `我的股票助手`。
4. 它问用户名 → 一定要以 `bot` 结尾，例如 `junren_stock_bot`（被人用过就换一个）。
5. 它会回你一串 token，类似：`7123456789:AAHxxxxxxxxxxxxxxxxxxxx`，**复制保存好**。

### 第 4 步：申请 Groq 免费 AI key

1. 去 https://console.groq.com ，用 Google 帐号登入即可，不用信用卡。
2. 左边菜单点 **API Keys** → **Create API Key**，随便取个名字。
3. 复制那串 `gsk_...` 开头的 key。⚠️ 它只显示一次，要马上保存。

### 第 5 步：建立 .env 文件（放你的 key）

1. 复制 `.env.example`，把复制出来的文件改名为 `.env`（前面有一点，后面没有 .txt）。
   - **Windows 小提醒：** 如果看不到文件后缀名，在文件夹上方点"检视" → 勾选"副档名"，确认文件名是 `.env` 而不是 `.env.txt`。
2. 用记事本打开 `.env`，把两行改成你自己的：
   ```
   TELEGRAM_BOT_TOKEN=7123456789:AAHxxxxxxxx
   AI_PROVIDER=groq
   GROQ_API_KEY=gsk_xxxxxxxx
   ```
   等号两边不要有空格，也不用加引号。存档。

### 第 6 步：启动机器人 🚀

在命令提示字元输入：
```
python bot.py
```
看到 `机器人运行中 - 按 Ctrl+C 停止` 就成功了。**这个窗口不要关**，关了机器人就下线。

### 第 7 步：测试

在 Telegram 搜索你在第 3 步取的用户名，打开对话：
1. 发送 `/start` → 应该看到使用说明
2. 发送 `/quick MAYBANK` → 应该看到数据报告和图表（不用 AI，测试数据部分）
3. 发送 `MAYBANK` → 完整报告 + 5 位基金经理发言 + 主席总结

---

## 常见问题

| 看到的错误 | 原因和解决方法 |
|---|---|
| `'python' is not recognized` | 第 1 步没勾选 "Add to PATH"。重新安装 Python 并勾选。 |
| `No module named ...` | 第 2 步的 `pip install` 没成功，再跑一次。 |
| `请在 .env 里设置 ...` | `.env` 文件名不对（可能变成 `.env.txt`），或 key 没填好。 |
| `InvalidToken` / `Unauthorized` | Telegram token 复制错了，回 @BotFather 发 `/mybots` 重新拿。 |
| 经理显示"暂时无法发言：401" | Groq key 错了或被删除，重新建一个。 |
| 经理显示"暂时无法发言：429" | 免费额度用太快了，等一分钟再试。 |
| 经理显示"暂时无法发言：model ... not found" | 默认模型被下架了。去 https://console.groq.com/docs/models 找一个新的模型名，在 `.env` 加一行 `AI_MODEL=新模型名`。 |
| `找不到 ... 的股价数据` | 股票代码错了。大马用 `1155.KL`，印尼用 `BBCA.JK`，美股用 `AAPL`。 |

遇到别的错误，把命令提示字元里的红字整段复制下来问 AI 或 Google。

---

## 使用方法

| 你发送 | 你会得到 |
|---|---|
| `MAYBANK` / `1155` / `1155.KL` | 完整报告 + 图表 + 基金经理圆桌 |
| `AAPL`、`BBCA` | 美股 / 印尼股完整分析 |
| `/company MAYBANK` | 认识公司：业务、成绩、管理层 + 弱到强评级 |
| `/radar` / `/radar us` | 今日错杀股、成长股、双杀股 |
| `/klci` | KLCI 50 最有机会入选的公司 |
| `/quick NVDA` | 只看数据报告（不开圆桌，更快） |
| `/panel TENAGA` | 只开基金经理圆桌 |
| `/tech`、`/fund`、`/news`、`/chart` + 代码 | 单独看某一部分 |
| `/buy 1155.KL 1000 9.80` | 记录买入（重复买入自动算平均成本） |
| `/sell 1155.KL 500` | 卖出 500 股（不写数量就全部清空） |
| `/portfolio` | 持股、实时市值和盈亏 |

常用名称（MAYBANK、TNB、CIMB、BBCA、TLKM…）在 `analysis.py` 顶部的 `ALIASES`，可以自己加。

## 圆桌嘉宾

🧓 老陈（价值投资派）· 🚀 Kelly（成长股猎手）· 📊 阿杰（技术派交易员）· 💰 Auntie Lim（收息派老手）· 🐻 冷面周（风控官·唱反调）

想加新经理：在 `managers.py` 的 `MANAGERS` 列表里照样加一段 dict。

---

## 换 AI 供应商（只改 .env，不用改代码）

| AI_PROVIDER | 费用 | 要准备什么 |
|---|---|---|
| `groq`（默认） | 免费 | `GROQ_API_KEY`，从 https://console.groq.com |
| `gemini` | 免费额度 | `GEMINI_API_KEY`，从 https://aistudio.google.com 的 "Get API key"。默认模型名如果用不了，去 AI Studio 看最新的 Flash 模型名，填到 `AI_MODEL` |
| `ollama` | 完全免费，本地跑 | 安装 https://ollama.com ，在命令提示字元跑 `ollama pull qwen3:8b`。电脑建议 16GB 内存 |
| `claude` | 付费，质量最好 | `ANTHROPIC_API_KEY`，从 https://console.anthropic.com 充值；还要跑 `pip install anthropic` |

例如以后想升级到 Claude，`.env` 改成：
```
AI_PROVIDER=claude
ANTHROPIC_API_KEY=sk-ant-xxxx
```
重开 `python bot.py` 就好。

---

## （可选）上传到 GitHub

最简单是用 **GitHub Desktop**（https://desktop.github.com）：
1. 登入 → File → Add local repository → 选你的 `stock-bot` 文件夹 → 按提示 "create a repository"。
2. **检查左边的改动清单：不可以出现 `.env` 和 `portfolio.db`。**（有 `.gitignore` 就不会出现。）
3. 写一句说明（例如"第一版"）→ Commit → Publish repository。建议勾选 **Keep this code private**。

⚠️ 万一不小心把 `.env` 上传了：马上去 Groq 删除那个 key、去 @BotFather 用 `/revoke` 换新 token。

---

## 🌐 网页版（免费放上网，手机随时打开）

网页版 `app.py` 和 Telegram 机器人用同一套分析和基金经理代码。功能包括：
个股分析（K 线图、技术面、基本面、新闻）、5 位基金经理卡片 + 主席总结、投资组合计算器，并且有**密码保护**。

### A. 先在自己电脑试跑

1. 在项目文件夹的命令提示字元运行：
   ```
   pip install -r requirements.txt
   ```
2. 在项目文件夹里建一个 `.streamlit` 文件夹，把 `secrets.toml.example` 放进去，复制一份改名为 `secrets.toml`，填入：
   ```
   APP_PASSWORD = "你自己定的密码"
   AI_PROVIDER = "groq"
   GROQ_API_KEY = "gsk_你的key"
   ```
   （或者直接沿用之前的 `.env` 也可以，再加一行 `APP_PASSWORD=你的密码`）
3. 运行：
   ```
   streamlit run app.py
   ```
   浏览器会自动打开 `http://localhost:8501`。输入密码 → 输入 `MAYBANK` → 按"分析"。

### B. 免费部署到网上（Streamlit Community Cloud）

**1. 把代码放上 GitHub**
- 下载安装 GitHub Desktop（https://desktop.github.com），用 GitHub 帐号登入（没有就先去 github.com 免费注册）。
- File → Add local repository → 选 `stock-bot` 文件夹 → 按提示 create a repository。
- **检查左边改动清单：不能出现 `.env`、`secrets.toml`、`portfolio.db`。**（`.gitignore` 会自动挡掉。）
- 写一句说明 → Commit to main → Publish repository。
  - 免费版只能有 1 个私人 app，所以 repo 可以设为 Public。代码公开没关系，key 和密码不在代码里。

**2. 部署**
- 去 https://share.streamlit.io ，用 GitHub 帐号登入，授权它读取你的 repo。
- 按 **Create app** → 选 "Deploy a public app from GitHub"。
- Repository 选你的 `stock-bot`，Branch 选 `main`，Main file path 填 `app.py`。
- App URL 可以自己取，例如 `junren-stock`（网址会是 `junren-stock.streamlit.app`）。
- 点 **Advanced settings** → 在 **Secrets** 框里贴上：
  ```
  APP_PASSWORD = "你自己定的密码"
  AI_PROVIDER = "groq"
  GROQ_API_KEY = "gsk_你的key"
  ```
- 按 **Deploy**，等 2-5 分钟安装完成就上线了。

**3. 用手机打开**
- 用手机浏览器打开你的网址，输入密码就能用。
- 想像 app 一样用：Chrome 右上角 ⋮ →"添加到主屏幕"（iPhone 用 Safari 的分享按钮 →"添加到主屏幕"）。

### 网页版要知道的事

- **会睡觉：** 12 小时没人用会自动睡眠，下次打开要等 30 秒到 1 分钟让它醒来。
- **投资组合不会永久保存：** 网站重开后资料会消失，用完记得按"下载 CSV"，下次上传就能恢复。
- **省额度设计：** 同一只股票的数据 15 分钟内不会重复抓；基金经理圆桌每只股票每天只生成一次，第二个人再查同一只股票不会再用额度。
- **改代码后：** 在 GitHub Desktop 再 Commit + Push，网站几分钟内会自动更新。
- **改密码或 key：** 在 share.streamlit.io 你的 app → Settings → Secrets 修改，不用改代码。

---

## 🔍 选股雷达：错杀股 / 成长股 / 双杀股

每个交易日收市后自动扫描（大马约 120 只大型股、印尼 36 只、美股 40 只），按固定规则分类：

| 类型 | 意思 | 规则（`screener.py` 的 `RULES` 可调） |
|---|---|---|
| 🎯 错杀股 | 股价大跌，但公司没变差，可能被市场错杀 | 距 52 周高点跌 ≥ 20% 或 3 个月跌 ≥ 15%；盈利增长 ≥ -5%；ROE ≥ 8%；本益比比自己历史平均便宜 ≥ 10% |
| 🚀 成长股 | 营收和盈利高速增长 | 营收增长 ≥ 10%、盈利增长 ≥ 15%、ROE ≥ 12%；股价在 200 日均线上（之下标「回调中」） |
| ⚠️ 双杀股 | 盈利下滑 + 估值被调低（戴维斯双杀），要小心 | 盈利增长 ≤ -10%、6 个月股价跌 ≥ 15%，且本益比低于历史或股价跌幅大于盈利跌幅 |

每只股票都列出符合的理由，有 AI 基金经理点评，卡片上可以直接按「🏢 认识公司」「📊 深入分析」。
Telegram：`/radar`（大马）、`/radar us`、`/radar idx`。

**要知道：** 盈利增长用 Yahoo 的最近一季按年增长（没有就用年度 EPS）；「历史本益比」用过去几个财年年底股价 ÷ 当年 EPS 计算。这是筛选研究起点，不是买卖信号。

---

## 🏆 KLCI 50 观察：谁最有机会进入成分股

**背景：** 2026 年 8 月，Bursa 和 FTSE Russell 宣布 FBM KLCI 由 30 只扩大到 **50 只**。

| 日期 | 事件 |
|---|---|
| 2026-11-23（一） | 数据截止：用这天收市的全市值排名 |
| 2026-12-03（四） | 公布新成分股 |
| 2026-12-21（一） | 生效：新增 20 只，先以 50% 权重加入 |
| 2027-06-21 | 新成分股权重升到 100% |

**怎么估算：**
1. 抓约 120 只马股大型股的全市值、自由流通量、过去 12 个月成交量
2. 资格筛选（按 FTSE 规则估算）：自由流通量 > 15%；非成分股 12 个月中至少 10 个月的每日成交量中位数 ≥ 可投资股数的 0.05%
3. 这次是扩容：现有 30 只保留，**20 个新名额**给全市值最高的合格非成分股
4. 第 20 名的市值 = 门槛；按每家公司比门槛高或低多少、离截止日还有几天，估算入选几率
5. 每天保存一份，网页上可以看到名额边缘公司的**几率变化走势**

网页会显示倒数、名额分界线、谁「还差几 %」、官方模拟和分析师名单对照（📋）。Telegram：`/klci`。

**限制：**
- 这是**模拟估算，不是官方结果**。Yahoo 的自由流通量和成交量数据不一定准确。
- 名单只涵盖 `klci.py` 里的约 120 只公司（`CANDIDATES` 可以自己加）。部分股票代码是凭资料整理的，抓不到数据的会自动跳过。
- 50 只成分股的新缓冲规则（排第几名才被剔除）官方还没公布细节。2027 年 6 月以后的检讨按「前 50 名」估算。
- 每次官方检讨后，要更新 `klci.py` 里的 `CONSTITUENTS`（现有成分股名单）。

---

## 🏢 认识公司：业务、成绩、管理层 + 弱到强评级

在网站任何地方点股票代码就能打开：
- 「📅 每日焦点」卡片上的 **🏢 认识公司** 按钮，或者**点表格里任何一行**
- 「📊 个股分析」公司名下面的 **🏢 认识这家公司**
- 侧边栏「🏢 认识公司」直接输入代码
- Telegram：`/company MAYBANK`

报告内容：

| 部分 | 说明 |
|---|---|
| ⭐ 综合评级 | 弱 / 偏弱 / 中等 / 偏强 / 强，另外分开评「业务实力」「管理层」「财务体检」 |
| 💡 一句话认识 | 这家公司是做什么的 |
| 🏭 主要业务 / 💰 营业模式 | 卖什么、客户是谁、靠什么赚钱、有没有护城河 |
| 📈 近几年成绩 | 近 4-5 年营收、净利润、净利率图表 + 财务表格 + AI 解读 |
| 🩺 财务体检 | 用固定规则算的 6 项分数：成长性、获利能力、财务稳健、盈利稳定、股东回报、公司治理（每项都写明理由） |
| 👔 管理层 | 高管名单、内部人和机构持股、治理风险分 + AI 评价 |
| ✅ 优势 / ⚠️ 风险 | 各 2-3 点 |

**两种评分的分别：**「财务体检」是纯数字计算，客观但看不到业务质量；「业务实力、管理层、综合评级」是 AI 读了资料后的判断，更全面但可能有偏差。两个一起看最好。

**要注意：**
- 财报来自 Yahoo Finance，一般有最近 4-5 年的年度数据；部分大马/印尼公司数据可能不齐全。
- AI 对业务和管理层的描述来自它的训练知识，**可能不是最新**（例如最近换了 CEO 它未必知道）。重要决定请查公司年报（Bursa 公司可以在 bursamalaysia.com 找到）。
- 同一家公司的报告会保存 7 天，不会重复用 AI 额度。

---

## 📅 每日焦点：开市 / 午间 / 收市自动报告

每个交易日，GitHub 会**免费**帮你定时扫描三个市场的蓝筹股，生成报告存进网站，也可以推送到你的 Telegram。
收市报告之后，同一次运行还会自动跑「🔍 选股雷达」；马股收市后再加跑「🏆 KLCI 50 观察」。

### 报告时间（当地时间）

| 市场 | 开市报告 | 午间报告 | 收市报告 |
|---|---|---|---|
| 🇲🇾 Bursa | 9:45am | 12:35pm（午休） | 5:15pm |
| 🇮🇩 IDX（雅加达时间，比大马慢 1 小时） | 9:45am | 12:05pm（星期五 11:35am） | 4:20pm |
| 🇺🇸 美股（纽约时间，大马时间约晚上 10-11 点开市） | 10:00am | 12:30pm（美股没午休，叫盘中报告） | 4:20pm |

GitHub 的定时任务有时会迟 5-30 分钟，属于正常。

### 每份报告有什么

- **市场概况**：上涨/下跌家数、平均涨跌、市场气氛
- **🔥 最值得关注的 5 只股票**：按"关注度分数"排名 = 涨跌幅 + 成交量异常放大 + 波幅 + 特殊信号（创 52 周新高/新低、突破或跌破 50 日均线），每只都列出原因标签
- **四个排行榜**：涨幅最大、跌幅最大、成交量异常放大、成交额最高
- **🧠 AI 市场点评**（有设置 AI key 才有）
- 每张卡片有"深入分析 →"按钮，一按就跳到个股分析 + 基金经理圆桌

### 怎样避开投机炒股公司

1. 只扫描**大型蓝筹股名单**（大马约 48 只、印尼约 36 只、美股 40 只），写在 `scanner.py` 顶部的 `BURSA`、`IDX`、`US`，可以自己加减。
2. **剔除低价股**：大马低于 RM1、印尼低于 Rp500、美股低于 $10。
3. **剔除成交冷清的股票**：过去 20 天平均每日成交额低于门槛（大马 RM500 万、印尼 Rp200 亿、美股 $1 亿）。

门槛在 `scanner.py` 的 `MARKETS` 里调整（`min_price`、`min_turnover`）。

### 设置步骤（只需做一次）

**1. 确认 `.github/workflows/market-reports.yml` 已经上传到 GitHub**
这个文件夹名字前面有一点，Windows 可能看不到，记得打开"显示隐藏的项目"。用 GitHub Desktop 上传时它会自动包含。

**2. 拿到你的 Telegram Chat ID**（想收推送才需要）
在电脑运行 `python bot.py`，在 Telegram 对机器人发 `/myid`，它会回你一串数字。

**3. 在 GitHub 设置 Secrets**
打开你的 repo 网页 → **Settings** → 左边 **Secrets and variables** → **Actions** → **New repository secret**，逐个添加：

| Name | Value |
|---|---|
| `AI_PROVIDER` | `groq` |
| `GROQ_API_KEY` | 你的 Groq key |
| `TELEGRAM_BOT_TOKEN` | 你的机器人 token（想收推送才加） |
| `TELEGRAM_CHAT_ID` | 第 2 步的数字（想收推送才加） |

**4. 只想看某些市场？**（可选）
同一页切换到 **Variables** 分页 → New repository variable：Name 填 `SCAN_MARKETS`，Value 填例如 `bursa` 或 `bursa,us`。

**5. 手动测试一次**
repo 网页 → **Actions** 分页 → 左边选 **市场报告** → 右边 **Run workflow** → market 填 `bursa`、session 填 `close` → 按绿色按钮。
等 1-2 分钟变成绿色勾勾，repo 里就会多一个 `reports/` 文件夹，网站「📅 每日焦点」也会出现报告（Streamlit 会在几分钟内自动更新）。

### 要知道的事

- **免费额度**：repo 是 Public 的话，GitHub Actions 完全免费。如果设成 Private，每月只有有限的免费分钟数，这个排程可能会超过，建议保持 Public。
- **假期**：遇到公共假期，扫描器会发现今天没有新数据，自动跳过，不会生成报告。
- **数据延迟**：Yahoo 的数据约延迟 15 分钟，所以报告时间都设在开市/休市/收市之后一点。
- **盘中成交量**：开市和午间报告的"成交量倍数"已按交易时间比例调整，例如午间只过了一半时间，就跟平常半天的量比较。
- 网站上也有"⚡ 现在立即扫描一次"，随时手动扫描（不会保存）。
- 在电脑上也可以手动生成：`python scanner.py --market bursa --session close`

---

## 限制

- 股价来自 Yahoo Finance（免费、非官方），可能延迟约 15 分钟；大马/印尼中小型股的数据较少。
- AI 经理只依据机器人给的数据和训练时学到的知识，**不会自己上网查最新新闻**。
- 免费 AI 有次数上限，自己用一般够；分析深度比付费的 Claude 弱一些。
- 只有电脑开着、`python bot.py` 在跑，机器人才在线。

*仅供学习参考，AI 观点不构成投资建议。*
