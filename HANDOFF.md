# 交接文件 — 臘腸狗桌寵 v0.3 → v0.4

> 開新對話時說：「照 桌面\dachshund-pet\HANDOFF.md 繼續做 v0.4」。Claude 會連上電腦直接改資料夾，不用傳 zip。
>
> **現況（2026-10-19）**：v0.3（待辦清單、狗搬清單、每天起床、番茄鐘、Settings、圓角泡泡）程式寫完，假 PySide6 測試全過，**還沒在 Evan 的 Windows 上實測**。下一個對話先處理 Evan 的實測回報（見「v0.3 要請 Evan 確認的」），再開始 v0.4。

## 專案目標（截止：2026-10-19 週一晚上）
Windows 桌寵臘腸狗：
1. 互動：摸頭、揉肚子、拎起來、亂跑（zoomies）、叼走滑鼠
2. 每日提醒：每天 08:00 起床，從螢幕邊緣把 to-do 清單拖出來
3. 雙人訊息：手機 PWA ↔ Firebase ↔ 桌寵頭上冒對話泡泡（用配對碼綁定兩人）
4. 動畫：Claude 畫草圖，Evan 畫正式圖替換
5. 額外功能：睡覺打呼、番茄鐘、餵零食
6. 開放別人下載：GitHub Releases ＋ GitHub Actions 自動打包 .exe

## 已定案的決定（答題卡）
| 項目 | 決定 |
|---|---|
| 系統 | Windows |
| 技術 | Python + PySide6 |
| 手機端 | PWA |
| 美術 | Evan 畫正式圖；Claude 照 Evan 的參考圖做草圖（頭紅、身體藍、腿黃、尾巴綠） |
| 大小 | 嘴巴約等於游標大小 → 預設 sprite 160px，可在設定改 `scale` |
| 名字 | 使用者第一次開啟時自己取 |
| 額外功能 | 睡覺打呼、番茄鐘、餵零食 |
| 叼滑鼠 | 偶爾隨機惡作劇（設定可關 `mouse_prank`） |
| 每日提醒 | 08:00 起床並檢查待辦 |
| 發佈 | GitHub repo + Releases（讓別人下載） |
| 方向 | 8 方向，畫 5 個方向，其餘鏡像 |
| 視角 | 3/4 斜俯視（俯角 30°） |
| 走動頻率 | 設定可調（安靜 / 普通 / 過動） |
| 滑鼠穿透 | 要：透明處點得到後面的東西 |

## v0.1 做了什麼
- `pet/dog_model.py`：純 Python 的 3D 管狀狗模型 → 投影成 8 方向草圖（不依賴 Qt，Qt 和 Pillow 共用）
- `pet/sprites.py`：讀 `assets/` 的正式圖，缺的自動用草圖；左邊方向和正面動作自動鏡像
- `pet/pet_window.py`：透明置頂不搶焦點的視窗，狀態機 `idle / walk / sit / sleep / held / drop / happy`
  - 自由亂逛：隨機目標點，偶爾跨螢幕
  - 點一下 = 摸摸（愛心）；拖曳 = 拎起（身體變長、影子變小），放開會掉下來彈一下
  - 太久沒互動會睡覺
- `pet/app.py`：右鍵選單、系統匣（點圖示 = 叫牠過來）、取名對話框、活潑程度
- `pet/settings.py`：`%APPDATA%\DachshundPet\settings.json`
- `tools/export_sketches.py`：輸出草圖 PNG 和總表給 Evan 描圖

## v0.1.1 方便性小補丁
- `pet/convenience.py`：單一實例（QLocalServer，再開一次 = 叫狗過來）、全域快捷鍵 Ctrl+Alt+D（RegisterHotKey + native event filter）、開機自動啟動（HKCU Run 登錄機碼）、建立桌面捷徑（PowerShell WScript.Shell，用 pythonw 啟動不跳終端機）
- `main.py`：未處理的例外寫進 `%APPDATA%\DachshundPet\error.log`
- requirements 改成 `PySide6-Essentials`（完整版 PySide6 太大，安裝很慢）
- 專案在 Evan 筆電的位置：**`C:\Users\user\Downloads\dachshund-pet-v0.1.1\dachshund-pet`**（桌面捷徑「超豬」和開機自動啟動都指向這裡，以後只改這份）。`Downloads\dachshund-pet-v0.1\dachshund-pet` 是舊的重複副本，內容同步到 v0.1.4，可刪。對話連上他的電腦後，Claude 直接把更新寫進資料夾（先用 device_request_folder_access 要權限），不用再傳 zip
- Evan 的環境：Windows、Python 3.14（PyManager 安裝在 AppData\Local\Python\pythoncore-3.14-64）、PySide6 6.12.0，v0.1 已在他電腦上跑起來

