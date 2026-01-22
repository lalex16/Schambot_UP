# Schambot - Shame Research Chatbot

Therapeutic chatbot for Master's thesis in Psychology on promoting self-compassion in shame experiences.

### Overview

Schambot is an AI-powered therapeutic chatbot that runs via Signal Messenger and guides participants through a structured 15-day process:

- **Week 1 (Days 1-8):** Shame exploration through daily reflection questions
- **Week 2 (Days 9-15):** Self-compassion interventions with personalized exercises
- **AI Integration:** Azure OpenAI (GPT-4.1-mini) for empathetic, contextualized responses
- **Crisis Intervention:** Automatic semantic detection with emergency resources

### Technology Stack

- **Programming Language:** Python 3.14
- **AI Model:** Azure OpenAI GPT-4.1-mini
- **Messaging:** Signal Messenger via Signal-CLI-REST-API
- **Data Persistence:** JSON/JSONL

## Project Structure

```
Schambot_UP/
├── requirements.txt       # Python dependencies
├── README.md              # Documentation
├── CODE_STRUCTURE.md      # bot.py function overview
├── .gitignore             # Git exclusions
│
├── src/
│     ├── main.py        # Entry point
│     ├── config.py      # Configuration & constants
│     ├── bot.py         # Bot logic
│     ├── gpt_client.py  # OpenAI/GPT integration
│     └── storage        # Data persistence
│
└── tests/
    └── test_smoke.py      # Basic validation tests
```

## Installation

### Prerequisites

- Python 3.14 or higher
- Docker (for Signal API)
- Azure OpenAI Account with API Key
- Signal phone number (registered)

### Step 1: Clone Repository

```bash
git clone https://github.com/lalex16/Schambot_UP.git
cd Schambot_UP
```

### Step 2: Create Virtual Environment

```bash
# Create virtual environment
python -m venv venv

# Activate
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows
```

### Step 3: Install Dependencies

```bash
# Install all dependencies
pip install -r requirements.txt

# Or: Install package in editable mode
pip install -e .
```

### Step 4: Configure Environment Variables

Create a `.env` file in project root:

```bash
# .env
SIGNAL_NUMBER=+49xxxxxxxxx        # Your Signal number
AZUREAI_API_KEY=sk-xxxxxxxxxxxxx  # Azure OpenAI API Key
```

---

## Signal API Setup

