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

## Git 追蹤範圍

這個目錄有掛 git（私人 repo：`https://github.com/mhbai/PIME`），但**只追蹤真正改過的東西**，不是整個 PIME 安裝目錄：

- `python\input_methods\cheliu\`（蝦米模組本身，所有新功能都寫在這裡）
- `CLAUDE.md`、`README.md`、兩支 `register`/`unregister-pime.bat`

**`cinbase\` 整個資料夾都不追蹤**（`git rm -r --cached python/cinbase/` + `.gitignore` 裡整條 `python/cinbase/` 排除），原則很簡單：**沒有實際改過的東西就不放進 git**。這包含：
- `cinbase\__init__.py`／`config.py`／`cin.py` 這三個引擎程式檔——原本都各自被我們改過（反查拼音功能、`hasPrefix()`），後來全部搬到 `cheliu_ime.py` 或發現不需要，現在完全恢復原廠。
- `cinbase\json\`、`cinbase\data\`、`cinbase\icons\`、`cinbase\config\`（網頁設定介面）、`cinbase\tools\` 這些——這些是 PIME 原始安裝就有的東西（各輸入法共用的碼表資料、資源檔），**從頭到尾都沒被我們動過**，只是因為 PIME 的目錄設計把所有輸入法的碼表都集中放在這個共用資料夾，所以一開始 `git add` 時被一起掃進去，並非我們刻意選擇追蹤。
- 包含 `cinbase\json\liu.json`、`cinbase\cin\liu.cin`——雖然內容是蝦米專屬的字碼表，但因為實體檔案位置也在 `cinbase\` 底下、而且內容跟官方一致，一併排除。

蝦米新增的功能（v/r/s/f 快速選字、反查拼音）全部只靠讀取 `cinbase` 公開的屬性（`self.cin.chardefs`、`self.compositionChar`、`self.multifunctionmode` 等）跟呼叫既有方法（`self.cinbase.setOutputString(...)`、`self.cinbase.resetComposition(...)`）完成，程式碼本身完全寫在 `cheliu_ime.py` 裡，所以整個 `cinbase\` 資料夾對這個 repo 來說就是「新電腦裝官方版就會有」的東西，不需要我們額外提供。

**`python\libchewing\`（`ChewingContext`／`chewing.dll`／辭典資料）同樣完全沒追蹤**，理由一樣：反查拼音功能有 import 它（`from libchewing import ChewingContext, CHEWING_DATA_DIR, CHINESE_MODE, HALFSHAPE_MODE`），但只是呼叫既有 API，從沒改過裡面任何一行（`git log` 查過，只有最初整包匯入那次紀錄）。已經確認過官方 `installer.nsi` 的 Register 區塊會把 `python\libchewing\` 整個資料夾在**任一個** Python 輸入法被勾選時就無條件裝進去，跟「新酷音」這個獨立勾選框無關，所以新電腦裝官方版一樣會有一模一樣的複本。

二進位檔（`PIMELauncher.exe`、DLL、Python 直譯器）跟第三方前端函式庫也都沒有追蹤，細節見 `.gitignore` 裡的註解。

在新電腦上安裝的流程是「先裝官方 PIME 1.3.0-stable，再用 `git init` + `git reset --hard origin/master` 疊上這個 repo 的內容」，完整步驟寫在 `README.md`。

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

**`regsvr32` 加了 `/s`（silent）：** 原本 `regsvr32` 成功/失敗都會跳出訊息視窗要手動按掉，兩支腳本現在都用 `/s` 讓它安靜執行，改用 `%errorlevel%` 判斷成功與否，直接印文字訊息（`x86/x64 build registered/unregistered successfully.` 或 `[ERROR] ... exit code ...`），不用再用滑鼠點掉彈窗。

**編碼注意事項：** 這兩支腳本內文刻意全用 ASCII 英文，沒有放中文。原因是最初版本內含中文註解/訊息，UTF-8 存檔後在這台機器上用 `cmd.exe` 執行時，因為主控台的作用中文碼頁不是 UTF-8，多位元組的中文字被誤判成 `&`、`|` 之類的特殊字元，導致整行被拆成好幾個「無法辨識的命令」而報錯。在 `@echo off` 後加 `chcp 65001 >nul` 理論上可解，但在這台機器上實測仍失敗（cmd 對批次檔的頁碼切換時機不夠可靠），因此改用純 ASCII 內容澈底避開這個問題。**之後若要修改這兩支 .bat，避免加入中文字元。**

## 蝦米（cheliu）字碼表

字碼表運作方式（詳見前面「如何修改字碼」的討論）：
- 人工編輯用的原始碼表：`python\cinbase\cin\liu.cin`（`.cin` 純文字格式，`%chardef` 區塊是「鍵碼 字元」對應）
- 實際執行期讀取的檔案：`python\cinbase\json\liu.json`（`.cin` 用 `python\cinbase\tools\cintojson.py` 轉換產生，引擎只讀這份 JSON，不會去讀 `.cin`）
- 改完 `.cin` 後必須執行 `python\python3\python.exe python\cinbase\tools\cintojson.py liu.cin` 重新產生 JSON，並重啟 PIME 後端（或切換掉再切回輸入法）才會生效，因為字碼表是啟動時載入後快取在記憶體中的。

**目前狀態：用的是原廠 PIME 內建的 `liu.cin`／`liu.json`（stock，未修改）。**

這中間有一段換表又換回來的歷史，記錄一下避免以後搞混：
1. 一開始為了解決「打 `ix` 會撞到我/曳，正式版嘸蝦米可以用 `v` 選字，PIME 沒做這功能」的問題，把整份表換成用 RIME 的 `references/liur_Trad.dict.yaml`（嘸蝦米字碼表的衍生資料）轉換出來的版本，裡面刻意加了 `ixv → 曳` 這類靠 `vrsf` 接續字母消歧義的碼。轉換方式跟細節（含 `maxCharLength` 當時改成 5）仍留著紀錄在 git 歷史裡（commit `40cf4d8` 之前那次）。
2. 後來發現這個做法的根本問題：那份轉換出來的表是嘸蝦米有版權碼表的衍生物，**不能自由分享/散佈**，違背了想把這些改動開源分享的初衷。
3. 所以改成用「v/r/s/f 快速選字」這個**純邏輯**方案（見下一節），完全不需要動字碼表就能達到一樣的選字體驗，而且是完全獨立的 `cheliu_ime.py` 改動，不影響其它 cin 系輸入法。
4. 邏輯方案驗證沒問題後，**把 `liu.cin`／`liu.json` 換回原廠版本**（用備份 `liu.cin.bak`／`liu.json.bak` 複製回去），`maxCharLength` 也改回 `4`。RIME 轉換版的表原本另存成 `liu.cin.rime-derived`／`liu.json.rime-derived`（僅供本機參考，從未進 git，後來也整個刪掉了，見下一點）。
5. 既然選字問題已經完全靠程式邏輯解決，`references\liur_Trad.dict.yaml`（RIME 字碼表原始資料，341KB）跟上面提到的 `liu.cin.rime-derived`／`liu.json.rime-derived` 都已經從磁碟上整個刪掉，不再需要留著任何 RIME 相關的衍生資料。

現在整包（`cinbase`/`cheliu_ime.py` 的程式邏輯 + 原廠 PIME 字碼表）都可以自由分享，沒有版權疑慮。

## 設定檔的真正生效位置：`%APPDATA%\PIME\<imeDirName>\config.json`

**重要陷阱：** 每個 cin 系輸入法在 `python\input_methods\<ime>\config\config.json` 的那份，只是**第一次執行時的預設值範本**。`cinbase\config.py` 的 `CinBaseConfig.load()` 邏輯是：優先讀 `%APPDATA%\PIME\<imeDirName>\config.json`（使用者專屬複本），只有這份不存在或是空的，才會退而讀安裝目錄裡的範本。也就是說，**一旦電腦上已經跑過這套輸入法，`%APPDATA%` 底下就已經有一份複本，之後修改安裝目錄裡的 `config.json` 範本完全不會生效**，因為程式根本不會再去讀那份範本。

實際踩到的例子：新增 `pinyinReverseLookup` 這個設定欄位時，改了 `python\input_methods\cheliu\config\config.json` 加上 `"pinyinReverseLookup": true`，但因為這台機器的 cheliu 早就跑過（`C:\Users\<user>\AppData\Roaming\PIME\cheliu\config.json` 已存在，日期是舊的），實際套用到 `cbTS.pinyinReverseLookup` 的還是 `CinBaseConfig` 裡的預設值 `False`（因為那份舊的 `%APPDATA%` 複本裡根本沒有這個欄位，`json.load()` 更新時自然不會補上）。症狀是功能完全沒反應，而且**沒有任何錯誤或例外**，很容易誤判成程式邏輯有問題，實際上只是設定沒套用到。

**之後在 `cinbase/config.py` 裡新增任何設定欄位、並且需要某個已經在用的 IME 預設開啟時，記得同時手動修改 `%APPDATA%\PIME\<imeDirName>\config.json` 這份實際生效的複本**（不是只改安裝目錄裡的範本），或是刪掉那份複本讓它退回讀範本（但這樣會連使用者原本的其他自訂設定一起清掉，通常不建議）。

## `autoClearCompositionChar`：拆錯字碼自動清除輸入字串

打一串查無此字根組合的字碼（例如 `LLLL`）按空白鍵，`cinbase` 只會跳出「查無組字...」的訊息，**預設不會清掉打錯的字**，還要自己按退格清掉才能重打。這個行為其實 `cinbase` 已經做好開關了（設定選單裡的「拆錯字碼時自動清除輸入字串」，對應 `cbTS.autoClearCompositionChar`，`cinbase/__init__.py` 裡「查無組字」的分支本來就有 `if cbTS.autoClearCompositionChar: ... self.resetComposition(cbTS)` 這段），只是預設值是 `false`，純粹是設定值的問題，**不用改任何程式碼**。

把 `python\input_methods\cheliu\config\config.json`（範本）跟 `%APPDATA%\PIME\cheliu\config.json`（實際生效複本，見上一節）裡的 `"autoClearCompositionChar"` 都改成 `true` 就會變成嘸蝦米官方那種行為：拆錯字碼按空白鍵後，輸入的字碼會自動清空，不用再手動按退格。

## v/r/s/f 快速選字（純邏輯改動，不碰字碼表，可自由分享）

`references/liur_Trad.dict.yaml` 轉出來的字碼表（含 `ixv` 這類消歧義碼）雖然解決了選字問題，但那份表是嘸蝦米有版權碼表的衍生物，不能自由散佈。改成完全放在 **`python\input_methods\cheliu\cheliu_ime.py`**（只有蝦米自己的檔案，完全不碰共用的 `cinbase`），用按鍵層級的技巧模擬出「字碼表裡真的有 `ixv` 對應到『曳』」的體感，但完全不用改字碼表：

**最終行為（v3）：** 候選字視窗開著、沒按 Ctrl/Shift 時，`v/r/s/f` 對應候選字清單裡第 2~5 個項目。按下去會：
1. 把這個字母併進 `compositionChar`／`compositionString`（例如 `ix` 按 `v` 會變成組字區顯示「ＩＸＶ」，視覺上就像真的多打了一碼）
2. 候選字清單直接窄化成**只剩使用者選的那一個字**（例如只剩「曳」）
3. 但**不直接送出**——composition 保持在「已選定、等待確認」的狀態，跟輸入其它任何字一樣，要按空白鍵或 Enter 才會真正上字

這樣使用者的體感跟「字碼表裡本來就有 `ixv → 曳`」幾乎一樣：打 `ixv`、看到只剩曳可選、按空白上字，但實際上 `liu.cin`/`liu.json` 完全沒有 `ixv` 這個字碼，全部是 `cheliu_ime.py` 用按鍵攔截跟畫面顯示模擬出來的。

如果選字後改變主意按了別的鍵（不是空白/Enter，例如想退格重打），會先把 `compositionChar`／`compositionString`／候選字清單完整還原回按 v/r/s/f **之前**的狀態，再讓那個按鍵照正常邏輯繼續處理（例如退格就會在「ix」狀態下正常刪掉一個字根）。

**這個做法的好處，也是這次特地選它而不是直接改 `cinbase/__init__.py` 的原因：**`cinbase` 是給所有 cin 系輸入法（`checj`、`chedayi`...等）共用繼承的基底，改那邊即使包成設定開關，仍然是共用檔案的異動；改 `cheliu_ime.py` 則完全物理隔離在蝦米自己的模組裡，其它輸入法的程式碼一行都沒動到，不需要額外的 config 開關就能保證不互相影響。

已用真實的 `cinbase` 引擎 + 真實 `liu.json` 資料驗證過：打 `ix`（候選字 `我/曳`）按 `v` → 組字區變成「ＩＸＶ」、候選字窄化成只剩「曳」→ 按空白鍵正確送出「曳」；選字後改按退格 → 正確還原回「ix」狀態（候選字回到 `我/曳`）再正常刪字。`abi`（5 個候選字）按 `s` 一樣正常運作。

**已還原成原廠字碼表：** `liu.cin`/`liu.json` 已換回原廠版本（`maxCharLength` 也還原成 `4`）。RIME 轉換版（`liu.cin.rime-derived`／`liu.json.rime-derived`）、原始的 `references\liur_Trad.dict.yaml` 都已經從磁碟上整個刪除，不再保留任何 RIME 衍生資料。整包（程式邏輯 + 原廠字碼表）現在可以自由分享，不牽涉版權問題。

**踩到的坑 1：v/r/s/f 本身也是合法的蝦米字根字母，不能無條件轉譯成選字鍵。** 上線後發現「現」(`kmr`)、「剛」(`nber`) 這種碼尾剛好是 `v/r/s/f` 的字打不出來——因為打完 `km`（候選字視窗開啟）之後接著打 `r` 想組成 `kmr`，卻被直接攔截去選第 3 個候選字了。修法是在轉譯前多判斷一步：**只有「目前組字 + 這個字母」不可能再是任何更長合法碼的字首時，才當作選字鍵**；否則就讓它正常繼續組字。

判斷用的 `_has_prefix(chardefs, prefix)`（`any(key.startswith(prefix) for key in chardefs)`）是 `cheliu_ime.py` 裡的模組層級函式，直接吃 `self.cin.chardefs`（`Cin` 類別本來就公開的一般 dict 屬性）——一開始是寫成 `cinbase\cin.py` 的 `Cin.hasPrefix()` 方法，後來發現完全不需要碰 `cinbase`，改成現在這樣純粹在 `cheliu_ime.py` 裡操作公開屬性即可，`cinbase` 因此完全恢復原廠狀態。呼叫方式是 `if ch in QUICK_SELECT_KEYS and not _has_prefix(self.cin.chardefs, self.compositionChar + ch):`。已用原廠字碼表資料驗證：`_has_prefix(chardefs, 'kmr')`／`_has_prefix(chardefs, 'nber')` 都是 `True`（正確判斷「還有更長的碼」不轉譯），`_has_prefix(chardefs, 'abiv'/'abir'/'abis'/'abif')` 都是 `False`（原本能選字的案例不受影響）。

**踩到的坑 2：一開始把 v/r/s/f 轉譯成數字選字鍵直接丟給 cinbase，會導致按下 v/r/s/f 當下就立刻上字**，跟這套輸入法「打完字要按空白鍵才上字」的一貫節奏不一致，會讓使用者覺得意外（`config.json` 的 `directCommitString` 其實是死設定，`cinbase` 完全沒讀，實際上字靠的是空白/Enter 觸發 `cinbase` 裡的送出邏輯）。改成「按 v/r/s/f 時記下 `self.pendingQuickSelectChar`，之後按空白/Enter 才由 `cheliu_ime.py` 自己呼叫 `self.cinbase.setOutputString(...)` 送出」解決了自動上字的問題。

**踩到的坑 3：光是把候選字清單重新排序（讓選到的字排最前面）不夠，空白鍵送出的還是原本第一個候選字。** 原因是 **`cinbase` 每次 `onKeyDown` 只要 `compositionChar` 沒變，就會直接從字碼表重新算一份全新的候選清單**（`cinbase/__init__.py` 裡 `candidates = cbTS.cin.getCharDef(cbTS.compositionChar)`，在 `elif cbTS.cin.isInCharDef(cbTS.compositionChar) and ...:` 這個條件下每個按鍵都會重跑），我們排好的順序在下一次呼叫 `cinbase.onKeyDown` 時就會被蓋掉、回到原本順序。這是實際測試時才發現的坑，只靠重新排序完全解決不了，必須讓空白/Enter 這個確認鍵也完全繞過 `cinbase`、自己處理才行——這也是為什麼最終版乾脆把 `compositionChar` 一起延伸（變成「ix」+「v」=「ixv」），讓 `cinbase` 完全不會再去重新計算這個（不存在的）字碼的候選字，衝突自然就不存在了。

**踩到的坑 4：按 v/r/s/f 之後候選字視窗直接消失，不是顯示窄化後的單一候選字。** 根本原因是 `python\textService.py` 的 `TextService.handleRequest()` 把每次按鍵的回覆設計成「這次改了什麼」的**增量封包**：`self.currentReply` 在每次處理完一個按鍵之後就會被清空(`handleRequest` 最後 `reply = self.currentReply; self.currentReply = {}`)，所以某個按鍵的回覆封包裡**只會包含這次按鍵過程中真的呼叫過 `setXxx()` 的欄位**，不會自動帶入前一個按鍵設定過的值。我們在 v/r/s/f 分支裡只呼叫了 `setCandidateList()`/`setCandidateCursor()`，沒有在同一次回覆裡重新呼叫 `setShowCandidates(True)`，導致這次的回覆封包裡根本沒有 `showCandidates` 這個欄位，前端收不到「候選字視窗要繼續開著」的訊號。修法是在 v/r/s/f 分支裡明確補上 `self.setShowCandidates(True)`。

這個坑也暴露了先前測試方式的盲點：mock 測試時我是用自己寫的 lambda 取代 `setCandidateList`/`setCandidateCursor` 等方法來記錄呼叫記錄，檢查的是「程式內部狀態值對不對」（`compositionString`/`candidateList` 這些值确實是對的），但沒有檢查「實際送給客戶端的回覆封包裡有哪些欄位」——這正是問題所在，內部狀態正確不代表送出的封包完整。之後驗證要直接用繼承來的真正 `TextService.setXxx()` 方法（不要用自己的 lambda 蓋掉），並且每次按鍵前重置 `self.currentReply = {}`（模擬 `handleRequest` 的行為），再檢查 `self.currentReply` 這個實際回覆封包的完整內容，才能真正抓到這類「內部狀態對、但送出的封包缺欄位」的問題。

## 蝦米反查拼音功能（按 `` ` `` 反查拼音，用 libchewing 標注蝦米碼，支援詞）