## v0.1.2 影子
- `pet/shadow.py`：從每個動作的圖片自動算影子（多格疊加 → 去掉上方 35%（尾巴、耳朵）→ PCA 算中心、方向、長寬 → 最低點貼腳底）。不依賴 Qt
- `pet/sprites.py`：載入時算好每個動作/方向的影子，左邊方向鏡像；`SpriteLibrary.shadow()` 給 pet_window 用。Evan 換圖後影子會自動跟著變
- Evan 已經畫好第一版正式動畫（82 格，黃色臘腸狗 `#E7C374`），預覽頁：https://claude.ai/artifact/RGCLHDktUdQ4EmtqctByxb。還沒放進 assets/；已給他修改建議（背面要有尾巴、正面太小、跑步要伸展收縮、腳底對齊 64%、眉毛用 `#A8702E`）

## v0.1.3 拎起來
- held 動畫：先顯示第 1 格 0.25 秒，之後停在最後一格（不循環），放下掉落時維持最後一格
- 游標抓住每一格的「脖子」：`assets/held/grab.json` 存每格脖子位置（比例），Evan 的圖是 `[[0.52, 0.47], [0.50, 0.40]]`；沒有這個檔就用草圖預設 (0.5, 0.16)
- 影子改成對準腳：下包絡線找出踩地的腳，中心放在最前和最後一隻腳中間，底部貼腳底

## v0.1.4 換成 Evan 的正式圖
- `assets/` 已放入 Evan 的 84 格（有眉毛版本）：walk/run 各 5 方向 × 6 格、idle 4、sit 4、sleep 2、held 2、happy 6、belly 6，每格 320×320、腳底在 64%
- 切圖方式：從 Evan 的整張 sheet（1640×2360，格距 147.6px、第一欄中心 x=640.5）按列遮罩後裁切
- `assets/held/grab.json` = `[[0.55, 0.20], [0.58, 0.17]]`（Evan 用預覽頁點選的，頭後面那塊肉）
- 影子：躺著的動作（belly、sleep）用 lying 模式貼身體
- 圖示：每次啟動都用 idle 第 1 格（裁掉透明邊）重寫 `%APPDATA%\DachshundPet\icon.ico`，系統匣和桌面捷徑都用它
- `run.bat` 會依序找 pythonw → pyw → py；`main.py` 連 PySide6 載入失敗都會寫 error.log
- Claude 透過 computer use 在 Evan 電腦上啟動過，但截圖抓不到透明置頂視窗，實際畫面要靠 Evan 回報

## 已知限制 / 待確認
- 雲端環境裝不到 PySide6，Claude 這邊只能做語法檢查；實際行為都要靠 Evan 在 Windows 上測試回報。v0.1.1 的快捷鍵和捷徑功能尚待確認。
- 透明處讓滑鼠穿透依賴 Qt 在 Windows 上的 layered window 行為，需要實測確認。
- 已有動作：walk、run、idle、sit、sleep、held、happy、belly（run 和 belly 已經畫好，但還沒接上互動）。

## v0.2 互動（2026-10-18 完成，排程任務自動做的，Evan 沒填答題卡）
Evan 說「全部授權」，所以答題卡用預設：**A~D 全做、叼滑鼠「很少（約 30 分鐘一次）」、先用系統字型**（`assets/fonts/` 已建好，放字型檔就會自動用）。沒有新增任何動畫。
- `pet/mood.py`：心情 / 親密度（純 Python）。摸頭 +4、揉肚爽到 +8、戳 +1、玩完 zoomies/被丟好玩 +2、叼滑鼠 +3；亂晃 −10（親密度 −1）；5 分鐘沒互動每分鐘 −1（最低 30）。每 60 秒、離開時存進 settings.json（`mood`、`affection`）
- `pet/fonts.py`：載入 `assets/fonts/` 第一個字型，`app.setFont` 套用到整個程式
- `pet/pet_window.py` 新狀態：`belly`（揉肚子，anim_speed 跟著揉的量）、`hop`（嚇一跳＝held 第 1 格跳起；打噴嚏＝idle 小跳）、`fly`/`slide`（丟出去，拋物線、撞螢幕邊/頂反彈、落地用 belly 第 1 格滑行）、`dizzy`（sit + 程式畫的星星，結束後 8 秒走路歪）、`chase`/`nose`（跑來聞游標）、`prank_go`/`prank_carry`（叼滑鼠，QCursor.setPos 接在嘴巴，游標被拉開 >40px 或點狗就鬆口，最多 5 秒）、`zoomies`、`spin`（walk 8 方向輪播）、`sniff`
- 摸頭改成「滑鼠停在狗身上並輕晃 0.5 秒」（像素判斷，透明處不算）；單擊改成戳一下（等雙擊間隔才觸發）；雙擊 = 翻肚 / 翻回來
- 名牌：滑鼠停在狗身上顯示「名字 😊 心情 80 / ♥ 親密度 30」，取代原本的 tooltip
- 右鍵選單：新增「Belly rub」「一起玩 → 暴衝 / 追尾巴 / 聞聞地板 / 來追我 / 叼走滑鼠」；選單標題顯示心情；「Mouse-stealing prank」頻率（關掉 / 很少 / 偶爾 / 只在我按選單時），設定鍵 `mouse_prank` + `prank_freq`
- `SpriteLibrary.frame_at()`：固定拿某一格
- 可調參數都在 `pet_window.py` 最上面：`THROW_SPEED`、`SWIPE_SPEED`、`SHAKE_REVERSALS`、`PET_HOVER_SEC`、`MOUTH`（嘴巴位置，照 Evan 的圖量的）、`PRANK_MEAN_SEC`
- 測試：雲端裝不到 PySide6，Claude 用假的 PySide6 模組跑過狀態機模擬（自動行為、摸頭、揉肚子、戳、亂晃→頭暈、丟出去、掃過嚇到、zoomies、追尾巴、聞地板、追游標、叼滑鼠、存檔都有跑到），**實際畫面和手感要 Evan 在 Windows 上測**

