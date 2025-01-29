#!/bin/bash
clear

# Configuration
URL="https://0x05485c0b0c759d1ec2b5307207b11077927e2fcf.gaia.domains/v1/chat/completions"
HEADERS=(-H "accept: application/json" -H "Content-Type: application/json")
KEYWORDS_FILE="keywords.txt"  # File containing the list of questions/keywords
INTERVAL=30  # Interval in seconds

# Function to get a random line from the keywords file
get_random_keyword() {
  if [[ -f "$KEYWORDS_FILE" ]]; then
    shuf -n 1 "$KEYWORDS_FILE"  # Use `shuf` to pick a random line
  else
    echo "Error: File $KEYWORDS_FILE not found!" >&2
    exit 1
  fi
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
