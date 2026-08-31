#!/bin/sh
# 從 HTML 抽出分析核心並加上 CommonJS 匯出，供 test-indicators.js 使用
set -e
SRC="${1:-tw-stock-analyzer.html}"
awk '/ANALYTICS-CORE-START/,/ANALYTICS-CORE-END/' "$SRC" > core.js
cat >> core.js << 'EXPORTS'
module.exports={toNum,normDate,validDate,parseInput,SMA,EMA,RSI,rsiValue,KD,MACD,BOLL,
  computeStats,buildIndicators,lastCross,maArrangement,esc,volLabel,decodeBytes};
EXPORTS
echo "core.js 產生完成（$(wc -l < core.js) 行）"
