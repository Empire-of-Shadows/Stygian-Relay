# Stygian Relay Deployment Guide

This guide explains how to deploy the Stygian Relay Discord bot using Docker. The deployment system automatically pulls code from GitHub and keeps all secrets secure inside the container.

## Overview

The deployment system features:

- **Git-based deployment**: Code is pulled directly from GitHub during build
- **Secret management**: All credentials live only in the container (no secrets on host filesystem)
- **Health monitoring**: Automatic health checks ensure the bot is running properly
- **Rollback capability**: Automatic rollback to previous version if deployment fails
- **Zero-downtime updates**: Graceful shutdown and startup

## Prerequisites

- Docker and Docker Compose installed on your server
- SSH access to your server
- A `.env` file with your bot credentials (see Setup section)

## Initial Setup

### 1. Create the Deployment Directory

On your server, create a directory for the deployment files:

```bash
mkdir -p ~/bots/stygian-relay
cd ~/bots/stygian-relay
```

### 2. Create Required Files

You only need THREE files on your server:

#### a. `docker-compose.yml`

Copy the `docker-compose.yml` from this repository to your server.

#### b. `healthcheck.py`

Copy the `healthcheck.py` from this repository to your server. This file is copied into the container during build.

#### c. `deploy.sh`

Copy the `deploy.sh` from this repository to your server and make it executable:

```bash
chmod +x deploy.sh
```

### 3. Create the `.env` File

Create a `.env` file with your bot's credentials:

```bash
nano .env
```

Use the `.env.example` as a template. Required variables:

```env
DISCORD_TOKEN=your_discord_bot_token_here
BOT_OWNER_ID=your_discord_user_id_here
MONGODB_URI=mongodb://localhost:27017/stygian_relay
EMAIL=your_email@example.com
PASSWORD=your_email_password_here
LOG_CHANNEL_ID=your_log_channel_id_here
LOG_LEVEL=INFO
```

**IMPORTANT**: The `.env` file should NEVER be committed to git. It only exists on your server.

## Deployment Workflow

### How It Works

1. **Build Time**: Docker pulls the latest code from GitHub
2. **Container Creation**: Code and dependencies are installed inside the container
3. **Runtime**: The `.env` file is injected into the container as environment variables
4. **Health Checks**: Automatic monitoring ensures the bot stays healthy

### Directory Structure on Server

```
~/bots/stygian-relay/
├── docker-compose.yml    # Docker orchestration file
├── healthcheck.py        # Health check script
├── deploy.sh            # Deployment script with rollback
└── .env                 # Your secrets (NEVER commit this!)
```

### Code Updates

When you update code in GitHub:

1. **On your server**, run the deployment script:

```bash
cd ~/bots/stygian-relay
./deploy.sh
```

The script will:
- Backup the current running version
- Pull latest code from GitHub inside Docker build
- Build the new container image
- Stop the old container gracefully
- Start the new container
- Monitor health checks
- **Automatically rollback** if health checks fail

### First Deployment

```bash
cd ~/bots/stygian-relay
./deploy.sh
```

The first deployment will:
1. Pull the Python base image
2. Clone the repository from GitHub
3. Install all dependencies
4. Start the bot
5. Monitor health checks for 2 minutes
6. Follow logs (press Ctrl+C to exit log view)

## Monitoring

### View Logs

```bash
docker logs -f StygianRelay
```

Press `Ctrl+C` to exit.

### Check Container Status

```bash
docker ps
```

Look for the `StygianRelay` container. The STATUS column should show "healthy".

### Check Health Status

```bash
docker inspect StygianRelay --format='{{.State.Health.Status}}'
```

Should return: `healthy`

### Manual Health Check

```bash
docker exec StygianRelay python /app/healthcheck.py
```

## Troubleshooting

### Deployment Failed

The deployment script automatically rolls back to the previous version if:
- Build fails
- Container doesn't start
- Health checks fail

Check logs to diagnose:

```bash
docker logs StygianRelay
```

### Container is Unhealthy

If the container shows as unhealthy:

1. Check the logs:
```bash
docker logs StygianRelay --tail 100
```

