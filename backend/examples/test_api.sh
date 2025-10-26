#!/bin/bash
# Demo script to test the API end-to-end

set -e

API_URL="http://localhost:8000"

echo "=== 1. Register Form ==="
FORM_YAML=$(cat examples/demo_form.yaml)
RESPONSE=$(curl -s -X POST "$API_URL/register_forms" \
  -H "Content-Type: application/json" \
  -d "{\"form_yaml\": $(echo "$FORM_YAML" | jq -Rs .)}")

echo "$RESPONSE" | jq .

FLOW_ID=$(echo "$RESPONSE" | jq -r .flow_id)
echo "Flow ID: $FLOW_ID"

echo ""
echo "=== 2. Create Run ==="
RESPONSE=$(curl -s -X POST "$API_URL/runs" \
  -H "Content-Type: application/json" \
  -d "{
    \"flow_id\": \"$FLOW_ID\",
    \"payload\": {
      \"username\": \"johndoe\",
      \"email\": \"john@example.com\",
      \"age\": 30,
      \"newsletter\": true
    }
  }")

echo "$RESPONSE" | jq .

RUN_ID=$(echo "$RESPONSE" | jq -r .run_id)
echo "Run ID: $RUN_ID"

echo ""
echo "=== 3. Get Run Status ==="
curl -s "$API_URL/runs/$RUN_ID" | jq .

echo ""
echo "=== 4. Advance Run ==="
curl -s -X POST "$API_URL/runs/$RUN_ID/advance" \
  -H "Content-Type: application/json" \
  -d '{"event": "continue"}' | jq .

echo ""
echo "=== 5. Final Run Status ==="
curl -s "$API_URL/runs/$RUN_ID" | jq .

echo ""
echo "=== Demo Complete ==="
