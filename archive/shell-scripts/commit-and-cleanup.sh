#!/bin/bash
#
# GRAPE Signal Recorder - Safe Cleanup with Git Commits
# 
# This script handles the cleanup in stages with git commits for easy rollback
#
# Usage:
#   ./commit-and-cleanup.sh
#

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}================================================${NC}"
echo -e "${GREEN}  GRAPE Signal Recorder - Safe Cleanup${NC}"
echo -e "${GREEN}================================================${NC}"
echo ""

# Check if we're in a git repository
if [ ! -d .git ]; then
    echo -e "${RED}Error: Not in a git repository${NC}"
    exit 1
fi

# Check for uncommitted changes (excluding our new files)
echo -e "${BLUE}Checking git status...${NC}"
if git diff --quiet && git diff --cached --quiet 2>/dev/null; then
    CLEAN_START=true
else
    CLEAN_START=false
    echo -e "${YELLOW}Warning: You have uncommitted changes${NC}"
    git status --short
    echo ""
    echo -e "${YELLOW}These changes will be included in the commits.${NC}"
    echo -e "${YELLOW}Press Enter to continue, or Ctrl+C to abort and commit them separately first.${NC}"
    read -r
fi

echo ""
echo -e "${GREEN}=== STAGE 1: Commit Cleanup Infrastructure ===${NC}"
echo ""
echo "This will commit:"
echo "  - archive/ directory structure"
echo "  - cleanup-codebase.sh script"
echo "  - CLEANUP_SUMMARY.md documentation"
echo ""

# Stage the cleanup infrastructure
git add archive/ cleanup-codebase.sh CLEANUP_SUMMARY.md

# Show what will be committed
echo -e "${BLUE}Files to be committed:${NC}"
git diff --cached --name-status | grep -E "(archive/|cleanup-codebase.sh|CLEANUP_SUMMARY.md)" || true
echo ""

read -p "Commit cleanup infrastructure? [y/N] " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Aborted by user${NC}"
    git reset HEAD
    exit 1
fi

# Commit stage 1
git commit -m "Add codebase cleanup infrastructure

- Created archive/ directory structure with READMEs
- Added cleanup-codebase.sh script with dry-run support
- Added CLEANUP_SUMMARY.md documentation
- Preserves development history while decluttering workspace"

echo -e "${GREEN}✓ Stage 1 committed${NC}"
echo ""

# Ask about pushing
read -p "Push to remote? [y/N] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    git push
    echo -e "${GREEN}✓ Pushed to remote${NC}"
else
    echo -e "${YELLOW}Skipped push (remember to push later)${NC}"
fi

echo ""
echo -e "${GREEN}=== STAGE 2: Preview Cleanup ===${NC}"
echo ""
echo "Running dry-run to show what will be archived..."
echo ""

./cleanup-codebase.sh --dry-run | head -60
echo ""
echo "... (see full output above)"
echo ""

read -p "Proceed with cleanup? [y/N] " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Cleanup aborted. Cleanup infrastructure is committed and ready.${NC}"
    echo "You can run './cleanup-codebase.sh' manually later."
    exit 0
fi

echo ""
echo -e "${GREEN}=== Executing Cleanup ===${NC}"
echo ""

# Execute cleanup
./cleanup-codebase.sh

echo ""
echo -e "${GREEN}=== STAGE 3: Commit the Cleanup ===${NC}"
echo ""

# Show what changed
echo -e "${BLUE}Files moved:${NC}"
git status --short | head -20
TOTAL_CHANGES=$(git status --short | wc -l)
if [ "$TOTAL_CHANGES" -gt 20 ]; then
    echo "... and $((TOTAL_CHANGES - 20)) more files"
fi
echo ""

read -p "Commit the cleanup? [y/N] " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Cleanup executed but not committed${NC}"
    echo "Run 'git status' to review changes"
    echo "Commit with: git add -A && git commit -m 'Archive development artifacts'"
    exit 0
fi

# Stage all changes
git add -A

# Commit stage 3
git commit -m "Archive development artifacts to cleanup workspace

Moved ~70 development files to organized archive:
- Historical bug fix docs → archive/dev-history/
- Test scripts → archive/test-scripts/
- Development shell scripts → archive/shell-scripts/
- Legacy code → archive/legacy-code/
- Session notes → docs/archive/

Root directory reduced from ~80 files to ~30 essential files.
All archived files preserved for reference.

See CLEANUP_SUMMARY.md for complete details."

echo -e "${GREEN}✓ Cleanup committed${NC}"
echo ""

# Ask about pushing
read -p "Push to remote? [y/N] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    git push
    echo -e "${GREEN}✓ Pushed to remote${NC}"
else
    echo -e "${YELLOW}Skipped push (remember to push later)${NC}"
fi

echo ""
echo -e "${GREEN}================================================${NC}"
echo -e "${GREEN}  Cleanup Complete!${NC}"
echo -e "${GREEN}================================================${NC}"
echo ""
echo "Summary:"
echo "  ✓ Cleanup infrastructure committed"
echo "  ✓ Development artifacts archived"
echo "  ✓ Workspace decluttered"
echo ""
echo "Archive locations:"
echo "  - archive/dev-history/     (historical docs)"
echo "  - archive/test-scripts/    (dev tests)"
echo "  - archive/shell-scripts/   (dev scripts)"
echo "  - archive/legacy-code/     (old code)"
echo "  - docs/archive/            (session notes)"
echo ""
echo "To undo cleanup: git revert HEAD"
echo "To undo everything: git reset --hard HEAD~2"
echo ""

exit 0