### v0.2 要請 Evan 確認的
1. 摸頭靈不靈敏（`PET_HOVER_SEC`）、名牌字會不會太小
2. 丟出去要甩多用力（`THROW_SPEED`）、亂晃要甩幾下才頭暈（`SHAKE_REVERSALS`）
3. 叼滑鼠時游標有沒有對準嘴巴（`MOUTH`）、會不會太煩
4. 頭暈星星、頭上冒的字位置對不對
5. 字型檔（有的話放 `assets/fonts/`）

## v0.2.1 照 Evan 的答題卡修剪（2026-10-19）
Evan 後來填了答題卡：**A 摸頭、揉肚子、戳一下；B 追游標、叼滑鼠；C Zoomies；不要 D 心情系統；叼滑鼠「偶爾（約 10 分鐘）」；字型想用自己手寫的英數字 PNG 轉**。他沒時間畫新動畫（本來就不需要）。
- 沒勾的 7 項（`dizzy` 亂晃頭暈、`throw` 丟出去、`look` 看著游標、`swipe` 被掃過嚇到、`spin` 追尾巴、`sniff` 聞地板、`mood` 心情系統）**程式碼保留、預設關閉**，右鍵「More interactions」可勾。清單在 `settings.EXTRAS`，存在 settings.json 的 `extras`，`Settings.extra(key)` / `set_extra()`；`PetWindow.feat(key)` 檢查
- 心情關掉時：`Mood.enabled=False`（change 什麼都不做、不會冷落掉分），行為機率用固定心情 0.7 / 親密度 0.3，名牌只顯示名字
- `Settings.migrate()`：`settings_version` < 2 → `prank_freq` 改 `sometimes`、`mouse_prank` 開。預設值也改成 `sometimes`
- `convenience.repair_launch_paths()`：每次啟動在背景檢查，開機啟動指令不對就重寫；桌面上 Arguments/WorkingDirectory 含 `dachshund-pet` 但不是現在資料夾的 .lnk 全部改指向現在這份（含圖示）。**捷徑壞掉時要先手動雙擊 `run.bat` 開一次才會修**
- 字型：已完成 `assets/fonts/EvanHand.ttf`（家族名 EvanHand，72 字：A–Z a–z 0–9 `!?.,:-'"()` + 空白）。Evan 把大小寫寫在同一格（「Aa」），a–z 格空著，所以程式自動左右切開。產生器 `tools/build_font.py`（四角黑方塊透視校正 → 濾導線 → 切格 → 各字貼基線 → 骨架化後統一加粗半徑 6px → 描邊 → fontTools；cap 700 units、5 units/px）。`fonts.py` 改用 `setFamilies([EvanHand, 系統字, Microsoft JhengHei UI, Segoe UI Emoji])`，中文和 emoji 自動 fallback。粗體是 Qt 模擬的
- **介面全部改英文**（Evan 要求，讓選單也用他的手寫字）：右鍵選單、系統匣選單、通知、取名對話框、頭上冒的字、名牌、預設名字 `Dachshund`。`app._style_menu()` 讓選單用 app 字型並放大 1.3 倍（有自訂字型時）。手寫字型沒有的字元（`+ ~ / ♥ …` 和中文）會 fallback 系統字型，所以新增文字盡量只用英數字和 `!?.,:-'"()`。程式註解仍是中文
- 圖示：`assets/icon.png` 存在就用它（系統匣、桌面捷徑、icon.ico），沒有就用 idle 第 1 格。Evan 已畫好狗頭（吐舌頭），Claude 去背後放進 `assets/icon.png`（512×512），已生效
- 語法檢查和 settings/mood 單元測試過了；畫面要 Evan 測

## 狗圖去白邊（2026-10-19）
- Evan 發現狗在深色背景上外框外面有一圈白點（當初從白底整張圖切出來的殘留）。`tools/defringe.py`：只看透明區旁 3px 內、白／灰色（低彩度、亮）的像素，改成外框深色 `(24,18,12)`、保留透明度；黃色身體和粉紅舌頭不受影響。84 格全部處理過，原圖備份在 `assets_original/`（已加進 .gitignore）。重跑是安全的（第二次修正 0 個像素）。Evan 之後換新圖時可以再跑 `py tools/defringe.py`
- 外部去背網站（remove.bg 等）工作環境連不到，也不需要

