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

# 反查拼音功能觸發鍵：` 之後接的字母 (m/u/e 已經被既有的 `M/`U/`E 功能用掉)
PINYIN_LOOKUP_EXCLUDED_KEYS = ('m', 'u', 'e')

# 反查拼音送出後的字碼提示訊息：改成「按下任一鍵才消失」而不是計時器到期就自動關閉
# (見 onKeyUp/onKeyDown)。這裡先用一個很長的秒數把訊息撐著，真正的關閉是靠下一次
# onKeyDown 主動呼叫 hideMessage()，這個數字本身沒有意義，純粹是「夠長不會自動到期」。
PINYIN_CODE_MESSAGE_DURATION = 86400


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

        # 反查拼音的進入點：`（cinbase 既有的多功能前導字元模式）之後接一般字母
        # (非 m/u/e，那三個已經被 `M/`U/`E 用掉)。這個按鍵組合在 cinbase 原本的邏輯裡
        # 完全沒有處理 (打了也不會有反應)，所以在這裡攔截、自己接手，不會影響
        # `M/`U/`E 原本的功能，也完全不需要修改 cinbase。
        if (self.multifunctionmode and self.compositionChar == '`'
                and keyEvent.isPrintableChar() and self.cinbase.isLetterChar(keyEvent.keyCode)
                and chr(keyEvent.charCode).lower() not in PINYIN_LOOKUP_EXCLUDED_KEYS):
            self.multifunctionmode = False
            self.compositionChar = ''
            self.setCompositionString('')
            self.pinyinLookupMode = True
            self.initPinyinChewingContext()
            return self.handlePinyinLookupKey(keyEvent)

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
    # 挑選/比對其它字的蝦米碼；按 Enter 才會真正確定，把目前 buffer 內容(可能一個字、
    # 可能一個詞)送出，並列出裡面每一個字的蝦米碼。
    def handlePinyinLookupKey(self, keyEvent):
        ctx = self.pinyinChewingContext
        keyCode = keyEvent.keyCode
        charCode = keyEvent.charCode

        if keyCode == VK_ESCAPE:
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
        if ctx.bopomofo_Check():
            bopomofoStr = ctx.bopomofo_String(None).decode("UTF-8")
            pos = ctx.cursor_Current()
            compStr = compStr[:pos] + bopomofoStr + compStr[pos:]
        self.setCompositionString("`" + compStr)

        return True


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
