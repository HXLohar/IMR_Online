# IMR Online — Step 1 開發說明書 (for Claude Code)

> 這份文件是給 **Claude Code** 的工作說明。請先完整讀一遍,再按「里程碑 / 任務拆解」逐步實作。
> 目標:做一個基於 IMR(Innovative Mahjong Ruleset,創新麻將)自創規則的 **HTML5 線上麻將**,網頁打開即玩、手機/電腦皆可。本階段(Step 1)只做**單人對 3 個機器人**的本地可玩 demo,用來驗證吃碰槓、和牌、算分。

---

## 0. 最重要的前提(請務必遵守)

1. **服務端是唯一權威(authoritative server)。** 牌牆、發牌、所有合法性判定都在服務端完成。客戶端只做兩件事:渲染服務端推來的狀態、把玩家「意圖」上報。**永遠不信任客戶端傳來的牌或結果。**
2. **複用現有的 Python 計分引擎,不要重寫。** 現有 `IMR_Calculator` 已實作拆牌、判和、番種偵測、IMR 計分、聽牌/待張(outs)。把它包成 `server/scoring/` 模組直接用。
3. **Step 1 客戶端刻意做薄。** 功能性棋盤即可,不做動畫與美術。先把「引擎 + 聯機 + 狀態機」跑通。
4. **核心難點是服務端的「回合 / 鳴牌狀態機」**,尤其是 IMR 特有機制(让过、重摸、报听、一炮多响)。把這部分用明確的有限狀態機(FSM)實作,並寫測試。
5. **先寫測試再擴張功能。** 規則複雜,回歸測試是保命符。

---

## 1. 技術選型

| 層 | 選型 | 理由 |
|----|------|------|
| 後端語言 | **Python 3.12** | 直接複用現有計分引擎 |
| 後端框架 | **FastAPI** + `uvicorn` | 原生 WebSocket、async、文檔好、部署簡單 |
| 訊息 schema | **Pydantic v2** | 強型別、自動校驗、序列化 |
| 客戶端 | **TypeScript + Vite** | 現代前端工具鏈、HMR 開發爽 |
| 客戶端渲染(Step 1) | 純 **DOM / Canvas** | 功能驗證為先,先不上遊戲引擎 |
| 客戶端渲染(後續) | Phaser 3(預留升級路徑) | 雀魂式觀感時再導入 |
| 傳輸 | **JSON over WebSocket** | 雙向、低延遲、足夠 |
| 測試 | `pytest`(後端) | 規則回歸測試 |

> **升級路徑備註**:Step 1 的客戶端渲染層要與通訊/狀態層解耦(見目錄結構的 `net/` vs `render/`),這樣之後換成 Phaser 時只需替換 `render/`。

---

## 2. 系統架構

```
┌─────────────────────────────┐         WebSocket (JSON)        ┌──────────────────────────────────┐
│         Browser Client       │ ───── 玩家意圖 (intent) ──────▶ │           FastAPI Server          │
│  (TypeScript + Vite)         │                                 │                                   │
│  - net/   WS 連線、收發訊息   │ ◀──── 遊戲狀態 (state) ──────── │  - ws/    WebSocket 端點          │
│  - render/ 棋盤渲染(可換)   │                                 │  - game/  房間 + 回合狀態機 (FSM) │
│  - state/  本地視圖狀態        │                                 │  - bots/  3 個機器人(同進程)    │
└─────────────────────────────┘                                 │  - scoring/ ← 複用 IMR_Calculator │
                                                                  │  - protocol/ Pydantic 訊息定義    │
                                                                  └──────────────────────────────────┘
```

- **一個房間 = 一個 async 任務 + 一份權威遊戲狀態。** Step 1 為單機房,記憶體內保存即可,不需 Redis/DB。
- 機器人不是獨立進程,而是服務端內部的決策函式,輸入「對該機器人可見的狀態 + 合法選項」,輸出一個動作。它們**共用同一套規則引擎**。
- 每位玩家(含人類)只能看到自己該看到的資訊:服務端為每個座位生成「個人視圖」後再下發(別人的手牌只送背面/數量)。

---

## 3. 目錄結構(建立新 repo `imr-online`)