## 手動調影子（2026-10-19）
- Evan 覺得有些動作的影子還是歪的。Shadow Picker 工具頁：https://claude.ai/artifact/GdkUuJFoZWxyXtSjhpc35N（15 個動作：idle、sit、happy、sleep、belly、walk/run × right、down_right、down、up_right、up；held 不用調）。拖曳影子中心、滑桿調長度 a、寬度 b、角度，起始值是 `shadow.py` 自動算的；自動存到該 artifact 的 db：collection `shadows`、doc `current`，欄位 `shadows`（{key: [cx, cy, a, b, angle]}，sprite 邊長比例）和 `edited`（他改過哪些）
- Evan 說調好後：用 ArtifactData get 讀 `shadows/current`，把 `shadows` 寫成 `assets/shadows.json`。`sprites.py` 已會讀這個檔（`_load_shadows`），有寫的動作用手動值，沒寫的照舊自動算，往左方向自動鏡像
- **已完成**：Evan 調好 15 個（全部改過），已寫成 `assets/shadows.json`（2026-10-19 14:49 版本）。以後他再調，同樣讀 db 再覆寫這個檔
- **丟出去掉到螢幕下面的 bug（已修）**：原因是放手時只有「輕放」會把落地點夾回螢幕可用範圍，「丟出去」沒有，所以在工作列附近甩出去會落在工作列下面。新增 `_settle_airborne()`：放手時和 drop / fly / slide 每一幀都把落地點夾在 `availableGeometry` 內，落地點往上移多少就從離地高度扣多少（畫面不跳）；往上夾時加回高度

## v0.3 規格（2026-10-19 定案，已實作 → 見下一節「v0.3 實作」）

**Demo（互動示意，HTML，不是正式程式）**：https://claude.ai/artifact/SApCYrxkxk28GWEKiCWigP
新對話可以用 Artifact 工具 `action: "read"` 讀它的原始碼當參考（動畫時序、座標都在裡面）。正式版要用 PySide6 在 Windows 上做出一樣的效果。

### Evan 的答案（答題卡）
| 項目 | 決定 |
|---|---|
| 清單從哪邊拉出 | **螢幕右邊** |
| 打勾的項目隔天 | **自動清掉**（換日時刪掉 done 的項目） |
| 每天固定出現的事項（daily） | **不要**（demo 裡的 Drink water daily 標籤拿掉） |
| 開機時已經過了設定時間 | **當天第一次開就拉出來**（記錄 `last_pull_date`，同一天只自動拉一次） |
| 時間到的提醒 | **番茄搖 + 狗跳 + 「叮」音效**（不要 Windows 通知） |
| 時間格式 | **24 小時制**，不要 AM/PM |
| 對話泡泡 | **原本的圓角泡泡**（Evan 手繪泡泡試過，不要） |
| 介面語言 | 英文、用 EvanHand 字型 |

### 1. 待辦清單（新檔 `pet/todo.py` 資料 + `pet/todo_window.py` 視窗）
- 資料：`%APPDATA%\DachshundPet\todo.json`，`{"date": "YYYY-MM-DD", "items": [{"text": "...", "done": false}]}`；載入時如果 date 不是今天 → 刪掉 done 的項目、date 改今天（自動清掉）
- 視窗：獨立的透明、置頂、無邊框 QWidget（不搶焦點，但輸入框要能打字 → 點輸入框時才 activate）。**筆記本紙**：米白底 `#FFFDF6`、藍色橫線 `#BFD6F2`、左邊紅色邊線 `#EBA2A2`、深色外框 2px、左上左下圓角、右邊貼著螢幕邊沒有框、陰影 -4,4
- **所有文字坐在橫線上**：每列高度 = 一行 `lh`；標題列 2 行高，「Today」和日期（例如 `Mon 10/19`）的 baseline 貼第 2 條線；EvanHand 的 baseline 在字框底往上 0.24em（line-height 1 時），要往下補回
- 每一項：手繪感方框 checkbox（打勾是紅色 `#E2553B` 勾）、文字（打勾後刪除線、變灰）；點整列切換；最下面一列「Add a task...」虛線底線輸入框 + 「Add」按鈕；項目可刪（右鍵或滑過出現 ×，Claude 自己決定，跟 Evan 說）
- 位置：螢幕可用範圍的**右邊**，**底部貼齊狗走路的地面線**（= 狗的 ground 範圍底），寬約 300px（跟著狗 scale）
- **紅色標籤**（`#E2553B`、深色框、左側圓角）：在清單左邊，**高度剛好在狗嘴巴**（地面往上 0.22×S，S = 狗 sprite 邊長）。清單收著時清單整個移到螢幕外，只有標籤露在螢幕右邊緣（約 16×26px）
- 打勾時狗開心跳 + 冒愛心 + 隨機 "Nice!" / "One down!" / "Woof!"；全部做完 "All done! Good job!"
- 番茄鐘進行中打勾，狗保持安靜