在 `ix` 空白鍵/多功能前導字元系統基礎上疊加的新功能：composition 是空的時候按 `` ` ``（進入既有的「多功能前導字元」模式），接著打一般字母（非 `m`/`u`/`e`，那三個已經被 `` `M ``/`` `U ``/`` `E `` 用掉）會進入拼音反查模式，內部建立一個獨立的 `ChewingContext`（`python\libchewing\libchewing.py` 包的 `chewing.dll`），把打的字母當漢語拼音（`KBType=9`）餵給它。

**操作方式（v2，支援詞，取代最初只能查單一字的版本）：**
- 可以連續打多個音節組成詞，例如 `fang3fu2`：libchewing 會用內建詞庫自動「回頭修正」，打完 `fang3` 先猜「訪」，接著打 `fu2` 會自動把整串修正成「彷彿」，跟真的在用新酷音打字的行為一樣。
- 打字過程中**不會主動彈出候選字清單**（拿掉了 v1 版本「音節打完就自動展開候選字」的做法，因為那樣會讓使用者沒辦法連續打完整個詞）。想看某個字的其它候選字，自己按 **方向鍵 ↓**（對應 `ctx.handle_Down()`），跟真正的新酷音操作一致，可以在打詞的過程中隨時挑選/修正某個字。
- 按 **Enter** 才是真正確定：把目前 buffer 內容（可能一個字、也可能一整個詞）送出，並且把裡面**每一個字**的蝦米碼都列出來，而不是只查最後一個字。
- Backspace 統一直接呼叫 `ctx.handle_Backspace()`，一次刪一個字（`彷彿`→`訪`→空），空了才會退出反查模式；不用分「候選清單開著」跟「一般輸入中」兩種狀態處理。

