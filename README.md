# 🐶 臘腸狗桌寵 Dachshund Pet

Windows 桌寵：會在整個螢幕上 8 方向亂逛的臘腸狗。（目前版本 v0.4）

## 執行

```
py -m pip install PySide6-Essentials pillow
py main.py
```

第一次跑完之後，右鍵點右下角系統匣裡的狗圖示 →「Create desktop shortcut」，以後雙擊桌面上的狗就能開，不會跳出終端機。

**方便功能**
- `Ctrl + Alt + D`：在任何地方叫狗過來
- 再雙擊一次捷徑：不會多一隻狗，而是叫原本那隻過來
- 系統匣選單 →「Start with Windows」
- 用捷徑開時看不到錯誤訊息，錯誤會記在 `%APPDATA%\DachshundPet\error.log`

## v0.1 能做什麼

| 動作 | 怎麼觸發 |
|---|---|
| 8 方向自由亂逛 | 自動 |
| 坐下、發呆 | 自動，或右鍵選單 |
| 摸摸頭（冒愛心） | 滑鼠在狗身上輕晃（v0.2 起） |
| 拎起來（身體會被拉長） | 左鍵按住拖曳 |
| 放下（落地彈一下） | 放開滑鼠 |
| 睡覺 💤 | 太久沒理牠會自己睡；點一下叫醒 |
| 乖乖待著 / 活潑程度 / 改名字 | 右鍵選單或系統匣圖示 |
| 狗跑不見 | 點系統匣圖示 → 牠會出現在螢幕中央 |

設定檔位置：`%APPDATA%\DachshundPet\settings.json`

## v0.2 互動 🐾

全部用現有的 84 格圖做，沒有新增動畫。

| 互動 | 怎麼觸發 |
|---|---|
| 摸頭（冒愛心） | 滑鼠停在狗身上輕輕晃 0.5 秒 |
| 名牌 | 滑鼠停在狗身上會顯示名字 |
| 揉肚子 | 雙擊狗，或右鍵「Belly rub」→ 在肚子上來回滑，越揉腳踢越快；再雙擊翻回來 |
| 戳一下 | 左鍵點一下：隨機轉頭 / 嚇一跳 / 打噴嚏 / 開心 |
| 追游標 | 牠偶爾會自己跑來聞你的游標；右鍵「Play → Chase my cursor」 |
| 叼走滑鼠 | 約 10 分鐘一次，用力甩滑鼠或點牠就會鬆口；右鍵「Mouse-stealing prank」可改頻率或關掉 |
| Zoomies 暴衝 | 自己會做；也可以從右鍵「Play」叫牠做 |

**更多互動（預設關閉）**：右鍵「More interactions」可以打開：亂晃 → 頭暈、丟出去、看著游標、被快速掃過會嚇到、追尾巴、聞地板、心情系統（名牌顯示心情和親密度，影響行為）。

**搬資料夾也沒關係**：每次啟動時，桌面捷徑和開機自動啟動會自動改成指向目前的資料夾。

**自訂字型**：目前用的是 Evan 手寫的 `EvanHand.ttf`（只有英數字，中文自動用系統字型）。想重寫的話，把寫好的 `tools/font_template.png` 照片丟給 `py tools/build_font.py 照片.png assets/fonts/EvanHand.ttf`。也可以把 `.ttf` / `.otf` 放進 `assets/fonts/`，名牌、頭上冒的字、選單都會改用那個字型。

## v0.3 待辦清單、番茄鐘 📝🍅

| 功能 | 怎麼用 |
|---|---|
| 待辦清單 | 點螢幕右邊緣的**紅色標籤**：狗會跑過去咬住、倒退著把清單拖出來；再點一次，牠用鼻子推回去。右鍵「Pull out my list」也可以 |
| 打勾 | 點一項就打勾（狗會開心跳、冒愛心）；全部做完牠會說 All done! |
| 新增 / 刪除 | 最下面「Add a task...」打字按 Enter 或 Add；滑鼠移到某一項上，右邊出現 × 就能刪 |
| 每天起床 | 每天到設定的時間（預設 08:00），狗把清單拉出來給你看；電腦比較晚開的話，當天第一次開就拉 |
| 換日 | 打勾的項目隔天自動清掉 |
| 番茄鐘 | 右鍵「Pomodoro → Start」：狗坐在番茄旁邊陪你，葉子指針慢慢轉回頂端；時間到番茄搖晃 + 叮一聲 → 自動休息 → 再叮一聲就停。專心時點狗牠會說 Shh |
| Settings | 右鍵「Settings...」：幾點拉出清單（24 小時制）、專心 / 休息幾分鐘 |

