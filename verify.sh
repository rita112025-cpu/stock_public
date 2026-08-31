#!/bin/sh
# 確認收到的檔案未在傳輸過程被改動，然後執行測試
set -e
echo "--- 檔案指紋 ---"
sha256sum tw-stock-analyzer.html test-indicators.js
echo "--- 語法檢查 ---"
node --check test-indicators.js && echo "test-indicators.js: OK"
echo "--- 產生 core.js 並執行測試 ---"
sh build-core.sh tw-stock-analyzer.html
node --check core.js && echo "core.js: OK"
node test-indicators.js
