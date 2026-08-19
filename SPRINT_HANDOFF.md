# IMR Online Sprint Handoff

## 目前狀態

- 更新日期：2026-08-19
- 已完成 Sprint：S0 — 基線與專案衛生、S1 — 房間狀態與 WebSocket 協定、S2 — 逾時與防卡死、S3 — 斷線恢復、S4 — 起和門檻與報聽
- 下一個 Sprint：S5 — 特殊和牌與計分驗證
- Alpha 計畫：已記錄於 `ALPHA_PLAN.md`

## 已完成內容

### S0

- 加入根目錄 `pytest.ini`、README、Python lockfile 與前端 `typecheck` 命令。
- 修正 setuptools build backend 與 flat-layout package discovery，新的隔離環境可安裝 `server[dev]`。
- 停止追蹤 `client/node_modules`、`client/dist` 與 Python cache；保留本機檔案並加入 `.gitignore`。
- 將 Windows 啟動批次檔改為使用 `%~dp0`，不再依賴固定絕對路徑。

### S1

- 所有大廳、房間與牌局輸入統一經 Pydantic v2 discriminator 驗證。
- 新增與 TypeScript 對齊的 client message union。
- 房間座位廣播 `connected`；建立、加入、設定、離房與重連都會更新 `room_state`。
- 非房主仍無法修改設定或開始房間。
- 房主明確離房會向所有房客發送 `room_closed` 並清理座位映射；房客離房回到大廳。
- WebSocket 重連會依既有房間映射直接恢復房間畫面。

### S2–S4

- Match 使用單一 `asyncio.Lock`；回合與宣告窗帶單調 `turn_id`／`window_id`、絕對伺服器期限與自動逾時。
- 逾時宣告統一視為 skip；回合逾時安全棄出摸入牌；前端回傳序號，過期訊息不改變狀態。
- 斷線玩家保留牌局座位，排隊斷線立即移除；60 秒後由既有 AI 接管，重連取消接管並取得 `match_snapshot`。
- Snapshot 含牌局、牌牆游標、分數、河牌、副露、自家手牌、合法操作與剩餘期限，不暴露他人手牌；找不到牌局時回傳 `match_lost`。
- 報聽與指定棄牌原子完成，保存等待集合；後續棄牌與各類槓必須維持同一等待集合。
- 起和門檻正式預設啟用；只有明確設定 `IMR_WIN_THRESHOLD_MODE=test`、`IMR_DISABLE_WIN_THRESHOLD=1` 或 `IMR_MIN_WIN_SCORE=0` 才停用。

## 公開協定變更

- 新增輸入訊息：`create_room`、`join_room`、`set_room_config`、`start_room`、`queue_join`、`queue_leave`、`leave_room`、`resume` 的 Pydantic schema。
- `room_state.room.seats[*]` 新增 `connected: boolean`。
- 新增伺服器事件：`room_closed`、`room_left`。
- `send()` 現在使用 TypeScript `ClientMessage` union 約束前端輸入。
- `discard`／`self_action` 新增可選 `turn_id`；`claim` 新增可選 `window_id`。
- 新增伺服器事件 `match_snapshot`、`match_lost`、`turn_timeout`、`claim_timeout`；`your_turn`／`claim_window` 新增序號與 `deadline_at_ms`。

## 已知驗證結果

- `python -m pytest`：82 passed，3 個既有第三方／FastAPI deprecation warnings。
- `npm run typecheck --prefix client`：通過。
- `npm run build --prefix client`：通過。
- Python 3.12 語法編譯：通過。

## 工作區注意事項

- 工作區原本已有未提交與未追蹤變更；本次保留並在其上修改，沒有使用 reset 或 checkout 覆寫。
- `.venv`、`node_modules`、`client/dist`、Python cache 與 SQLite 只作本機產物。
- Alpha 仍維持單一 FastAPI 行程、SQLite 與原生 TypeScript；未加入 Redis、Postgres、前端框架、微服務或部署平台依賴。

## 下一 Sprint 入口

執行 S5，且只處理特殊和牌與計分驗證；不得假設 S5 以後的前端座位視角或部署功能已完成。

## 禁止假設

- S2–S4 已完成；S5 尚未實作，不要把目前特殊和牌與計分覆蓋率當成完成。
- 不假設目前未提交變更可以捨棄或重寫。
- 不提前處理 S4 以後的規則、計分、座位視角或部署需求。
