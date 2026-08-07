# PIME

這個目錄不是原始碼專案，而是 **PIME**（Plugin platform for Input Method Editor）的安裝目錄——一套開源的 Windows 中文輸入法框架，讓輸入法邏輯可以用 Python 或 Node.js 撰寫，而不必直接用 C++ 對接 Windows TSF（Text Services Framework）API。

版本：`version.txt` = 1.3.0-stable

## 目錄結構

- `PIMETextService.dll`（`x86/`、`x64/` 各一份）— 核心 COM 元件，實作 TSF 的 `ITfTextInputProcessor`，是實際跟 Windows 輸入框架溝通的部分。
- `PIMELauncher.exe` — 由 DLL 依 `backends.json` 設定拉起的後端伺服器啟動器。不是 Windows 服務（沒有 `services.msc` 項目），但**一旦被觸發啟動就會持續常駐**，不會因為切換輸入法、或關閉/重開某個文字輸入框而自動重啟——實測中它可以連續跑好幾個小時。這代表修改 `.cin`/`.json` 字碼表或 Python 程式碼後，如果沒有真的砍掉這個進程重開，改動不會生效（見下面「已建立的輔助腳本」章節）。
- `backends.json` — 定義後端執行環境：
  - `python`：`python\python3\python.exe server.py`
  - `node`：`node\node.exe server.js`
- `python/` — Python 後端實作
  - `server.py` — 透過 named pipe 跟 `PIMETextService.dll` 溝通
  - `textService.py` / `serviceManager.py` — 核心邏輯
  - `input_methods/` — 已安裝的輸入法：`chewing`（新酷音/注音）、`cheliu`
  - `libchewing`、`opencc`（簡繁轉換）— 相依函式庫
- `Uninstall.exe` — 完整解除安裝程式（會做 TSF/COM 取消註冊 + 刪檔 + 清控制台項目）

## 啟動（註冊）/ 停止（取消註冊）機制

PIME 是透過標準 **COM + TSF 註冊**機制掛進系統的，不是 Windows 服務（沒有對應的 `services.msc` 項目），因此「啟動/停止」實際上指的是「註冊/取消註冊 COM 元件並登記/移除 TSF 輸入法」。

已確認目前系統上的登錄狀態：
```
HKLM\SOFTWARE\Classes\CLSID\{35F67E9D-A54D-4177-9697-8B0AB71A9E04}
    (預設) = PIMETextService
    InprocServer32 = C:\Program Files (x86)\PIME\x64\PIMETextService.dll
```
同一個 CLSID 也出現在 `HKLM\SOFTWARE\Microsoft\CTF\TIP\{35F67E9D-...}` 底下，代表它同時被登記為 TSF 輸入法服務。

**註冊（啟動）：**
```
regsvr32 "x86\PIMETextService.dll"
regsvr32 "x64\PIMETextService.dll"
```
呼叫 DLL 匯出的 `DllRegisterServer`，寫入 CLSID/InprocServer32，並透過 TSF 的 `ITfInputProcessorProfiles` API 登記為輸入法（寫入 `CTF\TIP` 機碼）。

**取消註冊（停止）：**
```
regsvr32 /u "x86\PIMETextService.dll"
regsvr32 /u "x64\PIMETextService.dll"
```
呼叫 `DllUnregisterServer`，清除上述登錄。取消註冊前應先切換掉目前使用中的輸入法，避免文字服務占用中無法卸載。

兩者都需要**系統管理員權限**（寫入 HKLM）。權限是進程層級的——必須用「以系統管理員身分執行」開啟終端機/腳本，無法在對話過程中臨時「授予」。

**重要更正（實測發現）：** 原本以為 `PIMELauncher.exe` 會在使用者切換到 PIME 管理的輸入法時，由 DLL 自動拉起——**實測發現不成立**。不管怎麼重新 `regsvr32` 註冊、怎麼切換輸入法，DLL 都沒有把 `PIMELauncher.exe` 叫起來，結果就是輸入法選了、Shift 切中文模式也切了，但按鍵完全沒被攔截，直接輸出成英文字母。這個問題的根本原因**還沒查證**，之前寫「可能是 client 端應用程式的權限/沙盒層級問題」只是未驗證的猜測，不要當成定論。從使用者能在網路上直接查到「執行 `PIMELauncher.exe` 就解決了」這個現成解法來看，這比較像是 PIME 社群裡頗常見的已知現象，不確定是不是這台機器獨有的環境問題。