- 清單存在 `%APPDATA%\DachshundPet\todo.json`
- 狗搬清單的時候點牠不會打斷（只會搖尾巴冒愛心）；番茄鐘進行中點標籤，清單會自己滑出來，狗繼續陪你專心
- 「叮」是 `assets/sounds/ding.wav`，想換成別的聲音就換這個檔（要是 .wav）
- 番茄和葉子是 `assets/pomodoro/tomato.png`、`leaf.png`（512×512、同一個中心點、葉子最長那片朝上）

## v0.4 跟朋友互傳訊息 💌

兩個人配對之後，可以從桌寵或手機傳訊息到對方的狗頭上。

| 功能 | 怎麼用 |
|---|---|
| 選單 | 狗右鍵 →「📱 Phone & friends」：📱 Link my phone / 🧪 Test with my phone / 💌 Invite a friend / 🔑 I have a code / ⚙ Pairing |
| 連自己的手機 | 「📱 Link my phone」→ 打名字 → 手機打開 https://stupidllama.github.io/dachshund-pet/ 輸入那組碼。**不用先有朋友**。手機可以「加入主畫面」當 App 用 |
| 自己測試 | 「🧪 Test with my phone」：手機假裝成朋友，手機傳的訊息會跑到自己的狗頭上。測完在手機「⋯ → Unpair」，再用「💌 Invite a friend」 |
| 邀請朋友 | 「💌 Invite a friend」→ 把碼給朋友，朋友在他的狗「🔑 I have a code」輸入，或在手機網頁輸入。碼 10 分鐘內有效 |
| 收到訊息 | 狗頭上冒紅色「!」→ 跑到螢幕中間 → 汪！→ 泡泡一直顯示到你點掉（點泡泡或點狗）。好幾則會一則一則來 |
| 番茄鐘專心中 | 只冒「!」幾秒 + Windows 通知，泡泡等休息時間才出現 |
| 回覆 / 看紀錄 | 右鍵「Messages with ○○...」（最近 20 則 + 打字回覆）；在訊息泡泡上按右鍵也能直接回覆 |
| 手機 | 聊天室：完整紀錄、快捷訊息、看得到對方的狗醒著沒、訊息「Sent / Delivered / Seen」 |

- 一則最多 60 字。英數字用手寫字，中文在電腦上用標楷體、在手機上用霞鶩文楷
- 對方的狗沒開也可以傳，下次開機就會收到
- 汪的聲音是 `assets/sounds/bark.wav`（程式合成的），想換成真的狗叫就換這個檔
- 配對資料存在 `%APPDATA%\DachshundPet\cloud.json`
- 用 Firebase Realtime Database（免費方案）。安全規則在 `firebase/database.rules.json`，由 `tools/build_rules.py` 產生

## 自訂圖示

把正方形、透明背景的 `icon.png`（建議 512×512）放進 `assets/`，重開後系統匣和桌面捷徑就會換成它。

## 換成你的正式圖 🎨

1. 匯出草圖，拿來描圖用：
   ```
   py tools/export_sketches.py
   ```
   檔案會輸出到 `sketches/`，`sketches/contact_sheet.png` 是全部動作的總表。
2. 照下面的資料夾結構放進 `assets/`。哪個動作有圖就用你的圖，沒圖的會自動用草圖頂替，所以可以一個一個慢慢換。

```
assets/
├─ walk/            分方向，每個方向 6 格
│  ├─ down/          frame_01.png ~ frame_06.png
│  ├─ down_right/
│  ├─ right/
│  ├─ up_right/
│  └─ up/            （左邊的方向程式會自動鏡像，不用畫）
├─ run/             同 walk，6 格
├─ idle/            frame_01~04   不分方向
├─ sit/             frame_01~04
├─ sleep/           frame_01~02
├─ held/            frame_01~06   被拎起來（脖子在上方中間）
├─ happy/           frame_01~06
└─ belly/           frame_01~06   翻肚
```

**圖片規格**
- 正方形、透明背景的 PNG，建議 320×320（程式會自動縮放）
- 狗腳底的中點放在**寬 50%、高 64%** 的位置，也就是草圖的影子中心，這樣換圖時狗不會跳位
- `held` 動作：抓住的點（脖子）在**寬 50%、高 16%**
- 不要畫影子，程式會自己畫
- 從白底切出來的圖如果外框外有白點，跑 `py tools/defringe.py` 會自動清掉（原圖先備份到 `assets_original/`）
- 嘴巴大約和滑鼠游標一樣大（草圖的比例就是對的）
- 格數不用跟上面完全一樣，程式會依照資料夾裡的張數播放
- idle / sit / happy 是朝右前方畫的，往左走時程式會自動鏡像
