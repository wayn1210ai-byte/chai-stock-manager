# 柴柴股票管家 🐕📈

每人有自己的持股帳號，支援買賣紀錄、自動抓取股價、損益分析。

## 部署到 Render

1. Fork 此 repo
2. 在 Render 建立 Web Service，選此 repo
3. Build Command: `pip install -r requirements.txt`
4. Start Command: `python3 stock_server.py`

⚠️ Render 免費方案重啟後資料會重置，建議定期匯出備份。
