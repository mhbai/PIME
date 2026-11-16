#! python3
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301  USA

from keycodes import *  # for VK_XXX constants
from textService import *
import io
import os.path
import copy

from cinbase import CinBase
from cinbase import LoadCinTable
from cinbase import LoadRCinTable
from cinbase import LoadHCinTable
from cinbase.config import CinBaseConfig
from libchewing import ChewingContext, CHEWING_DATA_DIR, CHINESE_MODE, HALFSHAPE_MODE

# 候選字視窗開啟時，v/r/s/f 對應候選字清單中第 2~5 個項目的索引值 (0-based)。
# 模仿正式版嘸蝦米的選字鍵，但不直接送出——只是把該候選字換到清單最前面(索引0)，
# 跟其它字一樣仍要按空白鍵才會真正上字，才不會讓使用者感覺「怎麼沒按空白就跳出去了」。
QUICK_SELECT_KEYS = {'v': 1, 'r': 2, 's': 3, 'f': 4}

# 反查拼音功能觸發鍵：` 之後接 h (代表「漢語」拼音)。固定用這一個字母，不管接下來
# 實際要打的拼音開頭是什麼字母 (含 m/u/e，也含 h 本身，例如「好」hao3)，統一只有這
# 一種進入方式，不會跟 cinbase 既有的 `M/`U/`E 功能衝突，規則也比較單純好記。
PINYIN_LOOKUP_TRIGGER_KEY = 'h'

# 反查拼音送出後的字碼提示訊息：改成「按下任一鍵才消失」而不是計時器到期就自動關閉
# (見 onKeyUp/onKeyDown)。這裡先用一個夠長的秒數把訊息撐著，真正的關閉是靠下一次
# onKeyDown 主動呼叫 hideMessage()，這個數字本身沒有意義，純粹是「夠長不會自動到期」。
PINYIN_CODE_MESSAGE_DURATION = 60


def _shortest_key_for_char(chardefs, ch):
    return min((key for key, value in chardefs.items() if ch in value), key=len)


def _has_prefix(chardefs, prefix):
    return any(key.startswith(prefix) for key in chardefs)