### 2. 狗搬清單的動畫（`pet_window.py` 新狀態）
量的是 Evan 的 run/right 圖（面向右）：**鼻子**在腳底點往前 0.40、往上 0.25（×S）；**咬的點**往前 0.37、往上 0.22
- **拉出來**（清單收著時點標籤，或早上到時間）：狗用 run 跑到「嘴巴對準螢幕邊標籤」的位置 → 換 run 第 2 格停住（頭往前）冒 "Grr!" 0.65 秒 → 面向右、run 倒著播（7fps）往左**分 4 下猛扯**（每下 55% 時間快拉（ease-out cubic）+ 45% 停頓），總共約 2.2 秒；**清單左邊緣永遠 = 狗嘴 x + 標籤寬/2** → 拉完放開、往後退 0.3×S（0.45 秒）→ sit + "Here you go!"（早上那次是 "Your list for today!"）
- **推回去**（清單開著時點標籤）：狗跑到「鼻子貼著清單左邊緣」→ 停 0.3 秒 → run 正著播（7fps）慢慢往右 1.8 秒，**清單左邊緣 = 狗鼻子 x** → 清單完全收進去（標籤留在螢幕邊）→ 狗往後退 0.38×S → "See you later!"
- **疊放順序：狗在清單上面**（Evan 要求，嘴和鼻子蓋住紙邊）。狗視窗 raise 在清單視窗之上；狗本來就用像素判斷點擊（透明處穿透），所以不會擋到標籤
- **搬清單期間（含早上整段）點狗不會打斷**，只冒愛心（`busy` 旗標）；搬清單時不能開始番茄鐘；狗如果在別的狀態（睡覺、亂逛）被叫去搬，先打斷那個狀態
- 多螢幕：清單在狗所在螢幕（或主螢幕）的右邊

### 3. 每天起床
- 設定 `wake_time`（預設 `"08:00"`，已在 settings.py DEFAULTS）。每分鐘檢查：到時間且今天還沒拉過 → 如果狗在睡覺先醒來冒 `"08:00! Good morning!"`（用設定的時間）→ 拉出清單 → "Your list for today!"
- 開機（程式啟動）時已經過了設定時間、且今天還沒拉過 → 也拉一次
- 記錄 `last_pull_date` 在 settings.json

### 4. 番茄鐘（新檔 `pet/pomodoro.py` + 畫在狗旁邊）
- 右鍵選單「Pomodoro」→ Start / Stop；設定 `focus_min`（預設 25）、`break_min`（預設 5）
- **廚房番茄計時器**：俯視番茄 `assets/pomodoro/tomato.png` + 葉子蒂頭 `assets/pomodoro/leaf.png`（Evan 畫的，兩張 512×512、同一個中心點，葉子最長那片朝上＝指針）。顯示大小約 0.62×S，**放在狗右邊地上**（底部貼地面）；狗走過去坐在番茄左邊（sit）
- **不畫刻度、不畫淺色扇形**（Evan 要求）：只有番茄本體 + 葉子繞中心旋轉，開始時 360°，隨剩餘時間轉回 0°（角度 = 360 × 剩餘/總長）
- 剩餘時間 `MM:SS` 用 EvanHand 顯示在番茄上方的小牌子（米白底、深框、圓角）；休息時字是綠色 `#5A9A3C` 加 "break"
- 專心期間：狗安靜坐著，**不亂跑、不叼滑鼠、不 zoomies**，點狗冒 "Shh... focusing"
- 時間到：**番茄左右搖晃**（±9°、0.14 秒來回 8 次）+ 狗 happy 跳 + 愛心 + "Ding! Break time!" + **「叮」音效**（用 `QSoundEffect` 播一個 wav；沒有音檔就程式合成一個短的 ding 存到 `assets/sounds/ding.wav`）→ 自動開始休息倒數 → 休息結束再叮一聲 + "Back to work?"，然後停（不自動開始下一輪）
- 收起番茄：停止或結束後番茄消失

### 5. Settings 視窗（右鍵「Settings...」，新檔 `pet/settings_dialog.py`）
- EvanHand 字型、米白紙風格。欄位：**Pull out my list at** = 兩個下拉選單：小時 00–23、分鐘 00–55（每 5 分）；**Work time** = 1–120 分鐘；**Break time** = 1–60 分鐘
- 「更多互動」那些開關可以搬進來或留在右鍵選單（Claude 決定）

### 6. 對話泡泡
- 維持現在的圓角泡泡（白底、深色外框 2px、圓角 14px、底下小三角、EvanHand）。泡泡靠近螢幕邊時往內移，不要超出螢幕

### 7. 其他已完成、不用再做的
- 狗頭圖示 `assets/icon.png`（已生效）、去白邊（`tools/defringe.py`）、手調影子（`assets/shadows.json`）、丟出去不會掉到螢幕下面（`_settle_airborne`）
- `assets/bubble/` 是沒採用的手繪泡泡，不要用

### v0.3 實作順序建議
1. todo 資料 + 換日清除 → 2. 清單視窗（紙、橫線對齊、標籤）→ 3. 狗拉／推動畫 → 4. 起床時間觸發 → 5. 番茄鐘 + ding → 6. Settings 視窗 → 7. 測試（雲端沒有 PySide6：用假 PySide6 模組跑狀態機；畫面請 Evan 測）→ 8. 寫 v0.3 → v0.4 交接

## v0.3 實作（2026-10-19 完成）
Evan 答題卡另外兩題：**刪除項目 = 滑過出現 ×**、**More interactions 開關留在右鍵選單**（Settings 只放時間）。

