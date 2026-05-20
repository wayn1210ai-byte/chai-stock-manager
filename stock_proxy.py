#!/usr/bin/env python3
"""柴柴股票管家 - Proxy 伺服器
解決瀏覽器 CORS 限制，讓手機也能自動抓取股價

使用方法：
  1. 在電腦上執行：python3 stock_proxy.py
  2. 在同個 wifi 下的手機，打開瀏覽器輸入 http://你的電腦IP:8765
  
  或者直接在電腦上打開 http://localhost:8765
"""

import http.server
import urllib.request
import json
import os
import sys

PORT = 8765
DIR = os.path.dirname(os.path.abspath(__file__))
HTML_FILE = os.path.join(DIR, 'stock_tool.html')

class ProxyHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        # Proxy endpoint: /api/stock?codes=2330,2317,0056
        if self.path.startswith('/api/stock'):
            try:
                from urllib.parse import urlparse, parse_qs
                qs = parse_qs(urlparse(self.path).query)
                codes = qs.get('codes', [''])[0]
                
                if not codes:
                    self.send_error(400, 'Missing codes parameter')
                    return
                
                # Yahoo Finance API - fetch one by one to avoid rate limits
                code_list = [c.strip() for c in codes.split(',') if c.strip()]
                prices = {}
                
                for code in code_list:
                    url = 'https://query1.finance.yahoo.com/v8/finance/chart/' + code + '.TW?range=1d&interval=1d'
                    try:
                        req = urllib.request.Request(url, headers={
                            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                        })
                        with urllib.request.urlopen(req, timeout=10) as resp:
                            data = json.loads(resp.read().decode())
                        result = data.get('chart', {}).get('result', [])
                        for item in result:
                            meta = item.get('meta', {})
                            symbol = meta.get('symbol', '').replace('.TW', '')
                            price = meta.get('regularMarketPrice')
                            if symbol and price:
                                prices[symbol] = price
                    except Exception:
                        pass
                    import time
                    time.sleep(0.3)
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({'success': True, 'prices': prices}).encode())
                return
                
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode())
                return
        
        # Serve the stock tool HTML
        if self.path == '/' or self.path == '/index.html':
            self.path = '/stock_tool.html'
        
        return super().do_GET()
    
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', '*')
        self.end_headers()

if __name__ == '__main__':
    # Get local IP
    import socket
    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)
    
    server = http.server.HTTPServer(('0.0.0.0', PORT), ProxyHandler)
    print(f'🐕 柴柴股票管家 - Proxy 伺服器啟動成功!')
    print(f'📱 本機打開: http://localhost:{PORT}')
    print(f'📱 手機打開: http://{local_ip}:{PORT}  (需在同個 WiFi)')
    print(f'🔥 按 Ctrl+C 停止伺服器')
    print(f'{"="*40}')
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n👋 伺服器已停止')
        server.server_close()
