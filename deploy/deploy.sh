#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════════
# AWARE Fund Production Deployment Script
# ═══════════════════════════════════════════════════════════════════════════════
# Usage:
#   ./deploy.sh setup     - First-time server setup
#   ./deploy.sh deploy    - Deploy/update the application
#   ./deploy.sh logs      - View service logs
#   ./deploy.sh status    - Check service status
#   ./deploy.sh stop      - Stop all services
# ═══════════════════════════════════════════════════════════════════════════════

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
DEPLOY_DIR="/opt/aware"
REPO_URL="git@github.com:ent0n29/aware.git"
COMPOSE_FILE="docker-compose.prod.yaml"

log() {
    echo -e "${GREEN}[AWARE]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
    exit 1
}

compose_cmd() {
    docker compose -f "$COMPOSE_FILE" "$@"
}

# ─────────────────────────────────────────────────────────────────────────────────
# First-time server setup
# ─────────────────────────────────────────────────────────────────────────────────
setup() {
    log "Setting up AWARE Fund production server..."

    # Update system
    log "Updating system packages..."
    apt-get update && apt-get upgrade -y

    # Install Docker
    if ! command -v docker &> /dev/null; then
        log "Installing Docker..."
        curl -fsSL https://get.docker.com | sh
        systemctl enable docker
        systemctl start docker
    else
        log "Docker already installed"
    fi

    # Install Docker Compose plugin
    if ! docker compose version &> /dev/null; then
        log "Installing Docker Compose plugin..."
        apt-get install -y docker-compose-plugin
    else
        log "Docker Compose already installed"
    fi

    # Install useful tools
    log "Installing utilities..."
    apt-get install -y git curl wget htop ncdu fail2ban ufw

    # Configure firewall
    log "Configuring firewall..."
    ufw default deny incoming
    ufw default allow outgoing
    ufw allow ssh
    ufw allow http
    ufw allow https
    ufw --force enable

    # Configure fail2ban
    log "Configuring fail2ban..."
    systemctl enable fail2ban
    systemctl start fail2ban

    # Create deploy directory
    log "Creating deployment directory..."
    mkdir -p "$DEPLOY_DIR"
    cd "$DEPLOY_DIR"

    # Clone repository (if not exists)
    if [ ! -d "$DEPLOY_DIR/.git" ]; then
        log "Cloning repository..."
        git clone "$REPO_URL" .
    fi

    # Create .env file if not exists
    if [ ! -f "$DEPLOY_DIR/.env" ]; then
        log "Creating .env file from template..."
        cp "$DEPLOY_DIR/.env.example" "$DEPLOY_DIR/.env"
        warn "Please edit $DEPLOY_DIR/.env with your configuration!"
    fi

    log "✅ Server setup complete!"
    log ""
    log "Next steps:"
    log "  1. Edit $DEPLOY_DIR/.env with your configuration"
    log "  2. Point your domain's A record at this server"
    log "  3. Run: make prod-up   (Caddy handles TLS on its own)"
}

# ─────────────────────────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════
# Deploy
# ═══════════════════════════════════════════════════════════════════════════
deploy() {
    log "Deploying AWARE Fund..."

    cd "$DEPLOY_DIR"

    # Pull latest code
    log "Pulling latest code..."
    git pull origin main

    # Load environment
    if [ -f "$DEPLOY_DIR/.env" ]; then
        export $(grep -v '^#' "$DEPLOY_DIR/.env" | xargs)
    fi

    cd "$DEPLOY_DIR/deploy"

    # Build and start services
    log "Building and starting services..."
    compose_cmd build
    compose_cmd up -d

    # Wait for services to be healthy
    log "Waiting for services to start..."
    sleep 30

    # Check status
    status

    log "✅ Deployment complete!"
}

# ─────────────────────────────────────────────────────────────────────────────────
# View logs
# ─────────────────────────────────────────────────────────────────────────────────
logs() {
    SERVICE=${1:-}

    cd "$DEPLOY_DIR/deploy"

    if [ -z "$SERVICE" ]; then
        compose_cmd logs -f --tail=100
    else
        compose_cmd logs -f --tail=100 "$SERVICE"
    fi
}

# ─────────────────────────────────────────────────────────────────────────────────
# Check status
# ─────────────────────────────────────────────────────────────────────────────────
status() {
    log "Service Status:"

    cd "$DEPLOY_DIR/deploy"
    compose_cmd ps

    echo ""
    log "Health Checks:"

    # Check each service endpoint
    services=("aware-executor" "aware-strategy" "aware-api" "aware-web")
    for service in "${services[@]}"; do
        case "$service" in
            aware-executor) health_url="http://localhost:8080/api/polymarket/health" ;;
            aware-strategy) health_url="http://localhost:8081/api/strategy/status" ;;
            aware-api) health_url="http://localhost:8000/api/health" ;;
            aware-web) health_url="http://localhost:3000/" ;;
            *) health_url="http://localhost/health" ;;
        esac

        if docker exec "$service" wget -q --spider "$health_url" 2>/dev/null; then
            echo -e "  ${GREEN}✓${NC} ${service#aware-}"
        else
            echo -e "  ${RED}✗${NC} ${service#aware-}"
        fi
    done
}

# ─────────────────────────────────────────────────────────────────────────────────
# Stop all services
# ─────────────────────────────────────────────────────────────────────────────────
stop() {
    log "Stopping all services..."

    cd "$DEPLOY_DIR/deploy"
    compose_cmd down

    log "✅ All services stopped"
}

# ─────────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────────
case "${1:-help}" in
    setup)
        setup
        ;;
    deploy)
        deploy
        ;;
    logs)
        logs $2
        ;;
    status)
        status
        ;;
    stop)
        stop
        ;;
    *)
        echo "AWARE Fund Deployment Script"
        echo ""
        echo "Usage: $0 <command>"
        echo ""
        echo "Commands:"
        echo "  setup   - First-time server setup"
        echo "  deploy  - Deploy/update the application"
        echo "  logs    - View service logs (optionally: logs <service>)"
        echo "  status  - Check service status"
        echo "  stop    - Stop all services"
        ;;
esac
