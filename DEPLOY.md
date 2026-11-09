# 部署：用 Cloudflare Tunnel 把線上客服放上網路

架構：程式在你們自己的一台電腦上執行，只開在 `127.0.0.1:7860`（區網連不到）。
Cloudflare Tunnel 從這台電腦主動連到 Cloudflare，使用者連 `https://你們的網域` 時，流量經由 Tunnel 送進來。
電腦不用開防火牆埠，也不用固定 IP。

```text
使用者瀏覽器 ──HTTPS──> Cloudflare ──Tunnel──> 這台電腦的 cloudflared ──> 127.0.0.1:7860（app.py）
```

## 0. 先決定由哪台電腦執行

- 這台電腦要一直開機、不睡眠、有穩定網路，直到 2026/11/28 投票日結束。
  - macOS：系統設定 → 電池（或能源）→ 接上電源時不要自動睡眠。或在終端機執行 `caffeinate -s` 並保持視窗開著。
- **把專案資料夾放在「桌面」「文件」「下載」以外的地方**，例如 `~/vote-bus-agent`。
  macOS 會擋背景服務讀取這三個資料夾，放在那裡，開機自動啟動會失敗。

## 1. 準備程式

```bash
cd ~/vote-bus-agent
pip install -r requirements.txt
cp .env.example .env
```

打開 `.env`，填入：

| 設定 | 內容 |
|---|---|
| `API_KEY` | Gemini API 金鑰。正式上線建議用**付費方案**：免費方案的內容可能被用來改善 Google 的產品，額度也很容易用完。 |
| `ORDER_SHEET_CSV_URL` | 訂單試算表的 CSV 匯出連結：`https://docs.google.com/spreadsheets/d/<試算表ID>/export?format=csv&gid=0`。**只寫在 `.env`，不要放進 GitHub 或任何公開的地方。** |
| `SESSION_SECONDS`（選填） | 登入後多久沒對話就自動登出，預設 1800 秒（30 分鐘）。 |
| `CONCURRENCY`（選填） | 同時處理幾位使用者的問題，預設 8。 |

先在本機試跑，打開 <http://127.0.0.1:7860> 確認正常：

```bash
python app.py
```

## 2. 建立 Cloudflare Tunnel（在 Cloudflare 網站上操作）

需要一個 Cloudflare 帳號，以及一個已經交給 Cloudflare 管理 DNS 的網域。

1. 登入 Cloudflare → **Zero Trust** → **Networks** → **Tunnels** → **Create a tunnel** → 選 **Cloudflared**。
2. 取名，例如 `vote-bus`。
3. 頁面會給一行安裝指令，裡面有一串 **token**。token 等同密碼，不要貼到公開的地方。
4. **Public Hostname**：
   - Subdomain：例如 `help`；Domain：你們的網域
   - Service：`HTTP`，URL：`127.0.0.1:7860`
5. 儲存。

## 3. 在電腦上啟動 Tunnel

```bash
brew install cloudflared
sudo cloudflared service install <上一步的 token>
```

這會把 cloudflared 裝成系統服務，開機自動連線。之後在 Cloudflare 的 Tunnels 頁面應該會看到狀態是 **HEALTHY**。

## 4. 讓客服程式開機自動執行、當掉自動重啟（macOS）

1. 打開 `deploy/org.tyad.votebus.plist`，改兩個路徑：
   - `start.sh` 的完整路徑（例如 `/Users/你的帳號/vote-bus-agent/deploy/start.sh`）
   - `PYTHON`：裝好套件的 Python（例如 `/opt/anaconda3/envs/ai26/bin/python`）
2. 安裝並啟動：

   ```bash
   cp deploy/org.tyad.votebus.plist ~/Library/LaunchAgents/
   launchctl load ~/Library/LaunchAgents/org.tyad.votebus.plist
   ```

3. 程式的輸出會寫在 `logs/app.log`。要停止：

   ```bash
   launchctl unload ~/Library/LaunchAgents/org.tyad.votebus.plist
   ```

改了程式或 `.env` 之後，先 unload 再 load 一次。

## 5. 上線前檢查

- [ ] 用手機的行動網路（不是同一個 Wi-Fi）打開 `https://help.你們的網域`，頁面正常。
- [ ] 一般訪客問「我的車票寄出了嗎？」，會請你先登入，而且看不到任何訂單資料。
- [ ] 用一筆真實訂單登入，只看得到那筆訂單。問別的訂單編號，客服會拒絕。
- [ ] 頁面上方**沒有**「🧪 測試模式」字樣（有的話，代表 `.env` 沒讀到 `ORDER_SHEET_CSV_URL`）。
- [ ] 座位那一行顯示「官方座位檢視表（表上更新日期 …）」，不是「備用資料 routes.csv」。

## 6. 建議在 Cloudflare 加上的保護（免費方案就有）

- **Security → Bots → Bot Fight Mode**：擋掉自動化的機器人流量。
- **Security → WAF → Rate limiting rules**：限制同一 IP 短時間內的請求次數。程式本身也會限制每個 IP 在 15 分鐘內最多輸錯 10 次訂單編號。
- 不要開 Cloudflare 的 **Cache Everything**：每位使用者的頁面內容不同，不能被快取。

## 7. 已知限制與之後可以改進的地方

- **訂單試算表目前是「知道連結就能看」。** 有連結的人不必透過客服，就能直接看到所有訂單。
  建議改成「限制」，再用 Google 服務帳戶（Sheets API）讀取。這需要改 `refresh_orders()` 的讀取方式。
- 訂單編號是唯一的登入憑證。拿到別人訂單編號的人可以查那筆訂單，能看到遮蔽過的姓名、車次和狀態。
- 登入狀態存在伺服器記憶體裡（每個分頁一份，約幾十位元組）。程式重啟後，大家要重新登入。
- 訂單表與座位表都暫存在記憶體中，不寫入硬碟。訂單表最多 30 秒重讀一次，座位表最多 60 秒。
- Gemini 免費方案每分鐘可呼叫的次數很少。11/27 前使用者集中時，請改用付費方案，並留意帳單。