```
imr-online/
├── README.md
├── server/
│   ├── pyproject.toml            # 或 requirements.txt
│   ├── app.py                    # FastAPI 入口 + WS 路由
│   ├── protocol/
│   │   ├── __init__.py
│   │   └── messages.py           # Pydantic: 所有 C→S / S→C 訊息
│   ├── game/
│   │   ├── __init__.py
│   │   ├── tiles.py              # 牌的表示(對齊 scoring 引擎的 Tile)
│   │   ├── wall.py               # 牌牆、發牌、寶牌(本階段無寶牌可略)
│   │   ├── player_state.py       # 手牌、副露、河、pass_count、吃碰次數、riichi 狀態
│   │   ├── room.py               # 房間:座位、開局、推進
│   │   ├── fsm.py                # ★ 核心:回合 / 鳴牌狀態機
│   │   ├── legal.py              # 合法動作偵測(對某張棄牌可否吃/碰/槓/和)
│   │   ├── redraw.py             # 重摸條件判定
│   │   └── settle.py             # 結算:呼叫 scoring + 起和門檻 + 让过賠付
│   ├── scoring/                  # ← 從 IMR_Calculator 搬入並包裝
│   │   ├── __init__.py
│   │   ├── parsing.py            # 來自 main.py(Tile/解析/拆解/find_all_explanations)
│   │   ├── fan.py                # 來自 fan.py(番種偵測 + 計分)
│   │   ├── api.py                # 乾淨封裝:score_hand / is_winning / waits / shanten
│   │   └── data/
│   │       ├── fan.csv           # ★ 轉存為 UTF-8
│   │       ├── lang.csv
│   │       └── additional_options.csv
│   ├── bots/
│   │   ├── __init__.py
│   │   ├── base.py               # Bot 介面:see_state(view) / decide_turn() / decide_claim()
│   │   ├── discard_only_bot.py   # 機器人①:純摸打,不鳴不和
│   │   └── auto_call_bot.py      # 機器人②:總是吃碰槓(槓優先),不和,隨機打牌
│   └── tests/
│       ├── test_scoring_api.py
│       ├── test_legal.py
│       ├── test_redraw.py
│       └── test_fsm.py
└── client/
    ├── package.json
    ├── vite.config.ts
    ├── index.html
    └── src/
        ├── main.ts
        ├── net/ws.ts             # WebSocket 連線、收發、重連
        ├── state/store.ts        # 本地視圖狀態(由服務端推送驅動)
        ├── render/board.ts       # 棋盤渲染(Step 1 用 DOM/Canvas,可整層替換)
        └── render/controls.ts    # 出牌 / 吃碰槓 / 和 / 让过 / 重摸 / 报听 按鈕
```

---

## 4. 複用現有計分引擎(`server/scoring/`)

### 4.1 搬遷步驟
1. 把 `IMR_Calculator/main.py` 的核心(Tile/TileType/Call/Group/解析/`find_all_explanations`/拆解相關函式)整理進 `parsing.py`;**不要**搬 `interactive_mode` / `run_tests` 之類 CLI 邏輯。
2. `fan.py` 直接搬入(`load_fans_from_csv`/`detect_fans`/`apply_overrides`/`calculate_score`/`score_hand`)。
3. 把 `data/*.csv` **轉存為 UTF-8** 後放進 `scoring/data/`(原檔是 GBK)。`load_fans_from_csv` 已有多編碼 fallback,但統一 UTF-8 可免後患。
4. **不要**搬 `ui.py`(Tkinter GUI 服務端用不到)。

### 4.2 對外只暴露一個乾淨 API(`scoring/api.py`)
讓上層只依賴這幾個函式,內部怎麼拆解對上層透明:

```python
def is_winning(hand_tiles, calls, winning_tile, flags) -> bool: ...
    # 是否構成合法和牌(內部走 find_all_explanations,有任一合法拆解即和)

def score_hand(hand_tiles, calls, winning_tile, flags) -> ScoringResult: ...
    # 回傳:命中的番種列表(id/名稱/分值)、原始總分、IMR 滿貯/減半後的最終分
    # flags 至少含:self_drawn(自摸)、last_tile(海底/最後一張)、riichi(报听)、
    #               heavenly/earthly(天和/地和) 等偶然番所需資訊

def waits(hand_tiles, calls) -> list[Tile]: ...
    # 聽牌待張(複用現有 outs 計算),供 tenpai 判定與機器人使用

def shanten(hand_tiles, calls) -> int: ...
    # 向聽數(0 = 聽牌)。若現有程式只有 outs,可由「是否存在使其聽牌的單張」推導
```

