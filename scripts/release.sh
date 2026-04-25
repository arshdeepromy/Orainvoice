#!/bin/bash
# ==========================================================================
# OraInvoice — Release Script
# ==========================================================================
# Bumps the version based on commit messages since the last release,
# updates the VERSION file, commits, tags, and pushes.
#
# Usage:
#   ./scripts/release.sh              # Auto-detect bump from commits
#   ./scripts/release.sh patch        # Force patch bump (1.0.0 → 1.0.1)
#   ./scripts/release.sh minor        # Force minor bump (1.0.0 → 1.1.0)
#   ./scripts/release.sh major        # Force major bump (1.0.0 → 2.0.0)
#
# Commit message conventions (used for auto-detection):
#   feat: ...     → minor bump (new feature)
#   fix: ...      → patch bump (bug fix)
#   BREAKING: ... → major bump (breaking change)
#
# After running this, deploy to prod with:
#   ssh nerdy@192.168.1.90
#   cd /home/nerdy/invoicing && ./scripts/update.sh
# ==========================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# --------------------------------------------------------------------------
# Read current version
# --------------------------------------------------------------------------
VERSION_FILE="VERSION"

if [ ! -f "$VERSION_FILE" ]; then
    echo -e "${RED}VERSION file not found${NC}"
    exit 1
fi

CURRENT=$(cat "$VERSION_FILE" | tr -d '[:space:]')
IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT"

echo ""
echo "Current version: $CURRENT"
echo ""

# --------------------------------------------------------------------------
# Determine bump type
# --------------------------------------------------------------------------
BUMP_TYPE="${1:-auto}"

if [ "$BUMP_TYPE" = "auto" ]; then
    # Find the last version tag (if any)
    LAST_TAG=$(git tag -l "v*" --sort=-v:refname | head -1)

    if [ -n "$LAST_TAG" ]; then
        COMMITS=$(git log "$LAST_TAG"..HEAD --oneline 2>/dev/null)
    else
        COMMITS=$(git log --oneline -20 2>/dev/null)
    fi

    if echo "$COMMITS" | grep -qi "BREAKING"; then
        BUMP_TYPE="major"
    elif echo "$COMMITS" | grep -qi "^[a-f0-9]* feat"; then
        BUMP_TYPE="minor"
    else
        BUMP_TYPE="patch"
    fi

    echo "Auto-detected bump type: $BUMP_TYPE"
    echo "  (based on commits since ${LAST_TAG:-'beginning'})"
    echo ""
fi

# --------------------------------------------------------------------------
# Calculate new version
# --------------------------------------------------------------------------
case "$BUMP_TYPE" in
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
        echo -e "${RED}Invalid bump type: $BUMP_TYPE (use major, minor, or patch)${NC}"
        exit 1
        ;;
esac

NEW_VERSION="$MAJOR.$MINOR.$PATCH"
echo -e "New version: ${GREEN}$NEW_VERSION${NC}"
echo ""

# --------------------------------------------------------------------------
# Confirm
# --------------------------------------------------------------------------
read -p "Release v$NEW_VERSION? (y/n) " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    exit 0
fi

# --------------------------------------------------------------------------
# Update VERSION file
# --------------------------------------------------------------------------
echo "$NEW_VERSION" > "$VERSION_FILE"

# --------------------------------------------------------------------------
# Generate changelog entry
# --------------------------------------------------------------------------
CHANGELOG_ENTRY="## v$NEW_VERSION — $(date +%Y-%m-%d)"
if [ -n "$LAST_TAG" ]; then
    CHANGELOG_ENTRY="$CHANGELOG_ENTRY"$'\n\n'
    CHANGELOG_ENTRY="$CHANGELOG_ENTRY$(git log "$LAST_TAG"..HEAD --pretty=format:'- %s' 2>/dev/null)"
else
    CHANGELOG_ENTRY="$CHANGELOG_ENTRY"$'\n\n'"- Initial release"
fi

# Prepend to CHANGELOG.md (create if doesn't exist)
if [ -f "CHANGELOG.md" ]; then
    echo -e "$CHANGELOG_ENTRY\n\n$(cat CHANGELOG.md)" > CHANGELOG.md
else
    echo -e "# Changelog\n\n$CHANGELOG_ENTRY" > CHANGELOG.md
fi

echo ""
echo "$CHANGELOG_ENTRY"
echo ""

# --------------------------------------------------------------------------
# Commit, tag, and push
# --------------------------------------------------------------------------
git add VERSION CHANGELOG.md
git commit -m "release: v$NEW_VERSION"
git tag -a "v$NEW_VERSION" -m "Release v$NEW_VERSION"
git push origin main
git push origin "v$NEW_VERSION"

echo ""
echo -e "${GREEN}Released v$NEW_VERSION${NC}"
echo ""
echo "Next steps:"
echo "  1. SSH into prod:  ssh nerdy@192.168.1.90"
echo "  2. Run update:     cd /home/nerdy/invoicing && ./scripts/update.sh"
