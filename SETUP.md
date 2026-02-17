# Stormline UTL Bot - Ubuntu Setup Guide

This guide provides step-by-step instructions for deploying the Stormline UTL Bot on Ubuntu 20.04+.

## Table of Contents

1. [System Requirements](#system-requirements)
2. [Installing Prerequisites](#installing-prerequisites)
3. [Setting Up with Docker](#setting-up-with-docker)
4. [Setting Up without Docker](#setting-up-without-docker)
5. [Running as a System Service](#running-as-a-system-service)
6. [Configuration](#configuration)
7. [Monitoring and Maintenance](#monitoring-and-maintenance)
8. [Troubleshooting](#troubleshooting)

## System Requirements

### Minimum Requirements
- **OS**: Ubuntu 20.04 LTS or later
- **RAM**: 1GB minimum, 2GB recommended
- **Disk Space**: 500MB for application and dependencies
- **Network**: Internet connection for API calls

### Required Accounts
- Telegram account with bot created via @BotFather
- Anthropic account with API access
- OpenAI account with GPT-4 API access

## Installing Prerequisites

### Update System Packages

```bash
sudo apt update
sudo apt upgrade -y
```

### Install Git

```bash
sudo apt install -y git
```

### Install Docker and Docker Compose (Recommended)

```bash
# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Add your user to the docker group
sudo usermod -aG docker $USER

# Install Docker Compose
sudo apt install -y docker-compose

# Verify installation
docker --version
docker-compose --version

# Log out and log back in for group changes to take effect
```

### Install Python 3.11+ (for non-Docker setup)

```bash
# Add deadsnakes PPA for latest Python
sudo apt install -y software-properties-common
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt update

# Install Python 3.11 and dependencies
sudo apt install -y python3.11 python3.11-venv python3.11-dev
sudo apt install -y python3-pip

# Verify installation
python3.11 --version
```

## Setting Up with Docker

### 1. Clone the Repository

```bash
cd ~
git clone https://github.com/tigertcorey/stormlineutl.git
cd stormlineutl
```

### 2. Configure Environment Variables

```bash
# Copy the example environment file
cp .env.example .env

# Edit with your API keys
nano .env
```

Add your credentials:

```env
TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
ANTHROPIC_API_KEY=sk-ant-api03-...
OPENAI_API_KEY=sk-...
LOG_LEVEL=INFO
```

Save and exit (Ctrl+X, then Y, then Enter).

### 3. Create Logs Directory

```bash
mkdir -p logs
```

### 4. Build and Start the Bot

```bash
# Build the Docker image
docker-compose build

# Start the bot in detached mode
docker-compose up -d

# Check if the bot is running
docker-compose ps
```

### 5. View Logs

```bash
# Follow logs in real-time
docker-compose logs -f

# View last 100 lines
docker-compose logs --tail=100

# Exit logs view: Ctrl+C
```

### 6. Stop the Bot

```bash
docker-compose down
```

## Setting Up without Docker

### 1. Clone the Repository

```bash
cd ~
git clone https://github.com/tigertcorey/stormlineutl.git
cd stormlineutl
```

### 2. Create Virtual Environment

```bash
# Create virtual environment
python3.11 -m venv venv

# Activate virtual environment
source venv/bin/activate

# Your prompt should now show (venv)
```

### 3. Install Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Configure Environment Variables

```bash
# Copy the example environment file
cp .env.example .env

# Edit with your API keys
nano .env
```

Add your credentials (same as Docker setup above).

### 5. Create Logs Directory

```bash
mkdir -p logs
```

### 6. Run the Bot

```bash
# Make sure virtual environment is activated
source venv/bin/activate

# Run the bot
python bot.py
```

The bot should start and display logs. Press Ctrl+C to stop.

## Running as a System Service

To run the bot as a background service that automatically starts on boot:

### 1. Create Service File

```bash
sudo nano /etc/systemd/system/stormline-bot.service
```

### 2. Add Service Configuration

```ini
[Unit]
Description=Stormline UTL Telegram Bot
After=network.target

[Service]
Type=simple
User=YOUR_USERNAME
WorkingDirectory=/home/YOUR_USERNAME/stormlineutl
Environment="PATH=/home/YOUR_USERNAME/stormlineutl/venv/bin"
ExecStart=/home/YOUR_USERNAME/stormlineutl/venv/bin/python bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**Important**: Replace `YOUR_USERNAME` with your actual Ubuntu username.

### 3. Enable and Start Service

```bash
# Reload systemd daemon
sudo systemctl daemon-reload

# Enable service to start on boot
sudo systemctl enable stormline-bot

# Start the service
sudo systemctl start stormline-bot

# Check status
sudo systemctl status stormline-bot
```

### 4. Service Management Commands

```bash
# Start the service
sudo systemctl start stormline-bot

# Stop the service
sudo systemctl stop stormline-bot

# Restart the service
sudo systemctl restart stormline-bot

# View logs
sudo journalctl -u stormline-bot -f

# Check status
sudo systemctl status stormline-bot
```

## Configuration

### Environment Variables

All configuration is done via the `.env` file:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | Yes | - | Your Telegram bot token from @BotFather |
| `ANTHROPIC_API_KEY` | Yes | - | Your Anthropic API key for Claude |
| `OPENAI_API_KEY` | Yes | - | Your OpenAI API key for GPT-4 |
| `LOG_LEVEL` | No | INFO | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `MAX_HISTORY_LENGTH` | No | 10 | Number of message pairs to keep in history |
| `MAX_MESSAGE_LENGTH` | No | 4000 | Maximum message length |

### Obtaining API Keys

#### Telegram Bot Token

1. Open Telegram and search for `@BotFather`
2. Send `/newbot` command
3. Follow the prompts to create your bot
4. Copy the token provided (format: `123456789:ABCdef...`)

#### Anthropic API Key

1. Visit https://console.anthropic.com/
2. Sign up or log in
3. Navigate to "API Keys" section
4. Click "Create Key"
5. Copy the key (format: `sk-ant-api03-...`)

#### OpenAI API Key

1. Visit https://platform.openai.com/
2. Sign up or log in
3. Navigate to "API Keys" section
4. Click "Create new secret key"
5. Copy the key (format: `sk-...`)
6. **Note**: You need GPT-4 API access for this bot

## Monitoring and Maintenance

### Check Bot Status (Docker)

```bash
# Container status
docker-compose ps

# Resource usage
docker stats stormline-utl-bot

# View logs
docker-compose logs -f
```

### Check Bot Status (Systemd Service)

```bash
# Service status
sudo systemctl status stormline-bot

# View logs
sudo journalctl -u stormline-bot -f

# View last 100 log lines
sudo journalctl -u stormline-bot -n 100
```

### Update the Bot

```bash
cd ~/stormlineutl

# Pull latest changes
git pull origin main

# For Docker:
docker-compose down
docker-compose build
docker-compose up -d

# For systemd service:
sudo systemctl restart stormline-bot
```

### Backup Configuration

```bash
# Backup your .env file
cp .env .env.backup

# Backup with timestamp
cp .env .env.backup.$(date +%Y%m%d)
```

### Log Rotation

Logs can grow large over time. Set up log rotation:

```bash
sudo nano /etc/logrotate.d/stormline-bot
```

Add:

```
/home/YOUR_USERNAME/stormlineutl/logs/*.log {
    daily
    rotate 7
    compress
    delaycompress
    notifempty
    missingok
    create 644 YOUR_USERNAME YOUR_USERNAME
}
```

## Troubleshooting

### Bot Not Starting

**Check configuration:**
```bash
cat .env
```

Ensure all required variables are set.

**Check logs:**
```bash
# Docker
docker-compose logs

# Systemd
sudo journalctl -u stormline-bot -n 50
```

### Permission Denied Errors

```bash
# Fix file permissions
chmod +x bot.py

# Fix directory permissions
chmod 755 ~/stormlineutl
```

### Docker Issues

**Docker daemon not running:**
```bash
sudo systemctl start docker
sudo systemctl enable docker
```

**Permission denied:**
```bash
# Add user to docker group
sudo usermod -aG docker $USER

# Log out and log back in
```

**Container fails to start:**
```bash
# Rebuild from scratch
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

### Python/Virtual Environment Issues

**Module not found:**
```bash
source venv/bin/activate
pip install -r requirements.txt
```

**Wrong Python version:**
```bash
# Check Python version in venv
source venv/bin/activate
python --version

# Recreate venv with correct version
deactivate
rm -rf venv
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### API Errors

**Telegram API errors:**
- Verify bot token is correct
- Check bot is not already running elsewhere
- Ensure internet connectivity

**Claude/GPT-4 API errors:**
- Verify API keys are correct
- Check API quota/billing
- Ensure you have GPT-4 access (for OpenAI)

### Network Issues

**Check internet connectivity:**
```bash
ping google.com
```

**Check DNS resolution:**
```bash
nslookup api.openai.com
nslookup api.anthropic.com
```

**Check firewall:**
```bash
sudo ufw status
```

If firewall is blocking, allow outbound HTTPS:
```bash
sudo ufw allow out 443/tcp
```

### High Memory Usage

Monitor memory:
```bash
# Docker
docker stats stormline-utl-bot

# System
free -h
htop
```

If memory is high, consider:
- Reducing `MAX_HISTORY_LENGTH` in `.env`
- Restarting the bot periodically
- Adding more RAM to your system

## Security Best Practices

1. **Never commit `.env` file**: Already in `.gitignore`
2. **Restrict file permissions**:
   ```bash
   chmod 600 .env
   ```
3. **Use strong API keys**: Regenerate if compromised
4. **Regular updates**:
   ```bash
   cd ~/stormlineutl
   git pull
   ```
5. **Monitor logs**: Check for unusual activity
6. **Firewall**: Enable and configure UFW
   ```bash
   sudo ufw enable
   sudo ufw allow ssh
   ```

## Getting Help

- **GitHub Issues**: https://github.com/tigertcorey/stormlineutl/issues
- **Documentation**: See main [README.md](README.md)
- **Logs**: Always include relevant logs when asking for help

## Quick Reference

### Essential Commands

```bash
# Docker deployment
docker-compose up -d        # Start
docker-compose down         # Stop
docker-compose logs -f      # View logs
docker-compose restart      # Restart

# Systemd service
sudo systemctl start stormline-bot    # Start
sudo systemctl stop stormline-bot     # Stop
sudo systemctl restart stormline-bot  # Restart
sudo systemctl status stormline-bot   # Status
sudo journalctl -u stormline-bot -f   # Logs

# Manual run
source venv/bin/activate    # Activate venv
python bot.py               # Run bot
```

---

For more information, see the main [README.md](README.md) file.