### 4.3 引擎**已提供** vs 需**新建**
- ✅ 已提供:拆牌、判和、番種偵測、IMR 計分(滿貯/減半)、聽牌待張。
- ❌ 需新建(屬於「對局邏輯」,不在計分器內):
  - 牌牆與發牌(`wall.py`)
  - 對「某張被打出的牌」判定每家可否吃/碰/槓/和(`legal.py`)
  - 重摸條件判定(`redraw.py`)
  - **起和門檻**(依让过次數與門前清狀態,見 §6.4)與**让过賠付**結算(`settle.py`)
  - 回合 / 鳴牌狀態機(`fsm.py`)

---

## 5. 規則摘要(IMR — 實作時以此為準,細節番種以 `fan.csv` 為準)

> 完整規則見使用者的 `MAHJONG.docx`。以下為與**對局流程**直接相關的機制摘要。

- **让过(yield)**:可將一張牌**面向下**打出,以避免放炮或被吃碰槓,但帶來限制:
  - 1 次让过:吃碰上限 2 次(让过前後皆須維持)。
  - 2 次让过:吃碰上限 1 次。
  - 注意:**槓不計入吃碰次數**。
  - **對局結束時**(有人和牌或荒牌),凡「做過 ≥1 次让过且未聽牌」者,須向聽牌者賠分(由聽牌者平分);沒让过也沒聽牌者不賠不得。
    - 1 让过,0/1/2 吃碰:賠 450 / 750 / 1200。
    - 2 让过,0/1 吃碰:賠 3000 / 4500。
- **报听(declare ready)**:僅**門前清**可报听;和牌時 +100,並**確保可點和**。报听後若不換聽,仍可開大明槓破門前清(通常不損分,因為[門前清]與[一槓]皆 100)。
- **重摸(re-draw)**:摸到的牌若滿足下列任一條件,可於摸到時立即打出,若該牌未被吃碰槓且未點炮,則可重新摸一張;滿足條件可連續重摸。
  - 該**字牌**已亮明 ≥ 2 張;或
  - 自己打出過該**字牌** ≥ 1 次、或該**非字牌** ≥ 2 次;或
  - 該牌與**自家牌河最後一張**相同(不考慮巡目;被碰走的不算在河上)。
- **得分**:點和 → 點炮者付 3× 得分;自摸 → 三家各付 1× 得分。**可一炮多響**。
- **起和門檻**(最低和牌分):一般 150 起和;0/1/2 次让过 → 150 / 300 / 500 起和。**門前清**:自摸無條件可和;點和須滿足「得分 ≥ 500 / 已报听(或天聽配牌)/ 让过 ≥1」其一。偶然類番種(槓上開花、海底撈月、搶槓和、天和、地和、天聽)與碰碰和**不計入**門檻判定(碰碰和的上位番種可計入)。

---

## 6. ★ 核心:回合 / 鳴牌狀態機(`fsm.py`)

把對局建成明確的 FSM。狀態與轉移如下(每次轉移都由服務端推送對應 S→C 訊息)。

### 6.1 狀態
| 狀態 | 說明 |
|------|------|
| `WAITING` | 等玩家就緒(Step 1:1 人 + 3 bot 自動就緒) |
| `DEALING` | 洗牌、發牌、定莊 |
| `PLAYER_TURN` | 當前玩家摸牌後決策:打牌 / 自摸和 / 暗槓·加槓 / 重摸 / 报听 |
| `AWAIT_CLAIMS` | 有人打牌後的**鳴牌窗口**:收集各家 吃/碰/槓/和/略過,按優先級裁決 |
| `KONG_DRAW` | 槓之後從牌尾補摸(可槓上開花)→ 回到該玩家的決策 |
| `HAND_END` | 有人和牌 → 結算(§6.5) |
| `EXHAUSTIVE_DRAW` | 荒牌 → 聽牌判定 + 让过賠付(§6.6) |
| `MATCH_END` | 整局結束 |