**架構：跟 v/r/s/f 一樣，完全只放在 `python\input_methods\cheliu\cheliu_ime.py`，`cinbase` 一行都沒改。** 這個功能原本是直接寫在 `cinbase/__init__.py` 共用引擎裡（連同一個 `pinyinReverseLookup` config 開關才能避免影響其它 cin 系輸入法），後來發現其實不需要碰 `cinbase`：`cheliu_ime.py` 裡的 `self` 跟 `cinbase` 方法收到的 `cbTS` 參數本來就是同一個物件，`self.compositionChar`、`self.multifunctionmode`、`self.showCandidates`、`self.cin` 這些狀態，還有 `TextService` 基底類別給的 `setCommitString`/`setCandidateList`/`showMessage` 等輸出方法，`cheliu_ime.py` 全部都能直接讀寫，不需要透過 `cinbase` 的程式碼。

實際做法：
- 觸發判斷完全在 `cheliu_ime.py` 自己的 `onKeyDown` 裡做：`self.multifunctionmode and self.compositionChar == '`'`（也就是 cinbase 既有、完全沒改過的多功能前導字元狀態）加上這個鍵是非 m/u/e 的字母，符合就攔截、**不呼叫** `self.cinbase.onKeyDown(...)`，自己接手處理。
- `self.pinyinLookupMode` 為 `True` 時，`onKeyDown` 一開始就直接呼叫 `self.handlePinyinLookupKey(keyEvent)`，同樣完全不進 `cinbase`。
- 送出結果時呼叫（不是修改）`self.cinbase.setOutputString(self, RCinTable, commitStr)` 沿用既有的簡繁轉換等共用邏輯，字碼提示訊息則自己直接組字串設定 `self.onKeyUpMessage`（逐字呼叫 `self.cin.getCharEncode(ch)`，這個方法本來就存在於 `cinbase\cin.py`，沒有為了這個功能新增或修改）。
- 候選字標注用的「最短字碼」改成 `cheliu_ime.py` 裡的模組層級函式 `_shortest_key_for_char(chardefs, ch)`，直接吃 `self.cin.chardefs`，原本在 `cinbase\cin.py` 加的 `getShortestKey()` 已經拿掉。
- `self.cinbase.isLetterChar(keyCode)`／`self.cinbase.resetComposition(self)` 這些是**呼叫**既有、未修改的 `cinbase` 方法（單純重用，不是修改），跟直接把邏輯寫進 `cinbase` 是兩回事。