**正確做法：必須手動先把 `PIMELauncher.exe` 開起來，讓它常駐等待，DLL 之後才連得上去。** 一旦 `PIMELauncher.exe` 是用這種方式（獨立執行，不是被 DLL 拉起）啟動，它就會自己接著啟動 `python\python3\python.exe server.py` 當後端（兩者啟動時間只差不到 1 秒）。也因此這個進程一旦啟動就會持續常駐，不會因為切換輸入法、或關閉/重開某個文字輸入框而自動重啟或重新載入——實測中它可以連續跑好幾個小時。這代表修改 `.cin`/`.json` 字碼表或 Python 程式碼後，如果沒有真的砍掉這個進程重開，改動不會生效（見下面「已建立的輔助腳本」章節）。

## 已建立的輔助腳本

- `register-pime.bat` — 以系統管理員身分執行：先停止現有的 PIME 後端行程，**明確重新啟動 `PIMELauncher.exe`**（見下方原因），再對 x86/x64 兩份 DLL 執行 `regsvr32`（註冊/啟動）
- `unregister-pime.bat` — 以系統管理員身分執行：先停止現有的 PIME 後端行程，再對 x86/x64 兩份 DLL 執行 `regsvr32 /u`（取消註冊/停止）

兩個腳本都會先檢查是否具備系統管理員權限（用 `net session` 測試），沒有的話會提示需要「以系統管理員身分執行」再重新執行。

**停止後端行程的邏輯（兩支腳本都有）：**
```
taskkill /F /IM PIMELauncher.exe
powershell -NoProfile -Command "Get-Process -Name python -ErrorAction SilentlyContinue | Where-Object { $_.Path -ieq 'C:\Program Files (x86)\PIME\python\python3\python.exe' } | Stop-Process -Force"
```
`PIMELauncher.exe` 用行程名稱直接砍掉即可（名稱夠獨特）。`python.exe` 則故意不用 `taskkill /IM python.exe`，因為那樣會砍掉使用者電腦上**所有**叫 python.exe 的行程（例如使用者自己在跑的其他 Python 腳本），改用 PowerShell 依**完整執行檔路徑**過濾，只砍 PIME 自己那個 `python\python3\python.exe`，避免波及無關行程。

**`register-pime.bat` 額外多一步：`start /D "C:\Program Files (x86)\PIME\" PIMELauncher.exe`**，砍完舊行程後立刻手動重新啟動 `PIMELauncher.exe`。這是因為實測發現 `PIMETextService.dll` 沒有在使用者切換輸入法時自動把 `PIMELauncher.exe` 拉起來（根本原因不明，見上一節說明），症狀是：切換輸入法、按 Shift 切中文模式都「有反應」，但按鍵完全沒被攔截，直接輸出英文字母，且怎麼查都找不到 `PIMELauncher.exe`／`python.exe` 這兩個行程在跑。手動用 `start` 先把 `PIMELauncher.exe` 獨立啟動、讓它常駐，`PIMELauncher.exe` 之後就會自己接著啟動 `python\python3\python.exe server.py` 當後端（兩者啟動時間只差不到 1 秒），DLL 之後只要連上這個已經在跑的常駐行程即可，不用自己再嘗試產生新行程。

新增停止/重啟這段的原因：改完蝦米字碼表（`liu.cin`/`liu.json`）或 `cheliu_ime.py` 後，光是切換輸入法測試，`python.exe` 後端進程完全沒有重啟過，導致改動一直不生效、也沒有任何錯誤訊息，只會表現成「查無組字」之類的假象（誤以為是字碼表寫錯）。之後改完程式碼或字碼表要測試，記得先跑一次 `unregister-pime.bat` 再跑 `register-pime.bat`，再重新切換輸入法，才能確保是用最新的檔案在跑，而且 `PIMELauncher.exe` 真的有被啟動起來。

