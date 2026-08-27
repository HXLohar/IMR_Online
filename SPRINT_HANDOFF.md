# IMR Online Sprint Handoff

## 目前狀態

- 更新日期：2026-08-27
- 已完成 Sprint（含本地驗收）：S0 — 基線與專案衛生、S1 — 房間狀態與 WebSocket 協定、S2 — 逾時與防卡死、S3 — 斷線恢復、S4 — 起和門檻與報聽、S5 — 特殊和牌與計分驗證、S6 — 前端權威狀態與座位、S7 — 對局與結算 UX、S8 — 大廳與響應式視覺、S9 — E2E 與部署設定
- 下一個入口：連接 Render 帳號，完成公開 HTTPS/WSS、持久磁碟與四位真人對局驗收
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

### S5–S9

- 特殊旗標從 FSM 傳入合法性判斷與結算：槓上開花、搶槓和、海底、天和、地和、天聽與報聽均有覆蓋測試。
- `fan.csv` 的 80 個番種均有 checker；參數化 coverage 與覆蓋／互斥圖測試已加入。來源 CSV 仍有 11 筆牌數或牌張數不合法的原始範例（114、203、204、208、257、258、408–412），文件標記為「規則覆蓋暫定」，未擅自猜改規則資料。
- `match_snapshot` 新增 `called_river_tiles`，並把分數、連線狀態、座位與合法操作送入同一個前端 store；前端自動重連後沿用伺服器快照。
- 牌桌以 `(seat - mySeat + 4) % 4` 映射自家、下家、對家、上家，顯示名稱、分數、手牌數、報聽與連線狀態；回合／宣告倒數使用伺服器絕對期限。
- `hand_result`／`draw_result` 補充分數與完整結算內容，S7 多手局中間由伺服器停留 8 秒後統一進入下一手。
- UI 統一繁中，加入手機斷點、鍵盤選牌、focus-visible、`aria-live` 與安全的結果 DOM 渲染；正式建置保留 `/auth-hero.png` 與 `/tiles/*`。
- 新增 `/healthz`、`IMR_SECURE_COOKIE`、`IMR_DB_PATH`、`IMR_HAND_PAUSE_SECONDS` 與 `IMR_BOT_DELAY_SECONDS`，並加入 `render.yaml`（SQLite persistent disk、正式 threshold、HTTPS cookie）。
- 新增四 WebSocket TestClient E2E、10 局固定種子 bot smoke，以及 seat=3 重連／stale timeout 快照 smoke。

## 公開協定變更

- 新增輸入訊息：`create_room`、`join_room`、`set_room_config`、`start_room`、`queue_join`、`queue_leave`、`leave_room`、`resume` 的 Pydantic schema。
- `room_state.room.seats[*]` 新增 `connected: boolean`。
- 新增伺服器事件：`room_closed`、`room_left`。
- `send()` 現在使用 TypeScript `ClientMessage` union 約束前端輸入。
- `discard`／`self_action` 新增可選 `turn_id`；`claim` 新增可選 `window_id`。
- 新增伺服器事件 `match_snapshot`、`match_lost`、`turn_timeout`、`claim_timeout`；`your_turn`／`claim_window` 新增序號與 `deadline_at_ms`。
- `match_snapshot` 新增 `called_river_tiles`、`players[*].score`／`connected`；`hand_result`／`draw_result` 新增累積 `scores`，荒牌結果另含所有手牌與副露。
- WebSocket 異常關閉時前端以退避重連，伺服器重新送出 `match_snapshot`；`/healthz` 提供部署健康檢查。

## 已知驗證結果

- `python -m pytest -q -p no:cacheprovider --basetemp .pytest-tmp server/tests`：175 passed，3 個既有第三方／FastAPI deprecation warnings。
- `npm run typecheck --prefix client`：通過。
- `npm run build --prefix client`：通過；`/auth-hero.png` 與 `/tiles/*` 由正式 dist 提供。
- `python server/tests/smoke_10_games.py`：10 個固定種子完成，另通過 seat=3 重連快照與 stale timeout 安全檢查。
- 四 WebSocket E2E：通過，四位註冊玩家可經 queue 啟動同一場 match。

## 工作區注意事項

- 工作區原本已有未提交與未追蹤變更；本次保留並在其上修改，沒有使用 reset 或 checkout 覆寫。
- `.venv`、`node_modules`、`client/dist`、Python cache 與 SQLite 只作本機產物。
- Alpha 仍維持單一 FastAPI 行程、SQLite 與原生 TypeScript；未加入 Redis、Postgres、前端框架、微服務或部署平台依賴。

## 外部驗收入口

使用 `render.yaml` 連接 Render 帳號後，完成公開 HTTPS/WSS、持久磁碟重部署保留資料，以及四位真人完整牌局；在此之前不得宣稱 Alpha 已有可供朋友使用的公開網址。

## 禁止假設

- 本地 S5–S9 已完成實作與驗收，但外部 Render 帳號、公開網址與四真人驗收尚未完成。
- 11 筆原始 `fan.csv` 範例的規則覆蓋仍為暫定，不得把修正 parser 或 checker 解讀成已取得缺失的正式規則文件。
- 10 局 smoke 使用 `IMR_WIN_THRESHOLD_MODE=test`、零 bot delay 與零手間 pause，僅驗證狀態機不死局；不等同於正式環境負載或公開服務驗收。
- 不假設目前未提交變更可以捨棄或重寫。
