# 新聞解讀寫作規格

數據來源：`docs/data/latest.json`（`us`、`taiwan`，以及 `liquidity`＝聯準會 H.4.1、資金市場、財政部、部位）；QRA 資料檔 `docs/data/qra/latest.json`（每季由使用者提供原文後更新）。

每週四、五美股收盤後，排程任務讀 `docs/data/latest.json`，搜尋國際新聞，寫入：

```
docs/data/commentary/<session_date>-<session>.json   例：2026-11-06-fri.json
```

檔名必須和 latest.json 的 `session_date`、`session` 完全一致，網頁才會讀到。

## 寫作原則

1. **語言**：繁體中文（台灣用語）。數字用半形，漲跌寫 `+1.23%`、`−0.45%`，相對強弱寫 `pp`，殖利率變動寫 `bp`。
2. **數字只能來自 latest.json 或新聞原文**，自己算的標「（計算）」，自己推論的標「（解讀）」，二手轉述標「（二手引用）」。
3. **先看量、再看幅度**：先講資金分數與量比，再講漲跌幅。
4. **週四報告**＝本週第一個檢查點：方向是什麼、哪些板塊放量。
   **週五報告**＝週結算：對照 `thu` 欄位與 `verdict`，說明哪些「確認／減弱／反轉」。
5. **新聞要對到板塊**：每則新聞說清楚它影響哪個板塊或族群、數據上有沒有看到反應；看不到就直說「數據上沒有明顯反應」。
6. **台灣對照**：看 `taiwan.reacts_to_us`，說明台股這一盤反應的是哪一天的美股；比較 `mapping` 的美台族群差距、ADR 溢價、外資買賣超。
7. **找不到原因就寫「原因未確認」**，不要猜。放進 `limits`。
8. **引用**：每個來源最多引一句、少於 15 字，其餘改寫成自己的話。
9. 文字欄位可用 `<b>…</b>`、`<em>…</em>`、`<br>`，其他 HTML 會被轉成純文字。
10. 不寫買賣建議。
11. **資金足跡（聯準會 H.4.1 與財政部）是總經傳導的一環**：把「準備金／TGA／逆回購 → 短期利率（SOFR−IORB）→ 信用利差 → 風險資產」這條線，和當週板塊表現對照；說明資金面是「助力、阻力或中性」，並標（解讀）。
12. **H.4.1 讀法固定五步驟**：① 方向（總資產與供給）→ ② 位置（準備金、TGA、RRP）→ ③ 原因（Bills、MBS、回購、貸款）→ ④ 結果（瀑布圖：準備金變化由哪幾項造成）→ ⑤ 性質（短期工具或長期供給）。數字一律引用 `latest.json` 的 `liquidity.h41`，單位十億美元（B）。
13. **門檻標示**：★＝一年分布判定、☆＝自訂研習門檻、○＝只記方向。判定沿用 `liquidity` 內的 `signal`，不自行改判；若要補充看法標（解讀）。
14. **TGA 對照 QRA**：用 `liquidity.qra_check` 與 `liquidity.h41.tga_scenarios` 說明 TGA 是否在財政部預估高峰區間、距年底假設多遠，情境 A／B／C 對準備金的影響。
15. **H.4.1 時間差**：H.4.1 每週四美東 16:30 公布、截至週三。週四報告若 `liquidity.h41.week` 不是本週三，要在 `liquidity_limits` 註明用的是上一週。
16. **MMF**：ICI 擋自動下載，請用 WebSearch／WebFetch 找 ICI 每週四公布的 Money Market Fund Assets，填 `mmf`；找不到就寫「本期未取得」。
17. **預測答案表**：週五報告寫 `predictions`（下週一的範圍，3–6 項，如準備金、TGA、10 年債、美元指數、板塊輪動、美元兌新台幣）；下一個週四報告用實際數據寫 `scorecard` 評分（命中／部分命中／未命中／暫不判定）。

## 欄位（全部選填，沒有就省略）

```jsonc
{
  "headline": "一句話標題（顯示在大標下方）",
  "tags": ["最多 5 個短標籤"],
  "intro": "大標下的導言 1–2 句",
  "lede": "核心數字上方的重點框，2–3 句",
  "plain_signals": "信號燈的白話說",
  "summary": ["<b>粗體開頭的結論。</b>補充說明", "…（5–8 點）"],
  "plain_summary": "摘要的白話說",
  "plain_flow": "漲幅 vs 資金分數的白話說（省略則用預設比喻）",
  "plain_groups": "6 大族群的白話說",
  "interpretation": [{"title": "粗體小標。", "body": "段落"}],
  "news_chain_title": "因果鏈標題",
  "news_chain": [{"title": "1–4 字", "detail": "一行說明", "color": "#選填"}],
  "news": [{"text": "一則新聞與它對板塊的影響", "source": "媒體名（日期）"}],
  "plain_news": "新聞的白話說",
  "taiwan": "台灣對照段落",
  "plain_taiwan": "台灣對照的白話說",
  "watch": [{"date": "11/10", "what": "事件", "why": "為什麼重要"}],
  "thresholds": "☆ 自訂的觀察警戒線",
  "kids": "給國小生的白話版，一段",
  "plain_kids": "國小生版的白話說",
  "limits": ["這期特有的限制"],
  "sources": [{"name": "媒體／機構", "url": "https://…", "note": "用到哪些內容"}],

  // ---- 資金足跡（主頁摘要區塊＋liquidity.html 完整頁）
  "liquidity_headline": "資金足跡頁的副標",
  "liquidity_intro": "資金足跡頁導言",
  "liquidity_lede": "重點框 2–3 句：準備金、TGA、逆回購、淨流動性怎麼動，對市場是助力或阻力",
  "liquidity_chain": [{"title": "MMF／TGA／準備金…", "detail": "一行", "color": "#選填"}],
  "plain_liquidity": "白話說",
  "liquidity_steps": [{"title": "方向 — 資金釋出了嗎", "body": "…"}, "…共 5 步"],
  "liquidity_watch": ["本週需要確認的事項（下次 H.4.1、QRA、標售…）"],
  "loan_check": [{"q": "在市場上借不到錢嗎", "value": "SOFR−IORB …", "verdict": "▲稍微偏緊"}],
  "plain_tga": "TGA 情境的白話說",
  "plain_ladder": "利率階梯的白話說",
  "mmf": {"rows": [{"type": "政府型 機構", "assets": 4527, "chg": -32.62}], "text": "閱讀順序與解讀", "source": "ICI（日期）"},
  "auction_note": "本週標售的需求強度解讀",
  "qra_note": "QRA 對本週市場與 TGA 的意義",
  "plain_qra": "QRA 的白話說",
  "issues_12": [{"area": "貨幣政策", "check": "…"}, "…共 12 領域：貨幣政策、財政與公債、經濟指標、企業財報、產業與主題、地緣政治與原物料、信用與金融穩定、匯率與資本、台灣、中國日本與新興市場、加密貨幣、政治與監管"],
  "asset_flows": [{"class": "風險資產", "assets": "股票與加密貨幣", "flow": "↔ 內部輪動…"}],
  "predictions_target": "11/9 週一",
  "predictions": [{"item": "準備金週平均", "range": "2,900–2,980 B", "current": "2,930.1", "basis": "（解讀）…"}],
  "scorecard": [{"item": "…", "prediction": "…", "actual": "…", "grade": "命中"}],
  "liquidity_limits": ["資金足跡特有的限制"],
  "liquidity_sources": [{"name": "ICI", "url": "https://…", "note": "MMF"}]
}
```
