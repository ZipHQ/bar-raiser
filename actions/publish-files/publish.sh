#!/usr/bin/env bash
set -euo pipefail

git -C upload-target-repo config user.email "$GIT_USER_EMAIL"
git -C upload-target-repo config user.name "$GIT_USER_NAME"
git -C upload-target-repo config --unset http.https://github.com/.extraheader || true
git -C upload-target-repo remote set-url origin "${TARGET_REPO_URL:-https://$CUSTOM_GH_TOKEN@github.com/$TARGET_REPO.git}"

for attempt in {1..5}; do
  git -C upload-target-repo fetch origin master
  git -C upload-target-repo reset --hard FETCH_HEAD
  rm -rf "upload-target-repo/$TARGET_REPO_PATH"
  cp -r "$LOCAL_REPO_PATH" "upload-target-repo/$TARGET_REPO_PATH"
  git -C upload-target-repo add -A -- "$TARGET_REPO_PATH"

  if git -C upload-target-repo diff --cached --quiet; then
    exit 0
  fi

  git -C upload-target-repo commit -m "Update $TARGET_REPO_PATH reports from $GITHUB_REPOSITORY $GITHUB_SHA"
  if git -C upload-target-repo push origin HEAD:master; then
    exit 0
  fi

  sleep "$attempt"
done

echo "Could not publish $TARGET_REPO_PATH after 5 attempts" >&2
exit 1