2. Check the health check output:
```bash
docker exec StygianRelay python /app/healthcheck.py
```

3. Common issues:
   - Missing or invalid `DISCORD_TOKEN`
   - MongoDB connection issues (check `MONGODB_URI`)
   - Insufficient resources (check memory/CPU limits)

### Manual Rollback

If you need to manually rollback:

```bash
# Stop current container
docker compose down

# Check for backup image
docker images | grep stygian-relay:backup

# Tag backup as current
docker tag stygian-relay:backup stygian-relay

# Start container
docker compose up -d
```

### Update .env Variables

If you need to update environment variables:

1. Edit the `.env` file:
```bash
nano .env
```

2. Recreate the container:
```bash
docker compose up -d --force-recreate
```

This recreates the container with new environment variables without rebuilding the image.

### Clean Restart

To completely rebuild from scratch:

```bash
# Stop and remove container
docker compose down

# Remove all related images
docker rmi stygian-relay stygian-relay:backup

# Deploy fresh
./deploy.sh
```

## Security Notes

### What's Stored Where

**On Server (visible)**:
- `docker-compose.yml` - Configuration
- `healthcheck.py` - Health monitoring
- `deploy.sh` - Deployment automation
- `.env` - **SECRETS (protected by .gitignore)**

**In Git (public)**:
- All source code
- `Dockerfile`
- `docker-compose.yml`
- `healthcheck.py`
- `deploy.sh`
- `.env.example` (template only)

**Never in Git**:
- `.env` (actual credentials)
- Log files
- Any files with tokens/passwords

### Protecting Secrets

1. The `.env` file is automatically excluded by `.gitignore`
2. Environment variables are only visible inside the container
3. The container is isolated from the host
4. Logs are rotated to prevent secret leakage

## Advanced Configuration

### Changing Branch

By default, the Dockerfile clones the `main` branch. To deploy from a different branch:

Edit `Dockerfile` line 15:

```dockerfile
# Clone a specific branch
RUN git clone -b dev https://github.com/Empire-of-Shadows/Stygian-Relay.git .
```

Then rebuild:

```bash
./deploy.sh
```

### Resource Limits

Edit `docker-compose.yml` to adjust resources:

```yaml
deploy:
  resources:
    limits:
      cpus: '0.50'      # Max CPU cores
      memory: 512M      # Max RAM
    reservations:
      cpus: '0.25'      # Guaranteed CPU
      memory: 256M      # Guaranteed RAM
```

### Health Check Tuning

Edit `docker-compose.yml` health check settings:

```yaml
healthcheck:
  test: ["CMD", "python", "/app/healthcheck.py"]
  interval: 30s       # Check every 30 seconds
  timeout: 10s        # Fail if check takes > 10s
  retries: 3          # Mark unhealthy after 3 failures
  start_period: 60s   # Grace period during startup
```

## Maintenance

### Log Rotation

Logs are automatically rotated:
- Max file size: 10MB
- Max files: 3
- Total max: 30MB per container

### Cleanup Old Images

Remove unused Docker images:

```bash
docker image prune -f
```

Remove all stopped containers and unused images:

```bash
docker system prune -a -f
```

## Quick Reference

| Task | Command |
|------|---------|
| Deploy/Update | `./deploy.sh` |
| View Logs | `docker logs -f StygianRelay` |
| Stop Bot | `docker compose down` |
| Start Bot | `docker compose up -d` |
| Restart Bot | `docker compose restart` |
| Check Health | `docker inspect StygianRelay --format='{{.State.Health.Status}}'` |
| Manual Health Check | `docker exec StygianRelay python /app/healthcheck.py` |
| Update .env Only | `docker compose up -d --force-recreate` |
| Shell into Container | `docker exec -it StygianRelay bash` |
| Clean Rebuild | `docker compose down && docker rmi stygian-relay && ./deploy.sh` |

## Support

For issues:
1. Check logs: `docker logs StygianRelay`
2. Run health check: `docker exec StygianRelay python /app/healthcheck.py`
3. Review this guide
4. Check GitHub issues