class CheLiuTextService(TextService):

    compositionChar = ''

    def __init__(self, client):
        TextService.__init__(self, client)

        # 輸入法模組自訂區域
        self.imeDirName = "cheliu"
        self.maxCharLength = 4 # 輸入法最大編碼字元數量
        self.cinFileList = ["liu.json"]

        self.cinbase = CinBase
        self.curdir = os.path.abspath(os.path.dirname(__file__))

        # 反查拼音 (輸入拼音以內嵌的 libchewing 引擎查詢候選字，並標注蝦米碼)
        self.pinyinLookupMode = False
        self.pinyinLookupArmed = False
        self.pinyinChewingContext = None
        self.pinyinCandidates = []
        self.pinyinDisplayCandidates = []
        self.pinyinCodeMessage = ""
        self.pinyinCodeMessagePending = False
        self.pinyinCodeMessageShowing = False

        # v/r/s/f 快速選字：記住使用者選了哪個字，等按空白/Enter 才真正送出。
        # 另外記住選字前的組字狀態，這樣如果使用者中途按別的鍵 (例如退格) 取消，
        # 才能完整還原，讓那個按鍵可以正常交給 cinbase 繼續處理。
        self.pendingQuickSelectChar = None
        self.pendingQuickSelectOriginalCompositionChar = ''
        self.pendingQuickSelectOriginalCompositionString = ''
        self.pendingQuickSelectOriginalCandidateList = []

        # 初始化輸入行為設定
        self.cinbase.initTextService(self, TextService)

        # 載入用戶設定值
        CinBaseConfig.__init__()
        self.configVersion = CinBaseConfig.getVersion()
        self.cfg = copy.deepcopy(CinBaseConfig)
        self.cfg.imeDirName = self.imeDirName
        self.cfg.cinFileList = self.cinFileList
        self.cfg.load()
        self.jsondir = self.cfg.getJsonDir()
        self.cindir = self.cfg.getCinDir()
        self.ignorePrivateUseArea = self.cfg.ignorePrivateUseArea
        self.cinbase.initCinBaseContext(self)

        # 載入輸入法碼表
        if not CinTable.curCinType == self.cfg.selCinType and not CinTable.loading:
            loadCinFile = LoadCinTable(self, CinTable)
            loadCinFile.start()
        else:
            while CinTable.loading:
                continue
            self.cin = CinTable.cin


    # 檢查設定檔是否有被更改，是否需要套用新設定
    def checkConfigChange(self):
        self.cinbase.checkConfigChange(self, CinTable, RCinTable, HCinTable)


    # 輸入法被使用者啟用
    def onActivate(self):
        TextService.onActivate(self)
        self.cinbase.onActivate(self)


    # 使用者離開輸入法
    def onDeactivate(self):
        TextService.onDeactivate(self)
        self.cinbase.onDeactivate(self)
        # 釋放反查拼音用的 libchewing context
        self.pinyinLookupMode = False
        self.pinyinLookupArmed = False
        self.pinyinChewingContext = None
        self.pinyinCodeMessagePending = False
        self.pinyinCodeMessageShowing = False
        self.pendingQuickSelectChar = None


    # 使用者按下按鍵，在 app 收到前先過濾那些鍵是輸入法需要的。
    # return True，系統會呼叫 onKeyDown() 進一步處理這個按鍵
    # return False，表示我們不需要這個鍵，系統會原封不動把按鍵傳給應用程式
    def filterKeyDown(self, keyEvent):
        KeyState = self.cinbase.filterKeyDown(self, keyEvent, CinTable, RCinTable, HCinTable)
        return KeyState


    def onKeyDown(self, keyEvent):
        # 反查拼音送出後的字碼提示訊息：按下任一鍵就先關掉訊息(這個鍵本身還是照正常
        # 邏輯繼續處理，不會被吃掉)，達到「按任意鍵才消失」的體感，而不是等
        # messageDurationTime 計時器到期才消失。
        if self.pinyinCodeMessageShowing:
            self.pinyinCodeMessageShowing = False
            self.isShowMessage = False
            self.hideMessage()

        # 反查拼音模式中：按鍵完全不交給 cinbase，全部交給內嵌的 libchewing 引擎處理
        if self.pinyinLookupMode:
            return self.handlePinyinLookupKey(keyEvent)

        # v/r/s/f 選字後，正等待使用者按空白/Enter 確認送出 (見下方 QUICK_SELECT_KEYS
        # 分支)。這裡一定要自己接手，不能借用 cinbase 原本的空白/Enter 送出邏輯，因為
        # cinbase 每次按鍵都會依照 compositionChar 重新從字碼表算出候選字清單、蓋掉我們
        # 排好的顯示內容，所以沒辦法讓 cinbase 送出「使用者選的那個」，只能自己直接送出。
        if self.pendingQuickSelectChar is not None:
            if (keyEvent.keyCode in (VK_SPACE, VK_RETURN)
                    and not keyEvent.isKeyDown(VK_CONTROL) and not keyEvent.isKeyDown(VK_SHIFT)):
                commitStr = self.pendingQuickSelectChar
                self.pendingQuickSelectChar = None
                self.cinbase.setOutputString(self, RCinTable, commitStr)
                self.cinbase.resetComposition(self)
                return True
            else:
                # 使用者改變主意，繼續打別的鍵 (例如退格想修改組字內容)：把組字狀態還原
                # 成按 v/r/s/f 之前的樣子，再讓這個按鍵照正常邏輯往下處理
                self.pendingQuickSelectChar = None
                self.compositionChar = self.pendingQuickSelectOriginalCompositionChar
                self.setCompositionString(self.pendingQuickSelectOriginalCompositionString)
                self.setCandidateList(self.pendingQuickSelectOriginalCandidateList)
                self.setCandidateCursor(0)

        # 反查拼音的進入點：`（cinbase 既有的多功能前導字元模式）之後接 h。這個按鍵
        # 組合在 cinbase 原本的邏輯裡完全沒有處理 (打了也不會有反應)，所以在這裡攔截、
        # 自己接手，不會影響 `M/`U/`E 原本的功能，也完全不需要修改 cinbase。
        # h 本身只是進入反查拼音模式的標記鍵，不會被當成拼音的一部分餵給 libchewing，
        # 所以不管接下來真正要打的拼音開頭是什麼字母(含 m/u/e，也含 h 本身，例如
        # 「好」hao3)都適用，不用像之前那樣為了閃開 `M/`U/`E 另外搞一套按鍵序列。
        # h 鍵本身先「武裝」反查拼音模式，不馬上進入(因為這個按鍵不是拼音字母，沒東西
        # 可以餵給 libchewing)；真正進入要等下一個按鍵。
        #
        # 這裡絕對不能把 compositionString 設成空字串：目前 compositionBufferMode
        # 是 False，setCompositionString() 寫的就是 TSF 當下真正在編輯中的那個
        # composition，不是獨立的內部緩衝區。真正的 TSF 用戶端(不是我們這個離線
        # mock 測試用的假 client)看到 composition 變空字串，會直接把這個 composition
        # session 結束掉，進而呼叫回我們的 onCompositionTerminated(forced=True)，
        # 把 pinyinLookupArmed 重設回 False——結果就是「按了 `h，前導功能卻直接結束，
        # 沒有進入反查拼音模式」，因為武裝旗標在下一個按鍵送到之前就已經被清掉了。
        # 改成顯示 "`H" 當作武裝中的提示文字，composition 全程都不會變空，就不會
        # 觸發這個問題。
        if (self.multifunctionmode and self.compositionChar == '`'
                and keyEvent.isPrintableChar() and self.cinbase.isLetterChar(keyEvent.keyCode)
                and chr(keyEvent.charCode).lower() == PINYIN_LOOKUP_TRIGGER_KEY):
            self.multifunctionmode = False
            self.compositionChar = ''
            self.setCompositionString('`H')
            self.pinyinLookupArmed = True
            return True

        # 武裝後的下一個按鍵：當作反查拼音的第一個字母餵給 libchewing (不管是不是
        # m/u/e/h，這時候已經脫離 cinbase 的多功能前導字元狀態，不會再跟 `M/`U/`E
        # 衝突)。如果這個按鍵不是字母(例如使用者按錯又按了 Esc/退格)，就明確完整重置
        # composition 並吃掉這個按鍵，等同取消整個反查拼音流程，回到完全空白的狀態
        # (不要只是靜悄悄地解除武裝、讓按鍵照一般邏輯處理——那樣 compositionChar 會是
        # ''、但 compositionString 還殘留著上面設的 "`H"，兩邊對不起來，容易留下顯示
        # 卡住的殘影)。
        if self.pinyinLookupArmed:
            self.pinyinLookupArmed = False
            if keyEvent.isPrintableChar() and self.cinbase.isLetterChar(keyEvent.keyCode):
                self.pinyinLookupMode = True
                self.initPinyinChewingContext()
                return self.handlePinyinLookupKey(keyEvent)
            self.cinbase.resetComposition(self)
            return True

        # 候選字視窗開著、沒按 Ctrl/Shift 的情況下，按 v/r/s/f 選候選字清單裡第 2~5 個
        # 項目。為了讓使用者感覺就像字碼表裡真的有「ix + v = ixv 對應曳」這樣的字碼，
        # 把這個字母併進 compositionChar/compositionString (視覺上跟真的多打一碼一樣)，
        # 候選字清單也直接窄化成只剩使用者選的那一個字——但**不直接送出**，仍然要按
        # 空白鍵/Enter 才會真正上字，跟輸入其它字的節奏一致，不會有「打完 v 就自動上
        # 字」的意外感。
        #
        # v/r/s/f 本身也是合法的蝦米字根字母，所以只有在「接下來這個字母不可能再組成
        # 更長的合法碼」時才當作選字鍵；否則就讓它正常繼續組字，避免擋到像「現(kmr)」
        # 「剛(nber)」這種碼尾剛好是 v/r/s/f 的字。
        if (self.showCandidates and keyEvent.isPrintableChar()
                and not keyEvent.isKeyDown(VK_CONTROL) and not keyEvent.isKeyDown(VK_SHIFT)):
            ch = chr(keyEvent.charCode).lower()
            if ch in QUICK_SELECT_KEYS and not _has_prefix(self.cin.chardefs, self.compositionChar + ch):
                idx = QUICK_SELECT_KEYS[ch]
                if idx < len(self.candidateList):
                    self.pendingQuickSelectChar = self.candidateList[idx]
                    self.pendingQuickSelectOriginalCompositionChar = self.compositionChar
                    self.pendingQuickSelectOriginalCompositionString = self.compositionString
                    self.pendingQuickSelectOriginalCandidateList = list(self.candidateList)

                    self.compositionChar += ch
                    self.setCompositionString(self.compositionString + self.cin.getKeyName(ch))
                    self.setCandidateList([self.pendingQuickSelectChar])
                    self.setCandidateCursor(0)
                    # 每次按鍵的回覆都是「這次改了什麼」的增量封包 (TextService.handleRequest
                    # 每次處理完就會清空 currentReply)，一定要在同一次回覆裡重新宣告
                    # showCandidates=True，候選字視窗才會用新的清單繼續顯示，不然客戶端
                    # 收不到「視窗要保持開啟」的訊號，畫面上會變成候選字視窗直接消失。
                    self.setShowCandidates(True)
                return True

        KeyState = self.cinbase.onKeyDown(self, keyEvent, CinTable, RCinTable, HCinTable)
        return KeyState


    # 建立/重用反查拼音用的 libchewing context (延遲建立，僅第一次進入反查模式時建立
    # 一次，之後在同一次啟用期間重複使用，直到 onDeactivate 才釋放，避免每次進入反查
    # 都重載辭典)
    def initPinyinChewingContext(self):
        if self.pinyinChewingContext is None:
            userdir = os.path.join(self.cfg.getConfigDir(), "pinyin_userphrase")
            os.makedirs(userdir, mode=0o700, exist_ok=True)
            syspath = ";".join((userdir, CHEWING_DATA_DIR)).encode("UTF-8")
            userpath = os.path.join(userdir, "chewing.sqlite3").encode("UTF-8")
            ctx = ChewingContext(syspath=syspath, userpath=userpath)
            ctx.set_maxChiSymbolLen(10)  # 最多可組成 10 字的詞，讓 libchewing 的詞庫回頭修正發揮作用
            ctx.set_KBType(9)  # 漢語拼音，索引值來自 chewing 設定頁 keyboardNames 陣列
            ctx.set_selKeys(self.selKeys)
            ctx.set_candPerPage(self.candPerPage)
            ctx.set_ChiEngMode(CHINESE_MODE)
            ctx.set_ShapeMode(HALFSHAPE_MODE)
            self.pinyinChewingContext = ctx
        else:
            # 一定要先關掉候選字清單再清緩衝區，不然候選字清單若還開著，下次打字會被
            # libchewing 誤判成是在對舊的候選清單按選字鍵，而不是重新輸入新的音節
            self.pinyinChewingContext.cand_close()
            self.pinyinChewingContext.clean_bopomofo_buf()
            self.pinyinChewingContext.clean_preedit_buf()


    # 反查拼音模式下的按鍵處理，全部交給內嵌的 libchewing 引擎判斷。
    # 打字時可以連續輸入多個音節組成詞 (libchewing 會用詞庫自動回頭修正，例如打完
    # fang3 先猜「訪」，接著打 fu2 會自動修正成「彷彿」)；按方向鍵 ↓ 可以展開候選字清單
    # 挑選/比對其它字的蝦米碼。方向鍵 ←/→ 移動游標到詞裡的其它字(呼叫 ctx.handle_Left()/
    # handle_Right())，不會主動彈出候選字清單，等游標移到想改的那個字再按 ↓ 才會展開該
    # 字的候選字清單——這樣才能修正「訪彿」裡的「訪」(不是最後一個字)，不是只能改最後
    # 一個字。按 Enter 才會真正確定，把目前 buffer 內容(可能一個字、可能一個詞)送出，
    # 並列出裡面每一個字的蝦米碼。
    #
    # 候選字清單「已經展開」時，上下左右鍵改成移動清單裡的選字游標，不再是上面那段
    # 說的「移動詞裡的游標」——這兩者只有其中一種情境會用到，不會衝突：清單沒開時是
    # 移動詞的游標，清單開了就是選字，見 movePinyinCandidateCursor()。這是因為實測
    # 發現 libchewing 原生對這幾個鍵、在候選字清單開著時的行為完全不是「選字」：
    # handle_Left()/handle_Right() 會直接整頁翻頁(而且頭尾相接、會循環)，handle_Up()
    # 會直接把整個候選字清單關掉，handle_Down() 清單已開啟時則什麼都不會發生——沒有
    # 一個是「移動醒目提示到清單裡的下一/上一個字」。所以改成完全不呼叫這幾個
    # libchewing 方法來處理清單內的游標移動，自己在 Python 這層維護
    # self.candidateCursor，真的要換頁時才呼叫 handle_Left()/handle_Right()(這兩個
    # 已經實測確認在清單開啟時就是換頁，不是移動詞的游標)。
    def handlePinyinLookupKey(self, keyEvent):
        ctx = self.pinyinChewingContext
        keyCode = keyEvent.keyCode
        charCode = keyEvent.charCode
        candidateOpen = ctx.cand_TotalChoice() > 0

        if candidateOpen and keyCode in (VK_UP, VK_DOWN, VK_LEFT, VK_RIGHT):
            self.movePinyinCandidateCursor(ctx, keyCode)
            return True

        if candidateOpen and keyCode == VK_RETURN:
            # 清單開著時 Enter 是「選定目前游標所在的候選字」，不是送出整個組字區
            # (送出整個組字區是下面 elif keyCode == VK_RETURN 那一支，只有在清單已經
            # 關閉時才會走到)。選字方式跟真正的新酷音一致：把游標位置對應的選字鍵
            # 字元，當成使用者直接按下那個數字鍵，餵給 libchewing 自己判斷選字
            # (已實測確認 ctx.handle_Default(ord(selKey)) 會正確選字、關閉清單、
            # 更新 buffer，不需要額外處理)。
            selKey = self.selKeys[self.candidateCursor]
            ctx.handle_Default(ord(selKey))
        elif keyCode == VK_ESCAPE:
            # 跟真正的新酷音一致：候選字清單開著的時候，第一次按 Esc 只關掉清單，
            # 還留在反查拼音狀態；要等候選字清單已經關閉的狀態下再按一次 Esc，才會
            # 真正離開反查拼音模式。libchewing 自己的 ctx.handle_Esc() 只會關閉候選字
            # 清單，不會清掉 buffer(就算候選字清單早就是關的，重複呼叫也一樣不會清空)，
            # 所以「第二次才整個離開」這個行為要我們自己判斷、自己決定，不能指望
            # libchewing 內建就有這個兩階段邏輯。
            if ctx.cand_TotalChoice() > 0:
                ctx.handle_Esc()
            else:
                self.resetPinyinLookupMode()
                self.cinbase.resetComposition(self)
                return True
        elif keyCode == VK_BACK:
            ctx.handle_Backspace()
            if not ctx.buffer_Check() and not ctx.bopomofo_Check() and ctx.cand_TotalChoice() == 0:
                self.resetPinyinLookupMode()
                self.cinbase.resetComposition(self)
                return True
        elif keyCode == VK_DOWN:
            ctx.handle_Down()
        elif keyCode == VK_LEFT:
            ctx.handle_Left()
        elif keyCode == VK_RIGHT:
            ctx.handle_Right()
        elif keyCode == VK_RETURN:
            ctx.handle_Enter()
            if ctx.commit_Check():
                commitStr = ctx.commit_String().decode("UTF-8")
                self.cinbase.setOutputString(self, RCinTable, commitStr)
                if not self.client.isUiLess:
                    # commitStr 可能是一個字、也可能是反查拼音打出來的一個詞，逐字列出蝦米碼。
                    # 訊息內容/顯示時機不用 cinbase 既有的 onKeyUpMessage(那個是固定
                    # messageDurationTime 秒後自動消失)，改成自己在 onKeyUp 顯示、在下一次
                    # onKeyDown 按任意鍵時主動關閉，見 onKeyUp/onKeyDown。仍然要設
                    # showMessageOnKeyUp=True，純粹是因為 cinbase.filterKeyUp() 只有在這個
                    # 旗標(或其它幾個既有旗標)為真時才會讓 onKeyUp() 真的被呼叫到；
                    # onKeyUpMessage 留空，避免 cinbase.onKeyUp() 自己也跳出來顯示一次。
                    self.pinyinCodeMessage = "　".join(self.cin.getCharEncode(ch) for ch in commitStr)
                    self.pinyinCodeMessagePending = True
                    self.showMessageOnKeyUp = True
                self.resetPinyinLookupMode()
                self.cinbase.resetComposition(self)
                return True
        else:
            ctx.handle_Default(charCode)

        if ctx.cand_TotalChoice() > 0:
            self.updatePinyinCandidateList(ctx)
        else:
            self.pinyinCandidates = []
            self.pinyinDisplayCandidates = []
            self.setShowCandidates(False)
            self.setCandidateList([])

        compStr = ctx.buffer_String().decode("UTF-8") if ctx.buffer_Check() else ""
        # +1 是因為畫面上的 compositionString 永遠多一個開頭的 "`"，但
        # ctx.cursor_Current()/bopomofoStr 的長度都是相對於 compStr 本身算的，不含這個前綴。
        if ctx.bopomofo_Check():
            bopomofoStr = ctx.bopomofo_String(None).decode("UTF-8")
            pos = ctx.cursor_Current()
            compStr = compStr[:pos] + bopomofoStr + compStr[pos:]
            self.setCompositionCursor(pos + len(bopomofoStr) + 1)
        else:
            self.setCompositionCursor(ctx.cursor_Current() + 1)
        self.setCompositionString("`" + compStr)

        return True


    # 候選字清單開啟時，上下左右鍵移動選字游標(self.candidateCursor，TextService 既有
    # 屬性)，而不是交給 libchewing 原生的 handle_Up()/handle_Down()/handle_Left()/
    # handle_Right() 處理。實測這四個方法在候選字清單已開啟時的行為：handle_Left()/
    # handle_Right() 是直接整頁翻頁(頭尾相接、會循環，例如最後一頁按右鍵會繞回第一
    # 頁)，handle_Up() 是直接把整個候選字清單關掉，handle_Down() 則完全沒有效果——
    # 沒有一個在做「移動醒目提示到清單裡的上一/下一個字」，所以兩段式選字(游標移動
    # +確認)要自己在這裡做：清單裡還有上一個/下一個字就直接移動游標；已經是清單這
    # 一頁的第一個/最後一個字，才呼叫 handle_Left()/handle_Right() 換頁(這兩個已經
    # 實測確認在清單開啟時就是換頁，不是移動詞的游標)，換頁後游標落在新的一頁的最後
    # 一個(往左/上換頁時)或第一個(往右/下換頁時)，跟 cinbase 自己選單系統的左右鍵
    # 換頁邏輯一致。上下鍵跟左右鍵用同一套規則，沒有另外做成「以列為單位」跳動，因為
    # 反查拼音的候選字清單在畫面上就是單純一直排下去的清單，不是像設定選單那樣的
    # 多欄網格。
    def movePinyinCandidateCursor(self, ctx, keyCode):
        candCursor = self.candidateCursor
        candCount = len(self.pinyinDisplayCandidates)
        forward = keyCode in (VK_DOWN, VK_RIGHT)

        if forward:
            if candCursor + 1 < candCount:
                candCursor += 1
            else:
                ctx.handle_Right()
                self.updatePinyinCandidateList(ctx)
                return
        else:
            if candCursor > 0:
                candCursor -= 1
            else:
                ctx.handle_Left()
                self.updatePinyinCandidateList(ctx)
                self.setCandidateCursor(len(self.pinyinDisplayCandidates) - 1)
                return

        self.setCandidateCursor(candCursor)
        # 候選字清單回覆封包是逐鍵增量的，這次按鍵沒有重新宣告 showCandidates 的話，
        # 清單會直接從畫面上消失(跟 v/r/s/f 快速選字踩過的坑一樣)。
        self.setShowCandidates(True)


    # 重建候選字清單，並標注目前字碼表的蝦米碼 (候選字視窗只能顯示單一字串，沒有另外
    # 的註解欄位，所以直接把字碼併進顯示字串；實際上字仍用 pinyinCandidates 裡的原始
    # 字元，不會把標註文字一起打出去)
    def updatePinyinCandidateList(self, ctx):
        self.pinyinCandidates = []
        self.pinyinDisplayCandidates = []
        ctx.cand_Enumerate()
        for i in range(ctx.cand_ChoicePerPage()):
            if not ctx.cand_hasNext():
                break
            char = ctx.cand_String().decode("UTF-8")
            self.pinyinCandidates.append(char)
            if self.cin.isHaveKey(char):
                code = _shortest_key_for_char(self.cin.chardefs, char)
                self.pinyinDisplayCandidates.append(char + "　" + code)
            else:
                self.pinyinDisplayCandidates.append(char)
        self.setCandidateList(self.pinyinDisplayCandidates)
        self.setCandidateCursor(0)
        self.setCandidatePage(0)
        self.setShowCandidates(True)


    # 重置反查拼音模式 (不釋放 pinyinChewingContext 物件本身，那個只在 onDeactivate 時釋放)
    def resetPinyinLookupMode(self):
        self.pinyinLookupMode = False
        self.pinyinCandidates = []
        self.pinyinDisplayCandidates = []
        if self.pinyinChewingContext is not None:
            self.pinyinChewingContext.cand_close()
            self.pinyinChewingContext.clean_bopomofo_buf()
            self.pinyinChewingContext.clean_preedit_buf()


    # 使用者放開按鍵，在 app 收到前先過濾那些鍵是輸入法需要的。
    # return True，系統會呼叫 onKeyUp() 進一步處理這個按鍵
    # return False，表示我們不需要這個鍵，系統會原封不動把按鍵傳給應用程式
    def filterKeyUp(self, keyEvent):
        KeyState = self.cinbase.filterKeyUp(self, keyEvent)
        return KeyState


    def onKeyUp(self, keyEvent):
        # 反查拼音送出後的字碼提示訊息：用一個很長的 duration 撐著，實際的關閉時機交給
        # onKeyDown 在下一次按鍵時主動呼叫 hideMessage()，不是靠這裡的計時器到期。
        # 顯示完要把 showMessageOnKeyUp 清掉(onKeyUpMessage 本來就是空字串)，不然接下來
        # 呼叫的 cinbase.onKeyUp() 會看到這個旗標還是 True，自己也跳出來重複處理一次。
        if self.pinyinCodeMessagePending:
            self.pinyinCodeMessagePending = False
            self.showMessageOnKeyUp = False
            self.isShowMessage = True
            self.showMessage(self.pinyinCodeMessage, PINYIN_CODE_MESSAGE_DURATION)
            self.pinyinCodeMessageShowing = True
        self.cinbase.onKeyUp(self, keyEvent)


    def onPreservedKey(self, guid):
        KeyState = self.cinbase.onPreservedKey(self, guid)
        return KeyState


    def onCommand(self, commandId, commandType):
        self.cinbase.onCommand(self, commandId, commandType)


    # 開啟語言列按鈕選單
    def onMenu(self, buttonId):
        MenuItems = self.cinbase.onMenu(self, buttonId)
        return MenuItems


    # 鍵盤開啟/關閉時會被呼叫 (在 Windows 10 Ctrl+Space 時)
    def onKeyboardStatusChanged(self, opened):
        TextService.onKeyboardStatusChanged(self, opened)
        self.cinbase.onKeyboardStatusChanged(self, opened)


    # 當中文編輯結束時會被呼叫。若中文編輯不是正常結束，而是因為使用者
    # 切換到其他應用程式或其他原因，導致我們的輸入法被強制關閉，此時
    # forced 參數會是 True，在這種狀況下，要清除一些 buffer
    def onCompositionTerminated(self, forced):
        TextService.onCompositionTerminated(self, forced)
        if self.pinyinLookupMode:
            self.resetPinyinLookupMode()
        self.pinyinLookupArmed = False
        self.pendingQuickSelectChar = None
        self.cinbase.onCompositionTerminated(self, forced)


    # 設定候選字頁數
    def setCandidatePage(self, page):
        self.currentCandPage = page


class CinTable:
    loading = False
    def __init__(self):
        self.cin = None
        self.curCinType = None
        self.userExtendTable = None
        self.priorityExtendTable = None
        self.ignorePrivateUseArea = None
CinTable = CinTable()


class RCinTable:
    loading = False
    def __init__(self):
        self.cin = None
        self.curCinType = None
RCinTable = RCinTable()


class HCinTable:
    loading = False
    def __init__(self):
        self.cin = None
        self.curCinType = None
HCinTable = HCinTable()
