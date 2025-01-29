#!/bin/bash
clear

# Configuration
URL="https://0x05485c0b0c759d1ec2b5307207b11077927e2fcf.gaia.domains/v1/chat/completions"
HEADERS=(-H "accept: application/json" -H "Content-Type: application/json")
KEYWORDS_URL="https://raw.githubusercontent.com/suuf24/question/refs/heads/main/keywords.txt"  # URL of keywords
INTERVAL=30  # Interval in seconds

# Function to get a random keyword from the URL
get_random_keyword() {
  local keyword=$(curl -s "$KEYWORDS_URL" | shuf -n 1)
  if [[ -z "$keyword" ]]; then
    echo "Error: Could not retrieve keyword from URL!" >&2
    exit 1
  fi
  echo "$keyword"
}

# Function to send the request
send_request() {
  local keyword=$(get_random_keyword)  # Get a random keyword
  echo "Sending request with keyword: $keyword"

  # Construct the JSON data
  local data=$(cat <<EOF
{
  "messages": [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "$keyword"}
  ]
}
EOF
  )

  # Send the request using curl
  response=$(curl -s -X POST "$URL" "${HEADERS[@]}" -d "$data")

  # Extract and display the response content
  local content=$(echo "$response" | jq -r '.choices[0].message.content')
  echo "Response received:"
  echo "$content"
  echo "------------------------------------"
}

# Function to display a countdown timer
countdown() {
  local seconds=$1
  while [[ $seconds -gt 0 ]]; do
    echo -ne "Waiting $seconds seconds before the next request...\r"
    sleep 1
    ((seconds--))
  done
  echo -ne "Waiting 0 seconds before the next request...\r"
  echo
}

# Main loop to send requests every 30 seconds
while true; do
  send_request
  countdown $INTERVAL  # Start the countdown
done