### 新檔
| 檔案 | 內容 |
|---|---|
| `pet/todo.py` | `TodoStore`（不依賴 Qt）：`todo.json` 讀寫、`rollover()` 換日刪 done、`add`（壓空白、最多 40 字）/`toggle`/`remove`/`all_done` |
| `pet/todo_window.py` | `TodoWindow`：筆記本紙 + 紅標籤；`InputStrip`：「Add a task...」輸入框（獨立小視窗） |
| `pet/bubble.py` | `Bubble`：頭上的圓角泡泡，獨立透明視窗、滑鼠穿透，靠近螢幕邊往內移，尾巴還是指著狗 |
| `pet/pomodoro.py` | `Pomodoro`（計時邏輯，不依賴 Qt）、`TomatoWindow`（番茄 + 葉子 + MM:SS 牌子，滑鼠穿透）、`Ding`（播放 / 合成 ding.wav）、`make_ding_wav()` |
| `pet/settings_dialog.py` | `SettingsDialog`：Pull out my list at（時 00–23 : 分 00–55 每 5 分）、Work time 1–120、Break time 1–60；`parse_hhmm()` |
| `pet/paper.py` | 共用顏色（紙、橫線、紅邊線、墨色、番茄紅、葉子綠）、`hand_font(px)`、`left_round_rect()`、英文星期 |
| `assets/sounds/ding.wav` | 程式合成的「叮」（G6 1568Hz + 泛音、1.3 秒），不見了會自動重做；Evan 想換聲音就換這個 wav |
| `tests/test_v03.py` + `tests/fakeqt/` | 假 PySide6 + 狀態機測試：`python tests/test_v03.py`（雲端 / VM 裝不到 PySide6，用這個測） |

### 清單視窗怎麼做的（`todo_window.py`）
- **視窗固定在「完全打開」的位置**（螢幕右邊、寬 = 陰影 5 + 標籤 T + 紙 W），紙在視窗裡用 `slide` 左右移（0 = 開、W = 收）。所以視窗永遠不會跨到右邊的另一個螢幕；透明處滑鼠穿透，收起來時只點得到紅標籤
- 尺寸都跟著狗 `k = S/160`：W 300、標籤 16×26、行高 `lh` 34、字 19px（標題 ×1.35、日期 ×0.8）
- 橫線：第 j 條在 `1 + j*lh - 1`；標題 2 行高（Today + `Mon 10/19`，日期用自己的英文星期表，不看系統語系）；每一項的 baseline 在線上 3px，**直接用 baseline 畫字，所以不需要補 EvanHand 的 0.24em**
- 紙的底 = `floor`（狗的 `_ground_rect(screen).bottom()`），紅標籤中心 = `floor - 0.22×S`（狗嘴高度）
- 項目太多（超過螢幕高度）時只顯示放得下的，滑鼠滾輪捲動，右邊有小三角提示
- **不搶焦點**：清單視窗是 `WindowDoesNotAcceptFocus`；輸入框是另一個不透明的小視窗 `InputStrip` 疊在最後一列上（只有清單完全打開時才出現），點它才會拿到鍵盤焦點。Esc 取消；失去焦點時發 `typingDone` → 狗重新 raise 到最上面
- 訊號：`tabClicked`、`toggled(checked, all_done)`、`typingDone`；方法：`attach_screen(screen, floor)`、`set_left(x)`、`set_open()`、`slide_to()`（自己滑 0.35 秒）、`refresh()`

### 狗搬清單（`pet_window.py`）
- 新狀態：`wake`（早上醒來 1.5 秒）→ `list_go`（run 跑過去，速度 max(活潑度速度×2.6, 220)）→ 拉：`list_bite`（run 第 2 格停住、Grr!）→ `list_tug`（2.2 秒、run 倒著 7fps、`_yank()` 分 4 下）→ `list_back`；推：`list_nudge` → `list_push`（1.8 秒、run 正著）→ `list_back`。常數在檔案上面：`BITE`、`NOSE`、`TUG_FPS`、`PULL_SEC`…
- 對齊：拉的時候**清單左邊緣 = 狗嘴 x + 標籤寬/2**、推的時候 **= 狗鼻子 x**（測試量到誤差 0）
- `busy` = 狀態在 `LIST_STATES`：點狗只冒愛心、不能拖、選單指令（`_free()`）都不接、雙擊沒反應
- 疊放：`_raise_all()` = 輸入框 < 狗 < 番茄 < 泡泡（清單在最下面）
- 拉出來時清單會搬到**狗所在的螢幕**；推回去用清單現在所在的螢幕（狗會跑過去）
- 打勾反應 `on_todo_toggled`：小跳（hop + happy）+ 愛心 + Nice! / One down! / Woof!；全做完跳高一點 + All done! Good job!。搬清單、番茄鐘時安靜
- **Claude 自己決定的**：番茄鐘進行中點標籤（或早上時間到）→ 狗不離開番茄，清單自己滑出來 / 收回去（`slide_to`），番茄鐘不會被中斷。Demo 裡是直接停掉番茄鐘，覺得不好所以改了；Evan 不喜歡可以改回來