**最終狀態：`cinbase\__init__.py`、`cinbase\config.py` 完全恢復原狀，`cheliu\config\config.json` 也拿掉 `pinyinReverseLookup` 欄位**（功能變成蝦米固定內建行為，不再需要開關，因為已經沒有「共用檔案異動需要 config 開關擋住其它輸入法」這個顧慮了）。已用真正的 `CheLiuTextService` 類別（不是 mock 出來的假物件）完整跑過一輪：`` ` ``→進入多功能前導字元→打 `n` 觸發反查拼音模式→打 `ni3`→按 ↓ 看候選字→選字→按 Enter 確定並正確列出字碼，過程中一般打字（`ix`）跟 v/r/s/f 快速選字都不受影響。

**實作時發現的 libchewing 行為細節（規劃階段沒查得到，是實際呼叫 DLL 才發現的）：**
- `ChewingContext(syspath=..., userpath=...)` 的 `userpath` 必須是**檔案路徑**（例如 `.../chewing.sqlite3`），不是資料夾路徑；傳資料夾會讓 `chewing_new2` 回傳 NULL context（`ctx.ctx == 0`），後續所有查詢都會安靜地回傳 `-1`，沒有任何例外或錯誤訊息。
- `set_maxChiSymbolLen(n)` 決定最多能組成幾個字的詞（目前設 10）；設成 1 的話每打完一個音節就會被強迫立刻結束，沒辦法連續打成詞。
- 打完一個完整拼音音節（含聲調數字）後，libchewing 會直接把最常用的字自動填進 `buffer`（`cand_TotalChoice()` 還是 0），要看其它候選字必須自己呼叫 `handle_Down()`。
- `handle_Enter()` 只有在「沒有候選字清單開著、也沒有打到一半的音節」時才會真的觸發 `commit_Check()`；候選字清單還開著、或音節還沒打完聲調就按 Enter，libchewing 會直接忽略，狀態不變（不會誤觸發、不需要額外防呆）。
- **候選字清單開著的時候一定要先呼叫 `ctx.cand_close()`，才能呼叫 `clean_bopomofo_buf()`/`clean_preedit_buf()` 清空重來**；如果候選清單還開著就直接清緩衝區、接著打新的音節，libchewing 會把新按的字母誤判成是在對「舊的」候選清單按選字鍵，導致打出跟預期完全無關的字（實測過：候選清單開著時清緩衝區不呼叫 `cand_close()`，接著打 `ma3` 卻打出「擬」──那其實是前一次 `ni3` 候選清單裡的字）。這個問題只發生在「context 重複使用」時（`initPinyinChewingContext`／`resetPinyinLookupMode` 裡都已經加上 `cand_close()`），一般正常的 `handle_Backspace()` 不會有這個副作用。
- `chewing_new`/`chewing_new2` 這類回傳指標的函式在 `libchewing.py` 裡沒有設定 `restype`，實測在 32-bit 直譯器下沒有造成數值錯誤（回傳的整數就是實際的 handle 值），但這是沒有明確保證的行為，日後若換 64-bit 直譯器要重新確認。
