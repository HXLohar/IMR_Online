# IMR Online

朋友 Alpha 的 FastAPI + 原生 TypeScript 麻將對局。

## 開發環境

- Python 3.12+
- Node.js 20+

從 repo 根目錄安裝依賴：

```powershell
python -m pip install -r server/requirements.lock
npm ci --prefix client
```

## 測試與建置

```powershell
python -m pytest
npm run typecheck --prefix client
npm run build --prefix client
```

`client/dist`、`client/node_modules`、Python cache 與 SQLite 檔案都是本機產物，不會納入 Git。

## 本機啟動

終端機一：

```powershell
cd server
python -m uvicorn app:app --reload --port 8000
```

終端機二：

```powershell
npm run dev --prefix client
```

瀏覽 <http://localhost:5173>。Windows 也可直接執行根目錄的 `play.bat`；它只使用 `%~dp0` 定位 repo，不依賴固定電腦路徑。

## 環境變數

Alpha 的資料庫預設使用 `server/imr.sqlite3`。正式環境可在啟動前設定 `IMR_DB_PATH` 指向其他 SQLite 檔案；未設定時使用預設值。

正式部署另設定 `IMR_SECURE_COOKIE=true`，並以 `/healthz` 作為服務健康檢查。`IMR_WIN_THRESHOLD_MODE=test`、`IMR_DISABLE_WIN_THRESHOLD=1`、`IMR_HAND_PAUSE_SECONDS=0` 與 `IMR_BOT_DELAY_SECONDS=0` 僅供測試／smoke 使用；Render Blueprint 已列出持久磁碟與正式門檻設定。

## 牌牆生成驗證

頁面底部顯示目前伺服器密鑰的 SHA-256，並提供在新分頁開啟的密鑰更換紀錄與對局驗證器。驗證器在瀏覽器本地運算，不上傳輸入的密鑰；需要 HTTPS 或 localhost。

在伺服器主機執行 `rotate_server_key.bat` 更換密鑰；它會使用 `.venv`（或 `py`）及與伺服器相同的 `IMR_DB_PATH`。正在進行任何對局時會拒絕更換，防止舊密鑰公開後洩露未結束的牌牆。更換成功後，下一場對局立即使用新密鑰，不需重啟。歷史頁顯示退役密鑰、對應哈希、啟用與更換時間。密鑰與紀錄保存在原 SQLite 資料庫中，應保護資料庫及備份；不要將它們公開或提交至 Git。

本功能沿用單一伺服器程序的部署方式。重啟後無法恢復的對局會在持久紀錄中標為 `interrupted`，已使用的對局計數不會回退。更換工具必須操作實際伺服器的資料庫；更換本機另一份資料庫不會更換遠端密鑰。

每場對局開局時原子地固定密鑰與四家的「此前已開局數」，並將計數加一；計數包含所有模式及中斷局，以整場對局而非小局計算。既有玩家第一次使用此功能時，計數以原本已保存的對局數初始化。機器人使用 `user_id: null`、計數 0 與機器人類型。對局 ID、小局編號及莊家也作為固定輸入。每小局發牌前，四家收到 `fairness` 資料，包括密鑰哈希、牌牆哈希及所有輸入；重連保持原資料。牌譜和頁尾提供驗證入口，資料可自動填入驗證器。舊牌譜仍可讀取，但沒有這項事前承諾。

算法版本為 `imr-hmac-sha256-v1`：

1. 用 UTF-8 編碼無空白的 JSON 陣列 `[version, match_id, hand, dealer, [[seat, user_id, games_played, bot], ...]]`，四家按座位 0–3 排列。
2. 密鑰是 32 個原始隨機位元組，歷史頁以 64 位十六進位公開；密鑰承諾是原始位元組的 SHA-256。
3. 每個隨機區塊是 `HMAC-SHA256(key, encoded_context || 0x00 || uint32_be(counter))`，counter 從 0 開始。依序以大端序讀取 32 位整數。
4. 對實體牌編號 0–135 做倒序 Fisher–Yates。每步範圍大小為 m，拒絕所有 `x >= floor(2^32/m)*m` 的值，再以 `x mod m` 選擇交換位置。
5. 實體牌編號取模 34，依序映射到萬 1–9、筒 1–9、索 1–9、東南西北白發中。牌牆承諾為洗牌後 136 個實體牌編號位元組的 SHA-256。
6. 沿用現有發牌：從座位 0 起，三輪各 4 張，再各 1 張，四家各 13 張；下一張是莊家首摸，驗證器另列。一般摸牌從前端，杠補牌從末端。

可執行 `npm run test:fairness --prefix client` 檢查瀏覽器算法與 Python 共用的公開測試向量，以及輸入錯誤與承諾不符的拒絕行為。

此功能證明「收到的承諾與公開輸入能重建相同牌牆」。玩家 ID、計數、座位並非獨立隨機來源，因此它不能證明伺服器在公布承諾前沒有篩選密鑰或匹配組合，也不能排除選擇性中止。更強的生成公平需要加入承諾後才出現的玩家隨機貢獻或未來公共信標。
