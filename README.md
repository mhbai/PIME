# PIME 蝦米輸入法自訂版

[![License: LGPL 2.1](https://img.shields.io/badge/License-LGPL%202.1-blue.svg)](./LICENSE)

這是 [PIME](https://github.com/EasyIME/PIME)（Windows 中文輸入法框架，版本 `1.3.0-stable`）的客製化版本，針對內建的「蝦米」（Boshiamy／`cheliu`）輸入法新增了幾個功能。所有改動都是**純程式邏輯**，沒有修改任何有版權的字碼表資料，可以自由分享。

這個 repo 只追蹤真正改過的檔案：`python\input_methods\cheliu\` 底下的蝦米模組本身，以及這份文件跟四支輔助腳本。PIME 安裝目錄底下其它所有東西——共用引擎 `cinbase\`、`python\libchewing\`、`python\opencc\`、「新酷音」模組（`python\input_methods\chewing\`）、核心管線程式（`server.py`、`textService.py`、`backends.json` 等）——全部沒有任何改動，跟官方安裝出來的版本一模一樣，所以都刻意不放進這個 repo。所有新功能需要用到的資料查詢（例如判斷某個字碼是不是更長字碼的字首、查詢拼音候選字）都是在 `cheliu_ime.py` 裡直接操作 `cinbase`／`libchewing` 本來就公開的屬性與 API 完成，不需要改動這些共用模組本身。

## 新增功能

### 1. v/r/s/f 快速選字

模仿正式版嘸蝦米的選字鍵。候選字視窗開啟時：

- `v` `r` `s` `f` 分別對應候選字清單裡的第 2、3、4、5 個字
- 按下去畫面上會把這個字母併入組字區（例如打 `ix` 出現候選字「我／曳」後按 `v`，組字區會顯示「ＩＸＶ」），候選字清單也會窄化成只剩選到的那一個字
- 跟輸入其它任何字一樣，還是要按**空白鍵或 Enter** 才會真正上字，不會一按 v/r/s/f 就自動送出
- 如果按錯想重來，按退格會完整還原回選字前的狀態

體感上就像字碼表裡真的有「ixv → 曳」這筆字碼，但實際上字碼表完全沒有改動。

### 2. 反查拼音（按 `` `h `` 查字/查詞）

忘記某個字的蝦米字碼時，可以暫時切換成拼音輸入：

1. 組字區是空的狀態下按 `` ` `` 再按 `h`（`h` 代表「漢語」拼音，固定用這個按鍵序列進入，不管接下來拼音開頭是哪個字母都一樣，包含 `m`/`u`/`e`/`h` 本身——那三個字母單獨接在 `` ` `` 後面仍然是既有的多功能前導字元功能，分別對應設定選單／Unicode 輸入／emoji 選單，不受影響）
2. 打漢語拼音（含聲調數字，例如 `ni3`），可以連續打多個音節組成詞（例如 `fang3fu2` 會自動修正成「彷彿」）
3. 按 **↓** 展開候選字清單，每個候選字後面會標注它在蝦米字碼表裡最短的字碼；按 **←/→** 可以移動游標回頭修正不是最後一個字的地方（但只有該位置剛好有收錄替代詞彙時才有用——如果游標移過去按 ↓ 候選字沒有變化，改用退格刪掉後面已經打好的字，剩下想修正的那個字時按 ↓ 選好之後，再重新打一次後面的音節接上去，這個方法永遠有效）
4. 候選字清單開啟時按 **Esc** 只會先關閉清單、不會離開反查拼音狀態（跟真正的新酷音操作一致）；清單已經關閉時再按一次 Esc 才會真正離開
5. 按 **Enter** 確定送出，並且會列出剛剛送出的字（或詞）裡每一個字的完整蝦米碼，這個提示訊息會持續顯示，直到按下任意一個鍵才會消失

底層是內嵌一份獨立的 [libchewing](https://github.com/chewing/libchewing) 引擎（`chewing.dll`）來查詢拼音候選字，跟系統裡有沒有安裝「新酷音」這個輸入法無關。這份使用說明也內建在輸入法的設定視窗裡（語言列選單→蝦米設定→使用說明頁籤）。

### 3. 拆錯字碼自動清除

打一串查無此字的字碼（例如 `LLLL`）按空白鍵後，畫面上的錯誤字碼會直接清空，不用再手動按退格——這是啟用了 PIME 原本就有、但預設關閉的 `autoClearCompositionChar`設定。

### 4. 輔助腳本

- `register-pime.bat` — 停止舊的後端行程、重啟 `PIMELauncher.exe`、註冊 PIME（安靜模式，不會跳出視窗要求手動按確定）
- `unregister-pime.bat` — 停止後端行程、取消註冊 PIME（同樣是安靜模式）
- `restart-pime-backend.bat` — **只**重啟後端行程，不會呼叫 `regsvr32`、不會動到 TSF/COM 註冊。平常改完程式碼或設定檔要測試，用這支，不要用 `register`/`unregister-pime.bat`——重複 `regsvr32` 註冊/取消註冊，實測會讓 Windows 把目前選定的輸入法切換掉（例如切成 PIME 自己，把你原本選的其它輸入法擠掉），這是 Windows 本身的行為，跟這個 repo 的程式邏輯無關，但 `register`/`unregister-pime.bat` 不需要常態性地重複執行就能避開。
- `update-pime.bat` — 參見下面「更新既有安裝」一節

全部都需要「以系統管理員身分執行」。

---

## 安裝到新電腦

這個 repo 只有我們自己改過的 Python 原始碼，**不包含** PIME 本身的執行檔、DLL、Python 直譯器（這些是編譯好的二進位檔，體積大又跟版權無關的部分不放進 git）。所以要在新電腦上使用，需要「先裝官方版，再用 git 疊上我們的改動」：

### 步驟 1：安裝官方 PIME

到官方 Release 頁面下載 **`1.3.0-stable`** 版本的安裝檔（版本要跟這個 repo 對齊）：

https://github.com/EasyIME/PIME/releases

以系統管理員身分執行安裝程式，安裝到預設路徑 `C:\Program Files (x86)\PIME`。元件勾選時**至少要勾選「蝦米」**——「新酷音」勾不勾都可以，不影響本專案的任何功能（反查拼音用的 `libchewing` 引擎只要有裝任一個 Python 輸入法就會一併安裝，跟新酷音這個輸入法選項本身無關）。

### 步驟 2：用 git 疊上這個 repo 的改動

以系統管理員身分開啟 PowerShell 或終端機：

```powershell
cd "C:\Program Files (x86)\PIME"
git init
git remote add origin https://github.com/mhbai/PIME.git
git fetch origin
git reset --hard origin/master
```

`git reset --hard` 只會覆蓋這個 repo 裡有追蹤的檔案（蝦米的程式碼、字碼表、這幾支輔助腳本等），完全不會動到官方安裝程式裝進去、repo 裡沒有追蹤的檔案（`PIMELauncher.exe`、DLL、Python 直譯器）。

### 步驟 3：確認 libchewing 有裝進來

```
C:\Program Files (x86)\PIME\python\libchewing\chewing.dll
```

這個檔案要存在，反查拼音功能才會動。如果沒有，把這個資料夾從其它已經裝好的機器複製過去即可。

### 步驟 4：註冊啟用

對 `register-pime.bat` 按右鍵「以系統管理員身分執行」。

### 步驟 5：測試

切換到蝦米輸入法，確認：
- 一般打字正常（例如打 `ix` 出現「我／曳」）
- 按 `v`/`r`/`s`/`f` 快速選字，按空白鍵才上字
- 按 `` `h `` + 拼音可以反查，按 ←/→ 能移動游標、Esc 是兩段式（先關候選字清單，再按一次才離開）
- 打錯字碼按空白鍵會自動清除

---

## 更新既有安裝

已經照上面裝好的機器，之後要更新到最新版時，對 `update-pime.bat` 按右鍵「以系統管理員身分執行」即可，會自動依序做：`git fetch` → `git reset --hard origin/master` → 重啟後端（`restart-pime-backend.bat`）。如果這個 repo 有本機沒 commit 的改動，腳本會先中止並提示，不會默默蓋掉。

也可以手動執行同樣的步驟：

```powershell
cd "C:\Program Files (x86)\PIME"
git fetch origin
git reset --hard origin/master
```

更新完一定要重啟後端行程（跑 `restart-pime-backend.bat`），改動才會生效——PIME 的後端一旦啟動就會持續常駐，不會自動重載新的程式碼。更新程式碼不需要重新 `regsvr32`，所以不要用 `register`/`unregister-pime.bat`，那兩支留給真的要安裝/解除安裝時用（見上面「輔助腳本」一節說明原因）。

---

更詳細的技術細節、踩過的坑、跟 `cinbase` 共用引擎之間的取捨，記錄在 [`CLAUDE.md`](./CLAUDE.md)。

## 授權

本專案採用 [LGPL 2.1](./LICENSE)，跟 `cheliu_ime.py` 檔頭原本就有的授權聲明一致（沿用自它衍生自的原始 PIME 原始碼）。