### 6.2 PLAYER_TURN(當前玩家)
摸牌後,服務端計算該玩家的**合法選項**並下發 `your_turn`。玩家可選:
- `discard`(可帶 `face_down=true` 表示**让过**;须符合 §6.3 让过限制)
- `tsumo`(自摸和;须 `is_winning` 為真且通過起和門檻)
- `concealed_kong` / `added_kong`(暗槓 / 加槓)→ 進 `AWAIT_CLAIMS`(搶槓和)後 `KONG_DRAW`
- `redraw`(重摸;须符合 §5 重摸條件)→ 立即打出該摸牌、重新摸 → 仍在 `PLAYER_TURN`
- `declare_ready`(报听;僅門前清)

### 6.3 让过的計數與限制
- 每位玩家維護:`pass_count`(让过次數)、`chow_pong_count`(吃+碰次數,**槓不計**)。
- 打 `face_down` 時 `pass_count += 1`,並即時套用吃碰上限(1 让过→上限 2;2 让过→上限 1)。若後續吃/碰會超限則該動作**非法**。

### 6.4 AWAIT_CLAIMS(鳴牌窗口)——最容易出錯的地方
1. 一張牌被打出後(明牌的正常棄牌;面向下的让过牌**不可被吃碰槓和**),服務端對**其餘三家**算出各自合法的 claim 選項(吃只限下家;碰/槓/和不限座次),下發 `claim_window` 並開計時器(例如 5 秒)。
2. 收集各家回覆(`chow`/`pong`/`kong`/`win`/`skip`);未在時限內回覆者視為 `skip`(機器人即時回覆)。
3. **裁決優先級**:`和` > `碰`/`槓` > `吃`;同級依座次(逆時針距離出牌者最近者優先)。
4. **一炮多響**:若多家宣告 `win`,**全部成立**,各自結算(§6.5 對每位贏家分別算分,點炮者對每位贏家分別賠付)。
5. 若無人 claim → 出牌者下家進入 `PLAYER_TURN`(摸牌)。
6. 被吃/碰/槓者 → 由鳴牌者形成副露後進入其決策(碰/吃後須打牌;槓後進 `KONG_DRAW`),並更新其 `chow_pong_count`。

> 實作建議:把「收集意圖 → 依優先級解析」寫成一個純函式 `resolve_claims(discard, claims) -> Resolution`,獨立測試,別和 async/網路混在一起。

### 6.5 和牌結算(`settle.py` + `scoring`)
- 呼叫 `scoring.score_hand(...)` 取得番種與最終分。
- **套用起和門檻**(§5):未達門檻則該「和」不成立(視為詐和或不可和,依你的規則處理;Step 1 先當作不可宣告該和並回 `error`)。門檻判定要排除偶然番與碰碰和(其上位番除外)。
- 计算賠付:點和 = 點炮者付 3×;自摸 = 三家各付 1×;报听贏家額外 +100。
- 一炮多響:對每位贏家獨立重複以上。
- 下發 `hand_result`。

### 6.6 荒牌結算
- 對每家用 `scoring.waits(...)` 判定是否聽牌。
- 套用 §5 让过賠付表:做過让过且未聽牌者向聽牌者賠分,聽牌者平分。
- 下發 `draw_result`。

---

## 7. WebSocket 通訊協議(`protocol/messages.py`)

JSON,每則訊息含 `type` 欄位。以下為 Step 1 必要訊息(可再擴充)。用 Pydantic 定義並校驗。

### 7.1 Client → Server
```jsonc
// 遊客登入 + 進房(Step 1 自動建一個含 3 bot 的房)
{ "type": "join", "name": "Guest123" }

// 就緒
{ "type": "ready" }

// 打牌(face_down=true 即「让过」)
{ "type": "discard", "tile": "5b", "face_down": false }

// 對鳴牌窗口的回覆
{ "type": "claim", "claim": "pong" }            // chow | pong | kong | win | skip
{ "type": "claim", "claim": "chow", "tiles": ["4b","6b"] } // 吃需指定用哪兩張

// 自己回合的特殊動作
{ "type": "self_action", "action": "tsumo" }    // tsumo | concealed_kong | added_kong | redraw | declare_ready
{ "type": "self_action", "action": "concealed_kong", "tile": "9d" }
```

