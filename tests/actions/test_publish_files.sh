#!/usr/bin/env bash
set -euo pipefail

repo_root=$(git rev-parse --show-toplevel)
test_dir=$(mktemp -d)
trap 'rm -rf "$test_dir"' EXIT

git init --bare -q "$test_dir/remote.git"
git clone -q "$test_dir/remote.git" "$test_dir/seed"
git -C "$test_dir/seed" config user.name Test
git -C "$test_dir/seed" config user.email test@example.com
mkdir -p "$test_dir/seed/docs/htmlcov"
echo old > "$test_dir/seed/docs/htmlcov/index.html"
git -C "$test_dir/seed" add .
git -C "$test_dir/seed" commit -qm 'Initial report'
git -C "$test_dir/seed" push -q origin HEAD:master

git clone -q --branch master "$test_dir/remote.git" "$test_dir/upload-target-repo"
git clone -q --branch master "$test_dir/remote.git" "$test_dir/racer"
git -C "$test_dir/racer" config user.name Test
git -C "$test_dir/racer" config user.email test@example.com
mkdir -p "$test_dir/new-report"
echo new > "$test_dir/new-report/index.html"

cat > "$test_dir/upload-target-repo/.git/hooks/pre-push" <<EOF
#!/usr/bin/env bash
set -euo pipefail
if [ ! -f "$test_dir/raced" ]; then
  touch "$test_dir/raced"
  echo competing > "$test_dir/racer/docs/htmlcov/index.html"
  git -C "$test_dir/racer" add .
  git -C "$test_dir/racer" commit -qm 'Competing report'
  git -C "$test_dir/racer" push -q origin HEAD:master
fi
EOF
chmod +x "$test_dir/upload-target-repo/.git/hooks/pre-push"

(
  cd "$test_dir"
  CUSTOM_GH_TOKEN=unused \
  TARGET_REPO=unused \
  TARGET_REPO_URL="$test_dir/remote.git" \
  TARGET_REPO_PATH=docs/htmlcov \
  LOCAL_REPO_PATH="$test_dir/new-report" \
  GIT_USER_NAME=Test \
  GIT_USER_EMAIL=test@example.com \
  GITHUB_REPOSITORY=example/repo \
  GITHUB_SHA=123456 \
  bash "$repo_root/actions/publish-files/publish.sh"
)

git -C "$test_dir/seed" fetch -q origin master
actual=$(git -C "$test_dir/seed" show FETCH_HEAD:docs/htmlcov/index.html)
test "$actual" = new
test -f "$test_dir/raced"