Schambot uses the [Signal-CLI-REST-API](https://github.com/bbernhard/signal-cli-rest-api) for communication via Signal Messenger.

### Option 1: Docker (Recommended for Development)

```bash
# Start Docker container
docker run -d \
  --name signal-api \
  -p 8080:8080 \
  -v $(pwd)/signal-data:/home/.local/share/signal-cli \
  bbernhard/signal-cli-rest-api:latest

# Check status
curl http://localhost:8080/v1/health
```

### Option 2: Docker Compose (Recommended for Production)

Create a `docker-compose.yml`:

```yaml
version: '3'
services:
  signal-api:
    image: bbernhard/signal-cli-rest-api:latest
    container_name: signal-api
    ports:
      - "8080:8080"
    volumes:
      - ./signal-data:/home/.local/share/signal-cli
    environment:
      - MODE=native
    restart: unless-stopped
```

Start:

```bash
docker-compose up -d
```


### Signal Number Registration (within docker container)

*Important:* Signal registration typically requires a **Captcha Token**

#### Registration with Captcha Token

This is the most reliable method and works when SMS verification fails.

**Step 1: Get Captcha Token**

1. Open Signal's registration page in your browser:
   ```
   https://signalcaptchas.org/registration/generate.html
   ```

2. Complete the Captcha challenge

3. Copy the generated token (starts with `signalcaptcha://`)
   - Example: `signalcaptcha://signal-hcaptcha.5LSbd...`
   - The Token is everything AFTER `signalcaptcha://`! (In this exampe the token is:`signal-hcaptcha.5LSbd...` )

**Step 2: Register with Token** 

```bash
# Register number with captcha token (replace with your number and token)
docker exec -it signal-api signal-cli -u +YOURNUMBER register --captcha TOKEN 
```
You might not receive a SMS. If so, use this command instead and you'll receive a call

````
docker exec -it signal-bot signal-cli -u +YOURNUMBER register --captcha TOKEN --voice
````

**Step 3: Receive Verification Code**

Wait for SMS/Call with verification code (6 digits)

**Step 4: Verify Number**

```bash
# Verify with code received via SMS (replace XXXXXX with your code)
docker exec -it signal-bot signal-cli -u +YOURNUMBER verify CODE
```

**Check success:**
``` bash
signal-cli listAccounts  
```

**Testing:**

Test if container is running:
```bash
curl http://localhost:8081/v1/about
```
Send a test message
```bash
curl -X POST http://localhost:8081/v1/send\
  -H "Content-Type: application/json" \
  -d '{
    "message": "Test from Schambot!",
    "number": "+49xxxxxxxxx",
    "recipients": ["+49yyyyyyyyyy"]
  }' 
```

### Available API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/register/{number}` | POST | Register number |
| `/v1/register/{number}/verify` | POST | Verify number |
| `/v1/send` | POST | Send message |
| `/v1/receive/{number}` | GET | Receive messages |
| `/v1/health` | GET | Health check |

**Detailed API documentation:** http://localhost:8080/api-docs

---

## Usage

### Start Bot

```bash
# Ensure Signal API is running
curl http://localhost:8080/v1/health

# Start bot
python -m main
```

**Expected output:**

```
Scham-Chatbot gestartet!
Senden 'Start' vom Handy, um zu beginnen
Logs: ../schambot/chatbot.log
Stoppen mit Ctrl+C
--------------------------------------------------
Starting Scham Research Bot...
Listening for messages...
```

### Stop Bot

```bash
# In terminal where bot is running:
Ctrl+C
```

### View Logs

```bash
# Live logs
tail -f ../schambot/chatbot.log

# Filter errors
grep -i error ../schambot/chatbot.log

# Last 50 lines
tail -50 ../schambot/chatbot.log
```

---

## Development

### Code Structure

**Main flow:**

```
main.py 
  → bot.py
    → setup_scheduler() (Automated messages)
    → listen_for_messages() (Signal API polling)
      → handle_signal_message() (Message routing)
        → handle_onboarding() / handle_week1() / handle_week2()
          → generate_ai_response() (GPT-4.1 integration)
            → send_signal_message()
```

### Run Tests

```bash
# Smoke tests (import validation)
python tests/test_smoke.py
```

---

## Logs and Monitoring

### Log Levels

```python
# Adjust in config/settings.py:
logging.basicConfig(level=logging.DEBUG)  # For development
logging.basicConfig(level=logging.INFO)   # For production
```

### Production Monitoring

```bash
# Error monitoring
watch -n 60 'grep -i error ../schambot/chatbot.log | tail -10'

# Active users
ls -1 ../schambot/user_state/*.json | wc -l

# Last activity
stat ../schambot/chatbot.log
```

---

## Troubleshooting

### Problem: "Signal API connection error"

**Causes and solutions:**

1. **Docker container not running:**
   ```bash
   docker ps  # Check if signal-api is running
   docker start signal-api  # If stopped
   ```

2. **Wrong port:**
   ```bash
   # Check which port is being used
   docker ps | grep signal-api
   # Adjust in config/settings.py if needed:
   SIGNAL_API_URL = "http://localhost:8080/v1"
   ```

3. **Number not registered:**
   ```bash
   # See "Register Signal Number" above
   ```

### Problem: "ModuleNotFoundError: No module named 'schambot'"

**Solution:**
```bash
pip install -e .
```

---

## Privacy and Data Protection

All personal data is handled in compliance with GDPR:

- **Phone numbers:** SHA256 hashing for anonymization
- **Storage:** Encrypted mapping files separate from user data
- **API Keys:** Environment variables (not version controlled)
- **Logs:** Only hashed IDs, no plain text numbers

---


## Author

**Laura Alex**  
University of Potsdam, Department of Psychology  
Master's Thesis, 2025-2026

GitHub: [@lalex16](https://github.com/lalex16)  
Repository: [Schambot_UP](https://github.com/lalex16/Schambot_UP)


**Last updated:** January 2026  
**Version:** 1.0.0  

