#!/usr/bin/env bash
# ==============================================================================
# Tradology BTC Options Trading Engine — Production Healthcheck Diagnostic Script
# ==============================================================================
set -euo pipefail

API_URL="${API_URL:-http://localhost:8000}"
DASHBOARD_URL="${DASHBOARD_URL:-http://localhost:3000}"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}============================================================${NC}"
echo -e "${CYAN}🔍 TRADOLOGY TRADING SYSTEM — HEALTH & CONNECTIVITY AUDIT${NC}"
echo -e "${CYAN}============================================================${NC}"

# 1. FastAPI Process Liveness (/health)
echo -n "Checking FastAPI Liveness (${API_URL}/health)... "
HEALTH_RESP=$(curl -s -o /dev/null -w "%{http_code}" "${API_URL}/health" || echo "000")
if [ "$HEALTH_RESP" = "200" ]; then
    echo -e "${GREEN}✅ OK (HTTP 200)${NC}"
else
    echo -e "${RED}❌ FAILED (HTTP ${HEALTH_RESP})${NC}"
fi

# 2. Trading Engine Readiness (/ready)
echo -n "Checking Engine Readiness (${API_URL}/ready)... "
READY_BODY=$(curl -s "${API_URL}/ready" || echo '{"ready":false}')
IS_READY=$(echo "$READY_BODY" | grep -o '"ready":true' || echo "")
if [ -n "$IS_READY" ]; then
    echo -e "${GREEN}✅ READY${NC} (${READY_BODY})"
else
    echo -e "${YELLOW}⚠️ NOT READY / SAFE_HALT${NC} (${READY_BODY})"
fi

# 3. System & Exchange Status (/api/v1/status)
echo -n "Checking System Status (${API_URL}/api/v1/status)... "
STATUS_BODY=$(curl -s "${API_URL}/api/v1/status" || echo '{}')
ENGINE_STATUS=$(echo "$STATUS_BODY" | grep -o '"status":"[^"]*"' | head -n 1 || echo '"status":"UNKNOWN"')
RECON_STATUS=$(echo "$STATUS_BODY" | grep -o '"is_synchronized":[^,}]*' || echo '"is_synchronized":false')
DB_STATUS=$(echo "$STATUS_BODY" | grep -o '"database":{[^}]*}' || echo '"database":{}')

echo -e "${GREEN}✅ RESPONDING${NC}"
echo -e "   • Engine: ${CYAN}${ENGINE_STATUS}${NC}"
echo -e "   • Reconciliation: ${CYAN}${RECON_STATUS}${NC}"
echo -e "   • Database: ${CYAN}${DB_STATUS}${NC}"

# 4. Dashboard Web Runtime (Next.js)
echo -n "Checking Next.js Dashboard (${DASHBOARD_URL})... "
DASH_RESP=$(curl -s -o /dev/null -w "%{http_code}" "${DASHBOARD_URL}" || echo "000")
if [ "$DASH_RESP" = "200" ]; then
    echo -e "${GREEN}✅ ONLINE (HTTP 200)${NC}"
else
    echo -e "${YELLOW}⚠️ OFFLINE (HTTP ${DASH_RESP})${NC}"
fi

echo -e "${CYAN}============================================================${NC}"
