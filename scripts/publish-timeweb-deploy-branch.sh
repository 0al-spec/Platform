#!/usr/bin/env bash
set -euo pipefail

generated_dir="${1:-}"
deploy_branch="${PLATFORM_TIMEWEB_DEPLOY_BRANCH:-timeweb-deploy}"
remote="${PLATFORM_TIMEWEB_DEPLOY_REMOTE:-origin}"
release_commit="${PLATFORM_RELEASE_COMMIT:-$(git rev-parse HEAD 2>/dev/null || echo unknown)}"
artifact_base_url="${TIMEWEB_REQUIRED_ARTIFACT_BASE_URL:-https://specgraph.tech}"
default_team_decision_log_artifact_base_url="${artifact_base_url%/}/workspaces/team-decision-log"
default_hosted_operation_canary_artifact_base_url="${artifact_base_url%/}/workspaces/hosted-operation-canary"
raw_product_workspace_artifact_base_url="${TIMEWEB_REQUIRED_PRODUCT_WORKSPACE_ARTIFACT_BASE_URL:-${TIMEWEB_REQUIRED_TEAM_DECISION_LOG_ARTIFACT_BASE_URL:-}}"
product_workspace_artifact_base_url_args=()
if [[ -z "$raw_product_workspace_artifact_base_url" ]]; then
  product_workspace_artifact_base_url_args+=(
    --product-workspace-artifact-base-url
    "team-decision-log=$default_team_decision_log_artifact_base_url"
    --product-workspace-artifact-base-url
    "hosted-operation-canary=$default_hosted_operation_canary_artifact_base_url"
  )
elif [[ "$raw_product_workspace_artifact_base_url" != *=* && "${raw_product_workspace_artifact_base_url%/}" == "${artifact_base_url%/}" ]]; then
  product_workspace_artifact_base_url_args+=(
    --product-workspace-artifact-base-url
    "$default_team_decision_log_artifact_base_url"
  )
else
  product_workspace_artifact_base_url_args+=(
    --product-workspace-artifact-base-url
    "$raw_product_workspace_artifact_base_url"
  )
fi
specpm_registry_url="${TIMEWEB_REQUIRED_SPECPM_REGISTRY_URL:-https://specpm.dev}"

if [[ -z "$generated_dir" ]]; then
  echo "Usage: scripts/publish-timeweb-deploy-branch.sh GENERATED_DIR" >&2
  exit 2
fi

if [[ ! -d "$generated_dir" ]]; then
  echo "Generated deploy directory does not exist: $generated_dir" >&2
  exit 2
fi

repo_root="$(git rev-parse --show-toplevel)"
generated_dir="$(cd "$generated_dir" && pwd -P)"
worktree="$(mktemp -d "${TMPDIR:-/tmp}/platform-timeweb-publish.XXXXXX")"

cleanup() {
  cd "$repo_root"
  git worktree remove --force "$worktree" >/dev/null 2>&1 || true
  rm -rf "$worktree"
}
trap cleanup EXIT

"$repo_root/scripts/platform.py" deploy timeweb-validate \
  --path "$generated_dir" \
  --artifact-base-url "$artifact_base_url" \
  "${product_workspace_artifact_base_url_args[@]}" \
  --specpm-registry-url "$specpm_registry_url"

git fetch --quiet "$remote" "$deploy_branch" 2>/dev/null || true

if git show-ref --verify --quiet "refs/remotes/$remote/$deploy_branch"; then
  git worktree add --quiet --detach "$worktree" "$remote/$deploy_branch"
else
  git worktree add --quiet --detach "$worktree"
  (
    cd "$worktree"
    git checkout --quiet --orphan "publish-${deploy_branch}-$$"
  )
fi

find "$worktree" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
cp -R "$generated_dir"/. "$worktree"/

"$repo_root/scripts/platform.py" deploy timeweb-validate \
  --path "$worktree" \
  --artifact-base-url "$artifact_base_url" \
  "${product_workspace_artifact_base_url_args[@]}" \
  --specpm-registry-url "$specpm_registry_url"

(
  cd "$worktree"
  git add -A
  if git diff --cached --quiet; then
    echo "Platform Timeweb deploy branch already matches generated manifest."
    exit 0
  fi

  git commit --quiet -m "Publish Platform Timeweb deploy manifest for ${release_commit}"
  git push "$remote" "HEAD:$deploy_branch"
)

echo "Published $deploy_branch from generated Platform manifest."
