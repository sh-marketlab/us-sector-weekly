# 美股板塊週報（週四檢查點／週五結算）

自動化網頁：美股 11 個 GICS 板塊 + 6 大主題族群的資金流與相對強弱，週四看方向、週五看確認，再對照台股（加權、櫃買、台積電 ADR 溢價、對應族群、外資買賣超），加上國際新聞解讀。全繁體中文。

## 怎麼運作

```
GitHub Actions（週四、五 UTC 21:40）
  scripts/fetch_data.py → docs/data/latest.json、history/、index.json
Claude 排程任務（台北 週五、週六 早上）
  讀 latest.json + 搜尋新聞 → docs/data/commentary/<日期>-<thu|fri>.json
GitHub Pages（/docs）
  docs/index.html 讀上面兩個檔案渲染；右上角可切換歷史期別
```

沒有解讀檔時，網頁仍會顯示全部數據與自動摘要。

## 設定

- 板塊、族群、台股對應、門檻：`config.json`
- 解讀欄位與寫作規則：`COMMENTARY_SPEC.md`
- 信號燈（☆ 自訂）：週內相對 SPY ≥ +1.0pp 且當日資金分數 > 0 為強勢……詳見 `config.json` 的 `rules`

## 第一次啟用

1. Settings → Pages → Source 選 `main` 分支、`/docs` 資料夾
2. Actions → update-data → Run workflow（session 選 auto）跑第一次
3. 測試：`python -m pytest -q tests`

## 已知限制

- Yahoo Finance 免費資料，偶有延遲或缺值
- 證交所 BFI82U 若擋掉 GitHub 的海外 IP，外資買賣超會顯示「資料未取得」，其他部分不受影響
- 外資只含上市，不含櫃買