### 7.2 Server → Client
```jsonc
{ "type": "joined", "seat": 0, "players": [{"seat":0,"name":"Guest123","is_bot":false}, ...] }

// 開局:只把「你自己」的手牌明細送給你
{ "type": "game_start", "dealer": 0, "your_seat": 0,
  "your_hand": ["1b","2b","3b","5c","5c","E", ...], "wall_count": 70 }

// 你的回合與合法選項
{ "type": "your_turn", "drawn": "7d",
  "options": ["discard","tsumo","concealed_kong","redraw","declare_ready"],
  "redraw_eligible": true }

// 某家摸牌(別家只見座位與牌數,不見牌面)
{ "type": "tile_drawn", "seat": 1, "wall_count": 69 }

// 某家打牌(face_down 即让过,牌面對他家隱藏)
{ "type": "discarded", "seat": 1, "tile": "3c", "face_down": false }

// 鳴牌窗口:告訴「你」可以做什麼,以及截止時間
{ "type": "claim_window", "tile": "3c", "from_seat": 1,
  "your_options": ["pong","skip"], "deadline_ms": 5000 }

// 有人鳴牌成功
{ "type": "call_made", "seat": 2, "call": "pong",
  "tiles": ["3c","3c","3c"], "from_seat": 1 }

{ "type": "ready_declared", "seat": 0 }          // 报听
{ "type": "redraw", "seat": 0 }                  // 重摸發生

// 和牌結算(支援多贏家=一炮多響)
{ "type": "hand_result",
  "winners": [
    { "seat": 0, "win_type": "ron", "from_seat": 2,
      "fans": [{"id":201,"name":"Pure Flush","value":2000}, ...],
      "raw_score": 2150, "final_score": 2150 }
  ],
  "payments": { "0": +2150, "2": -2150, "1": 0, "3": 0 } }

// 荒牌結算(含让过賠付)
{ "type": "draw_result",
  "tenpai_seats": [0,3],
  "payments": { "0": +600, "1": -750, "2": 0, "3": +600 } }

{ "type": "error", "message": "Illegal action: ..." }
```

> 規則:**別家手牌一律不下發牌面**;面向下的让过牌對他家隱藏牌面。所有「個人視圖」由服務端按座位裁剪後再送。

---

## 8. 機器人

Step 1 的機器人**不追求棋力**,而是用來壓力測試摸打與鳴牌流程。提供**兩種行為固定、可預測**的測試機器人。兩者都:**從不和牌**(不自摸、不點和;鳴牌窗口即使可和也不選 `win`)、**不使用让过/重摸/报听**、**只能看見自己可見的狀態**(別把全知狀態餵給它)。

先定一個共同介面(`bots/base.py`):

```python
class Bot:
    def decide_turn(self, view) -> dict: ...
        # 輪到自己(已摸牌)時回傳一個 self_action / discard 動作
    def decide_claim(self, view, options: list[str]) -> dict: ...
        # 鳴牌窗口時回傳 {"type":"claim","claim": ...},不鳴則回 {"claim":"skip"}
```

### 機器人①:純摸打(`discard_only_bot.py`)
最簡單版,只摸打,不吃碰槓、不和。
- **輪到自己**:直接打出**剛摸到的那張牌**(摸切 / tsumogiri,「摸到什麼打什麼」)。不暗槓、不加槓、不重摸、不报听、不自摸。
- **鳴牌窗口**:一律 `skip`(不吃、不碰、不槓、不和河牌)。

### 機器人②:自動鳴牌(`auto_call_bot.py`)
專門用來測吃碰槓:能鳴就鳴,但不和。
- **鳴牌窗口**:只要有合法的吃/碰/槓選項,**一定鳴牌**(可和也不選 `win`);若**只有** `win` 而無吃碰槓可做,則 `skip`。多個選項時按固定優先級選**第一個**:

  > **槓 > 碰 > 吃**;吃之間再按「順子最小牌的數字」由小到大排序(吃 123 > 吃 234 > 吃 345 > …;同數字時按花色 b→c→d 固定排序)。

  鳴牌後需打牌時(碰/吃後,或槓補牌後),**從手牌中隨機打出一張**。