### 每天起床（`app.py`）
- `_check_wake()` 每 20 秒跑一次、啟動 3 秒後也跑一次：先 `todo.rollover()`（跨過半夜也會清），然後「今天還沒拉過、現在 ≥ wake_time」→ `pet.morning()`；回傳 True 才記 `last_pull_date`（狗被拎著、在空中時回 False，20 秒後再試）
- `morning()`：在睡覺 → `wake` 狀態冒 `"08:00! Good morning!"`（用設定的時間）→ 拉 → `"Your list for today!"`；沒在睡 → 直接拉；清單已經開著 → 只冒字
- Settings 改成「今天還沒到的時間」會清掉 `last_pull_date`，到時間會再拉一次；存檔後馬上檢查一次

### 番茄鐘
- 右鍵（狗和系統匣都有）「Pomodoro → Start (25 min) / Stop」。開始：記下 `pomo_spot`（往左挪到右邊放得下番茄）→ `pomo_go` 跑過去 → 到了才開始計時、番茄出現、"Wind it up!" → `pomo_sit`（專心 = sit、休息 = idle，面向右）
- `_choose_next()` 最前面：番茄鐘進行中就回到番茄旁邊，所以不會亂逛、睡覺、叼滑鼠、zoomies；被拖走或從選單叫牠做別的，做完會自己走回來
- 專心時點狗 / 雙擊 → "Shh... focusing"
- 時間到：`TomatoWindow.ding()` 搖 ±9°（0.14 秒 × 8）+ 叮 + 狗跳 + 愛心 + "Ding! Break time!" → 自動休息（牌子綠字 + break）→ 結束再叮 + "Back to work?"，番茄 2.2 秒後消失，不自動開始下一輪
- 番茄位置：中心 x = 狗 + 0.62S、大小 0.62S、頂 = 地面 − 0.95T；牌子在番茄上方。番茄視窗滑鼠穿透
- 音效：**Windows 用內建 `winsound`**（最穩，不用 QtMultimedia），其他系統才用 `QSoundEffect`。規格寫 QSoundEffect，改用 winsound 是因為 PySide6-Essentials 的多媒體後端在 Windows 偶爾沒聲音

### 對話泡泡
- `say()` 現在全部走 `Bubble`（v0.2 的白邊浮字不用了；`color` 參數留著相容舊呼叫但不再使用）。同時只有一個泡泡，新的蓋掉舊的
- 位置照 demo：尖端在狗中心往面向的方向 0.08S、sprite 頂往下 0.12S；字 18px×k、內距 4/12/6、圓角 14、尾巴 8px、陰影往下 2px

### 選單 / 設定
- 狗的右鍵和系統匣都多了：「Pull out my list / Put away my list」（搬清單時灰掉）、「Pomodoro」、「Settings...」
- settings.json 新鍵：`last_pull_date`、`focus_min`（25）、`break_min`（5）；`wake_time` 原本就有

### 測試（`python tests/test_v03.py`，全過）
拉出來（嘴巴對標籤誤差 0、清單只往外動）、busy 時點狗和選單不打斷、打勾 / 全做完 / 新增 / 刪除 / 點擊判定、標籤高度 = 地面 − 0.22S、推回去（鼻子誤差 0）、早上睡覺 → 醒來 → 拉、已開著只打招呼、被拎著延後、番茄鐘整輪（專心 → 叮 → 休息 → 叮 → 消失）、專心時 Shh / 打勾安靜 / 點標籤清單自己滑、搬清單時不能開始番茄鐘、泡泡不超出螢幕、換日清除、起床檢查（同一天一次、開機補拉、不方便時延後）、各 paintEvent 跑過一遍（假 QPainter，只抓 Python 錯）。
**真 Qt 的 API 和畫面沒辦法在這裡測**，要 Evan 實測。

### v0.3 要請 Evan 確認的
1. 點紅標籤狗會不會跑過去拉、嘴巴有沒有咬在標籤上（`BITE`）、推的時候鼻子有沒有貼著紙邊（`NOSE`）
2. 清單的字有沒有坐在藍線上、字大小、紙寬（`todo_window.py` 的 `lh`、`fp`、`W`）
3. 「Add a task...」點得到、打得了字嗎？打完字狗還在清單上面嗎？
4. 狗會不會擋到標籤（狗站在標籤上時應該點得到透明處後面的標籤）
5. 番茄和葉子大小、葉子轉的方向、MM:SS 牌子位置；叮有沒有聲音、音量
6. 對話泡泡位置、字大小；靠近螢幕邊會不會往內移
7. Settings 視窗長怎樣（下拉選單、數字框的樣式）
8. 改起床時間成幾分鐘後，看早上那段是否正常

## 之後的版本
v0.4 Firebase + 手機 PWA 雙人訊息（頭上冒泡泡，Evan 要先建 Firebase）；v0.5 餵零食、打呼、打包 exe + GitHub Actions + Releases；v1.0 交接文件。原訂 2026-10-19 週一晚上全部完成，已經延後，時程要跟 Evan 重新確認。

