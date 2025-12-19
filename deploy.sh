#!/bin/bash
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration (required environment variables)
EC2_HOST="${LLM_COUNCIL_EC2_HOST:-}"
SSH_KEY="${LLM_COUNCIL_SSH_KEY:-~/.ssh/llm-council-key.pem}"
REMOTE_DIR="${LLM_COUNCIL_REMOTE_DIR:-~/llm-council}"

# Validate required environment variables
if [ -z "$EC2_HOST" ]; then
  echo -e "${RED}Error: LLM_COUNCIL_EC2_HOST environment variable is required${NC}"
  echo -e "Example: export LLM_COUNCIL_EC2_HOST=ec2-user@your-ec2-ip"
  exit 1
fi

# Parse arguments
BUMP_TYPE="${1:-patch}"  # patch, minor, major

# Show help if requested
if [[ "$1" == "-h" || "$1" == "--help" ]]; then
  echo "Usage: $0 [patch|minor|major]"
  echo ""
  echo "Environment variables:"
  echo "  LLM_COUNCIL_EC2_HOST    - EC2 host (required, e.g., ec2-user@your-ec2-ip)"
  echo "  LLM_COUNCIL_SSH_KEY     - SSH key path (default: ~/.ssh/llm-council-key.pem)"
  echo "  LLM_COUNCIL_REMOTE_DIR  - Remote directory (default: ~/llm-council)"
  exit 0
fi

echo -e "${YELLOW}=== LLM Council Deploy Script ===${NC}"
echo -e "Deploying to: ${GREEN}$EC2_HOST${NC}"

# Read current version
VERSION=$(cat VERSION)
echo -e "Current version: ${GREEN}$VERSION${NC}"

# Parse version components
IFS='.' read -r MAJOR MINOR PATCH <<< "$VERSION"

# Bump version based on type
case $BUMP_TYPE in
  major)
    MAJOR=$((MAJOR + 1))
    MINOR=0
    PATCH=0
    ;;
  minor)
    MINOR=$((MINOR + 1))
    PATCH=0
    ;;
  patch)
    PATCH=$((PATCH + 1))
    ;;
  *)
    echo -e "${RED}Invalid bump type: $BUMP_TYPE. Use: patch, minor, or major${NC}"
    exit 1
    ;;
esac

NEW_VERSION="$MAJOR.$MINOR.$PATCH"
echo -e "New version: ${GREEN}$NEW_VERSION${NC}"

# Update VERSION file
echo "$NEW_VERSION" > VERSION

# Update frontend package.json version
cd frontend
npm version $NEW_VERSION --no-git-tag-version --allow-same-version
cd ..

echo -e "${YELLOW}Syncing files to EC2...${NC}"
rsync -avz --exclude '.git' --exclude 'node_modules' --exclude '__pycache__' \
  --exclude '.env' --exclude '.env.production' --exclude 'data' --exclude 'ssl' --exclude '.claude' --exclude '.venv' \
  -e "ssh -i $SSH_KEY" \
  ./ $EC2_HOST:$REMOTE_DIR/

echo -e "${YELLOW}Building Docker images on EC2...${NC}"
ssh -i $SSH_KEY $EC2_HOST "cd $REMOTE_DIR && \
  docker build -f backend/Dockerfile -t llm-council-backend . && \
  docker build -t llm-council-frontend ./frontend"

if [ $? -ne 0 ]; then
  echo -e "${RED}Build failed! Reverting version...${NC}"
  echo "$VERSION" > VERSION
  cd frontend && npm version $VERSION --no-git-tag-version --allow-same-version && cd ..
  exit 1
fi

echo -e "${YELLOW}Restarting containers...${NC}"
ssh -i $SSH_KEY $EC2_HOST "cd $REMOTE_DIR && \
  docker rm -f llm-council-backend llm-council-frontend 2>/dev/null || true && \
  docker-compose up -d"

if [ $? -ne 0 ]; then
  echo -e "${RED}Deploy failed! Reverting version...${NC}"
  echo "$VERSION" > VERSION
  cd frontend && npm version $VERSION --no-git-tag-version --allow-same-version && cd ..
  exit 1
fi

echo -e "${YELLOW}Verifying deployment...${NC}"
sleep 3
HEALTH=$(ssh -i $SSH_KEY $EC2_HOST "curl -s http://localhost:8001/" 2>/dev/null)

if [[ $HEALTH == *"ok"* ]]; then
  echo -e "${GREEN}Deployment successful!${NC}"

  # Commit version bump
  git add VERSION frontend/package.json frontend/package-lock.json
  git commit -m "chore: bump version to $NEW_VERSION

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"

  echo -e "${GREEN}Version $NEW_VERSION deployed and committed!${NC}"
  echo -e "Run 'git push' to push the version bump."
else
  echo -e "${RED}Health check failed! Containers may not be running correctly.${NC}"
  echo "$VERSION" > VERSION
  cd frontend && npm version $VERSION --no-git-tag-version --allow-same-version && cd ..
  exit 1
fi