- **輪到自己**(正常摸牌、無可鳴對象時):**從手牌中隨機打出一張**(同樣不暗槓、不重摸、不报听、不自摸)。

### 房間機器人配置
Step 1 的 demo 房有 3 個 bot 座位,**類型可在建房時配置**。建議至少放 1 個「自動鳴牌」bot,才測得到鳴牌窗口的優先級裁決與一炮多響以外的鳴牌路徑;其餘可用「純摸打」bot 製造穩定的牌流。

> 為什麼故意做這麼笨:行為確定 = 出 bug 時容易復現與定位。等核心流程穩了,再做有棋力的啟發式 bot(用 `scoring.shanten` / `waits` 選牌)也不遲。

---

## 9. 開發環境與啟動

### 後端
```bash
cd server
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install fastapi "uvicorn[standard]" pydantic pytest
uvicorn app:app --reload --port 8000
```

### 前端
```bash
cd client
npm create vite@latest . -- --template vanilla-ts   # 首次建立
npm install
npm run dev                                          # http://localhost:5173
```
開發時前端連 `ws://localhost:8000/ws`;Vite 設 proxy 或直接寫絕對位址皆可。

### 測試
```bash
cd server && pytest -q
```

---

## 10. 里程碑 / 任務拆解(請按順序做,每步要能跑+有測試)

1. **搬遷計分引擎**:建 `server/scoring/`,搬入 parsing/fan,CSV 轉 UTF-8,寫 `api.py`(`is_winning`/`score_hand`/`waits`/`shanten`)。`test_scoring_api.py` 用 `MAHJONG.docx`/`fan.csv` 的範例手牌驗證分數正確。
2. **牌與牌牆**:`tiles.py`(對齊引擎 Tile 表示)、`wall.py`(洗牌、發牌、補摸)。
3. **合法動作偵測**:`legal.py`(對棄牌判各家可吃/碰/槓/和)、`redraw.py`(重摸條件)。各自單元測試。
4. **狀態機**:`fsm.py` 先做**不含特殊機制**的基本回合(摸→打→鳴牌窗口→裁決),`resolve_claims` 純函式 + `test_fsm.py`。
5. **WebSocket + 房間**:`protocol/messages.py`、`app.py`、`room.py`。先做「1 人 + 3 bot(可混用兩種類型)」能跑完一整局。注意:兩種測試 bot 都不和牌,所以**全自動的一局通常會走到荒牌**(`draw_result`);要驗證 `hand_result` 需要由人類玩家和牌,或臨時讓某個 bot 在聽牌時宣告和。
6. **薄客戶端**:`client/` 連線、渲染自己手牌+四家河+按鈕,能出牌、能在鳴牌窗口點吃碰槓和,能看到結算。
7. **接入特殊機制**:依序加入 **报听 → 让过(含計數/吃碰上限/賠付) → 重摸 → 一炮多響**,每加一項補測試。
8. **結算完整化**:`settle.py` 套用起和門檻、报听 +100、让过賠付、荒牌賠付。

---

## 11. 工程準則(guardrails)

- 服務端權威;客戶端零信任。所有合法性在服務端複查。
- `fsm.py` 用顯式狀態枚舉,別用一堆 bool 堆疊;轉移集中管理。
- 規則邏輯(`legal`/`redraw`/`resolve_claims`/`settle`)寫成**純函式**,與 async/網路解耦,便於測試。
- 個人視圖裁剪:任何下發給某座位的訊息都不得含他不該看到的牌面。
- 每完成一個里程碑就跑 `pytest`,保持綠燈。
- CSV 與所有原始碼一律 UTF-8。
- 提交訊息與 PR 描述用繁體中文或英文皆可,保持簡潔。

---

## 12. 暫不在 Step 1 範圍(避免過度設計)

- 真實多人連線、匹配、帳號系統、資料庫、Redis(單機房記憶體即可)。
- 寶牌/Dora、連莊累計、整場積分排名。
- 美術、動畫、音效(Phaser 等後續再上)。
- 斷線重連的完整處理(可先做最基本的:重連後重送個人視圖)。

> 完成 Step 1 後,客戶端渲染層替換為 Phaser、後端房間狀態移到 Redis、再加真人匹配,即可往多人線上演進。