## v0.4 Firebase 設定（2026-10-19，Evan 已完成）
- 專案 **`message-76c6c`**（Evan 的 Google 帳號），免費 Spark 方案
- **Realtime Database**：`https://message-76c6c-default-rtdb.asia-southeast1.firebasedatabase.app`（新加坡），建立時選**鎖定模式** → 安全規則還要寫（配對碼綁定的兩個人才能讀寫自己的房間），寫好給 Evan 貼到 Realtime Database →「規則」
- **Authentication → 匿名登入已啟用**（現在在左邊選單「安全性 Security」底下，不是「建構」）
- **網頁應用程式** `dachshund-pwa` 已註冊；完整 web config 存在 **`firebase/config.json`**（公開設定，不是密碼）。有 measurementId（Analytics 開著），用不到可以不載入 analytics SDK
- 桌寵端：用 REST + 匿名登入的 idToken（`identitytoolkit.googleapis.com/v1/accounts:signUp?key=API_KEY` 拿 idToken/refreshToken，`securetoken.googleapis.com` 換新），讀寫 `databaseURL/路徑.json?auth=ID_TOKEN`，收訊息用 SSE（`Accept: text/event-stream`），不用裝 firebase-admin
- 之後想上架成真 App：同一份 PWA 用 Capacitor 包（Apple 開發者 99 美元/年、Google Play 25 美元一次、iOS 要 Mac/Xcode 或雲端編譯）

## v0.4 要做的（還沒定規格）
Firebase + 手機 PWA 雙人訊息：兩個人用配對碼綁定，手機傳訊息 → 對方桌寵頭上冒泡泡（用現在的 `Bubble`）。**Evan 要先建 Firebase 專案**。開工前要先給 Evan 答題卡決定：
- Firebase 用哪個（Realtime Database / Firestore）、登入方式（匿名 + 配對碼？）
- PWA 放哪裡（GitHub Pages？Firebase Hosting？）
- 配對碼流程（桌寵右鍵產生 6 碼 → 手機輸入？）
- 泡泡要顯示多久、訊息要不要存歷史、桌寵能不能回訊息、收到時狗要做什麼動作 / 要不要叮一聲
- 桌寵端的 Python 怎麼連 Firebase（REST + 輪詢 / SSE 串流；不要裝太大的套件，exe 打包會變大）

## GitHub（2026-10-19 起）
- Repo：**https://github.com/StupidLlama/dachshund-pet**（Public，分支 `main`）
- **Evan 要 Claude 每次改完就幫他 commit + push**（他說 "push it for me from now on"）
- 做法（Evan 的電腦上沒有可用的 GitHub 憑證給 device_bash，所以走 bundle）：
  1. `device_request_delete_permission` 要專案資料夾的刪除權限（git 要刪自己的 .lock 檔，沒有權限 commit 會壞）
  2. device_bash：`git add -A && git -c user.name=StupidLlama -c user.email=stupidllamareligion@gmail.com commit -m "..."`，再 `git bundle create .push.bundle origin/main..main`（`.push.bundle` 已在 .gitignore）
  3. `device_stage_files` 把 `.push.bundle` 拿到雲端
  4. 雲端：`add_repo`（owner StupidLlama、repo dachshund-pet、access push）→ clone 到 `/home/claude/dachshund-pet` → `git fetch <bundle> main:incoming && git merge --ff-only incoming && git push origin main`
  5. device_bash：電腦端連不到 GitHub（proxy 403），所以 push 成功後用 `git update-ref refs/remotes/origin/main main` 手動更新 origin/main，再刪掉 `.push.bundle`。Evan 自己在 VS Code 按「同步」或 `git pull` 也會更新
- commit 訊息用英文、說清楚改了什麼

## 新對話開始時
1. 連上 Evan 的電腦（Windows 筆電 laptop-oe33r92j）。專案在 **`C:\Users\user\Desktop\dachshund-pet`**，用 `device_request_folder_access` 要這個資料夾。只改這一份
2. 讀這份 HANDOFF.md 和程式碼（`pet/pet_window.py` 約 1400 行是主體；v0.3 新檔見上面表格）。先問 Evan v0.3 實測結果（上面 8 點）並修好，再進 v0.4
3. v0.4 規格還沒定：先給 Evan 答題卡（上面那幾題），照他的習慣，開工前再給大分類工作清單等他說 OK
4. 寫檔用 device_bash 直接改資料夾裡的檔案（就地改，用 python 讀 → 換字串 → 寫回，不要從工具輸出重打整個檔）；新圖或大檔用 `device_commit_files`
5. 測試：device 的 VM 和雲端都裝不到 PySide6（PyPI 被擋）→ 跑 `python3 tests/test_v03.py`（假 PySide6）；新功能就照這個檔加測試
6. 改完提醒 Evan：先在狗身上右鍵「Quit」，再執行 `cd /d "%USERPROFILE%\Desktop\dachshund-pet" && run.bat`（或雙擊桌面捷徑）重開，不然單一實例只會叫出舊的那隻
7. Claude 的截圖抓不到透明置頂的狗視窗，畫面一律請 Evan 回報
8. Evan 的習慣：回覆用繁體中文；要他決定的事給答題卡；指令給可複製的格式；完成小版本（v0.4）後寫完整交接並請他開新對話
