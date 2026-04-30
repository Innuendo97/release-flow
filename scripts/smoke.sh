#!/usr/bin/env bash
# scripts/smoke.sh — manual smoke test against real GitLab
#
# Requires:
#   GITLAB_TOKEN env var
#   A disposable test repo at $SMOKE_REPO_URL with develop + master branches
#
# Usage:
#   SMOKE_REPO_URL=git@gitlab.example:me/release-flow-smoke.git ./scripts/smoke.sh
set -euo pipefail

: "${GITLAB_TOKEN:?GITLAB_TOKEN env var required}"
: "${SMOKE_REPO_URL:?SMOKE_REPO_URL env var required}"

WORK=$(mktemp -d)
cd "$WORK"
git clone "$SMOKE_REPO_URL" repo
cd repo
git checkout develop

# Reset to a known SNAPSHOT version
cat > pom.xml <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<project>
    <artifactId>smoke-test</artifactId>
    <version>0.0.1-SNAPSHOT</version>
</project>
EOF
git add pom.xml
git commit -m "smoke: reset to 0.0.1-SNAPSHOT" || true
git push origin develop

# Run release-flow with -y (no confirmations)
release-flow --release-version 0.0.1 --next-version 0.0.2-SNAPSHOT -y

# Verify outcome
[[ "$(grep -oE '[0-9]+\.[0-9]+\.[0-9]+(-SNAPSHOT)?' pom.xml | head -1)" == "0.0.2-SNAPSHOT" ]] \
    || { echo "FAIL: version not bumped"; exit 1; }

echo "smoke test passed"

# Cleanup: delete the release branch we created (allowed, since it's release/* not develop/master)
git push origin --delete release/release-0.0.1 || true

cd /
rm -rf "$WORK"