**編碼注意事項：** 這兩支腳本內文刻意全用 ASCII 英文，沒有放中文。原因是最初版本內含中文註解/訊息，UTF-8 存檔後在這台機器上用 `cmd.exe` 執行時，因為主控台的作用中文碼頁不是 UTF-8，多位元組的中文字被誤判成 `&`、`|` 之類的特殊字元，導致整行被拆成好幾個「無法辨識的命令」而報錯。在 `@echo off` 後加 `chcp 65001 >nul` 理論上可解，但在這台機器上實測仍失敗（cmd 對批次檔的頁碼切換時機不夠可靠），因此改用純 ASCII 內容澈底避開這個問題。**之後若要修改這兩支 .bat，避免加入中文字元。**

## 蝦米（cheliu）字碼表

字碼表運作方式（詳見前面「如何修改字碼」的討論）：
- 人工編輯用的原始碼表：`python\cinbase\cin\liu.cin`（`.cin` 純文字格式，`%chardef` 區塊是「鍵碼 字元」對應）
- 實際執行期讀取的檔案：`python\cinbase\json\liu.json`（`.cin` 用 `python\cinbase\tools\cintojson.py` 轉換產生，引擎只讀這份 JSON，不會去讀 `.cin`）
- 改完 `.cin` 後必須執行 `python\python3\python.exe python\cinbase\tools\cintojson.py liu.cin` 重新產生 JSON，並重啟 PIME 後端（或切換掉再切回輸入法）才會生效，因為字碼表是啟動時載入後快取在記憶體中的。

**目前狀態：字碼表已整份換成 RIME 版本（`references/liur_Trad.dict.yaml`）轉換而來**，取代原廠 PIME 內建的 `liu.cin`／`liu.json`。

原因：官方嘸蝦米正式版支援用 `v r s f` 選第 2~5 候選字，但這套 PIME 的 `cheliu` 模組沒有實作這個選字機制（`cinbase/config.py` 的 `selKeys` 只有 `"1234567890"` 一種，不像 `chewing` 模組有多組可切換）。RIME 的字碼表用另一種等效做法解決同樣的問題：直接把消歧義用的按鍵（如 `v`）當作字碼的一部分寫進字典裡，例如「我」的碼是 `ix`，跟「曳」衝突，RIME 就多加一筆 `ixv → 曳`，讓使用者打 `ixv` 直接出「曳」不用選字。這是純資料表寫法，不需要改 PIME 引擎的程式邏輯，cin 格式本來就支援任意長度、多對一的碼。

轉換內容：
- 備份：`python\cinbase\cin\liu.cin.bak`、`python\cinbase\json\liu.json.bak`（換表前的原始版本）
- 新表：把 `references/liur_Trad.dict.yaml`（格式為「字\t字碼」，`~` 開頭的字碼代表次要/重複條目）逐行轉成 cin 的「字碼 字」格式，塞進原本 `liu.cin` 的 `%chardef` 區塊（開頭的 `%gen_inp`/`%ename`/`%cname`/`%selkey`/`%keyname` 沿用原檔，沒有改動），再用 `cintojson.py` 轉出新的 `liu.json`
- 已驗證：新表裡 `ix` 對應 `['我', '曳']`（維持原本的候選字碰撞），`ixv` 對應 `['曳']`（可直接上字，不跳候選視窗），符合 RIME 表原本設計的行為
- 新表最長字碼到 5 碼（原表最長 4 碼），因此把 `python\input_methods\cheliu\cheliu_ime.py` 裡的 `self.maxCharLength` 從 `4` 改成 `5`，否則新表裡約 1937 個 5 碼字根會因為超過原本上限而永遠打不出來

若要復原成 PIME 原廠字碼表：把 `liu.cin.bak`／`liu.json.bak` 複製回 `liu.cin`／`liu.json`（去掉 `.bak`），並把 `maxCharLength` 改回 `4`。
