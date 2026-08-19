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
