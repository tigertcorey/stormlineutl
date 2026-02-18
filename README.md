# Stormline UTL Bot 🤖

A production-ready, multi-AI Telegram bot that integrates **Claude 3.5 Sonnet** and **GPT-4** to provide comprehensive, synthesized responses to your questions.

[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Telegram Bot API](https://img.shields.io/badge/Telegram%20Bot%20API-20.7-blue.svg)](https://python-telegram-bot.org/)
[![Docker](https://img.shields.io/badge/docker-ready-brightgreen.svg)](https://www.docker.com/)

## ✨ Features

### 🎯 Core Capabilities
- **Multi-Model AI Integration**: Seamlessly interact with both Claude 3.5 Sonnet and GPT-4
- **Three Query Modes**:
  - `/claude` - Get responses from Claude AI only
  - `/gpt` - Get responses from GPT-4 only
  - `/both` or default - Get synthesized responses combining insights from both models
- **Intelligent Synthesis**: Automatically combines the best aspects of both AI responses
- **Conversation History**: Maintains context across your conversation (last 10 messages)
- **Graceful Degradation**: Automatically falls back to a single model if one is unavailable
- **PDF Conversion Tool**: Convert Edmund job proposals to Stormline Master v3 format (see [CONVERSION_README.md](CONVERSION_README.md))

### 🛠️ Technical Features
- **Async Architecture**: Built with Python's async/await for optimal performance
- **Modular Design**: Clean separation of concerns (bot handlers, AI models, config, utilities)
- **Error Handling**: Comprehensive error handling with automatic retry logic and exponential backoff
- **Docker Support**: Production-ready Docker setup with multi-stage builds
- **Logging**: Detailed logging at multiple levels (DEBUG, INFO, ERROR)
- **Security**: Environment-based configuration with no hardcoded credentials

### 🔒 Security & Reliability
- Input sanitization and validation
- Rate limit handling with automatic retries
- Secure credential management via environment variables
- Health checks for Docker deployments

## 📋 Prerequisites

### Required
- **Python 3.11+** (if running without Docker)
- **Docker & Docker Compose** (recommended for deployment)
- **API Keys**:
  - [Telegram Bot Token](https://core.telegram.org/bots#6-botfather) from @BotFather
  - [Anthropic API Key](https://console.anthropic.com/) for Claude
  - [OpenAI API Key](https://platform.openai.com/) for GPT-4

### System Requirements
- Ubuntu 20.04+ (or any Linux distribution)
- 1GB+ RAM recommended
- Internet connection for API calls

## 🚀 Quick Start

### Option 1: Docker Deployment (Recommended)

```bash
# 1. Clone the repository
git clone https://github.com/tigertcorey/stormlineutl.git
cd stormlineutl

# 2. Configure environment variables
cp .env.example .env
nano .env  # Edit with your API keys

# 3. Start the bot with Docker Compose
docker-compose up -d

# 4. Check logs
docker-compose logs -f
```

### Option 2: Python Virtual Environment

```bash
# 1. Clone the repository
git clone https://github.com/tigertcorey/stormlineutl.git
cd stormlineutl

# 2. Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment variables
cp .env.example .env
nano .env  # Edit with your API keys

# 5. Run the bot
python bot.py
```

## ⚙️ Configuration

### Environment Variables

Create a `.env` file from the template:

```bash
cp .env.example .env
```

Edit the `.env` file with your credentials:

```env
# Required
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
ANTHROPIC_API_KEY=your_anthropic_api_key_here
OPENAI_API_KEY=your_openai_api_key_here

# Optional
LOG_LEVEL=INFO                    # DEBUG, INFO, WARNING, ERROR
MAX_HISTORY_LENGTH=10             # Number of messages to keep in history
MAX_MESSAGE_LENGTH=4000           # Maximum message length
```

### Getting API Keys

1. **Telegram Bot Token**:
   - Open Telegram and search for [@BotFather](https://t.me/botfather)
   - Send `/newbot` and follow the instructions
   - Copy the bot token provided

2. **Anthropic API Key**:
   - Go to [console.anthropic.com](https://console.anthropic.com/)
   - Sign up or log in
   - Navigate to API Keys and create a new key

3. **OpenAI API Key**:
   - Go to [platform.openai.com](https://platform.openai.com/)
   - Sign up or log in
   - Navigate to API Keys and create a new key

## 📖 Usage

### Available Commands

| Command | Description | Example |
|---------|-------------|---------|
| `/start` | Welcome message and introduction | `/start` |
| `/help` | Show help and usage guide | `/help` |
| `/claude <message>` | Query Claude AI only | `/claude Explain quantum computing` |
| `/gpt <message>` | Query GPT-4 only | `/gpt What is machine learning?` |
| `/both <message>` | Query both models with synthesis | `/both Compare Python and JavaScript` |
| `<any message>` | Default: query both models | `How does blockchain work?` |

### Example Interactions

**Single Model Query:**
```
You: /claude What are the benefits of async programming?

Bot: 💡 Claude:
Async programming offers several key benefits...
```

**Multi-Model Query:**
```
You: What is the future of artificial intelligence?

Bot: 🤖 Synthesized Answer:
The future of AI involves several converging trends...

---
💡 Claude's perspective:
Claude sees AI evolving through...

🧠 GPT-4's perspective:
GPT-4 emphasizes the importance of...
```

### Response Format

When using `/both` mode or default messaging, you receive:

1. **🤖 Synthesized Answer**: A comprehensive response combining the best insights from both models
2. **💡 Claude's Perspective**: Claude's unique viewpoint
3. **🧠 GPT-4's Perspective**: GPT-4's unique viewpoint

## 🐳 Docker Deployment

### Building and Running

```bash
# Build the image
docker-compose build

# Start the bot
docker-compose up -d

# View logs
docker-compose logs -f stormline-bot

# Stop the bot
docker-compose down

# Restart the bot
docker-compose restart
```

### Docker Commands

```bash
# Check container status
docker-compose ps

# Access container shell
docker-compose exec stormline-bot /bin/bash

# View resource usage
docker stats stormline-bot

# Remove everything (including volumes)
docker-compose down -v
```

## 📁 Project Structure

```
stormlineutl/
├── bot.py                          # Main bot entry point with handlers
├── ai_models.py                   # AI model integrations (Claude, GPT-4)
├── config.py                      # Configuration management
├── utils.py                       # Helper functions and utilities
├── convert_edmund_to_stormline.py # PDF conversion tool
├── requirements.txt               # Python dependencies
├── Dockerfile                     # Docker container definition
├── docker-compose.yml             # Docker Compose configuration
├── .env.example                   # Environment variables template
├── .gitignore                     # Git ignore rules
├── README.md                      # This file
├── SETUP.md                       # Detailed setup guide
├── CONVERSION_README.md           # PDF conversion tool documentation
└── logs/                          # Log directory (created at runtime)
```

## 🔧 Troubleshooting

### Bot Not Responding

1. Check if the bot is running:
   ```bash
   docker-compose ps
   ```

2. Check logs for errors:
   ```bash
   docker-compose logs -f
   ```

3. Verify environment variables:
   ```bash
   docker-compose config
   ```

### API Key Issues

- **Invalid Token**: Verify your Telegram bot token in `.env`
- **Anthropic API Errors**: Check your Anthropic API key and quota
- **OpenAI API Errors**: Verify your OpenAI API key and ensure you have GPT-4 access

### Rate Limiting

If you encounter rate limits:
- The bot automatically retries with exponential backoff
- Consider implementing message queuing for high-traffic scenarios
- Check your API quotas and limits

### Docker Issues

```bash
# Rebuild containers from scratch
docker-compose down
docker-compose build --no-cache
docker-compose up -d

# Check Docker logs
docker logs stormline-utl-bot

# Remove all Docker data and restart
docker-compose down -v
docker-compose up -d
```

## 🔄 Development

### Running in Development Mode

```bash
# Activate virtual environment
source venv/bin/activate

# Set log level to DEBUG
export LOG_LEVEL=DEBUG

# Run the bot
python bot.py
```

### Adding New Features

The modular architecture makes it easy to extend:

- **New AI Models**: Add to `ai_models.py`
- **New Commands**: Add handlers in `bot.py`
- **New Utilities**: Add to `utils.py`
- **Configuration Options**: Add to `config.py`

## 🗺️ Roadmap

Future features planned:

- [ ] **PlanSwift Integration**: COM API integration for construction takeoff
- [ ] **SMS/Twilio Support**: SMS interface via Twilio
- [ ] **Web Dashboard**: Monitor bot usage and analytics
- [ ] **Database Integration**: Persistent conversation history with PostgreSQL
- [ ] **Custom GPT Actions**: RESTful API endpoints for ChatGPT plugins
- [ ] **Multi-language Support**: Internationalization (i18n)
- [ ] **Voice Messages**: Support for audio input/output
- [ ] **Image Analysis**: Integration with vision models
- [ ] **Admin Panel**: User management and bot configuration

## 📄 License

This project is open source and available for use under the MIT License.

## 🤝 Contributing

Contributions are welcome! Please feel free to submit issues or pull requests.

## 📞 Support

- **Issues**: [GitHub Issues](https://github.com/tigertcorey/stormlineutl/issues)
- **Documentation**: See [SETUP.md](SETUP.md) for detailed setup instructions

## 🙏 Acknowledgments

Built with:
- [python-telegram-bot](https://python-telegram-bot.org/)
- [Anthropic Claude API](https://www.anthropic.com/)
- [OpenAI GPT-4 API](https://openai.com/)

---

Made with ❤️ for the Stormline community