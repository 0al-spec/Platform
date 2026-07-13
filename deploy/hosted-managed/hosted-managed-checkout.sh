#!/usr/bin/env bash
set +x
set -euo pipefail

readonly RUNTIME_UID=1000
readonly RUNTIME_GID=1000
readonly RUNTIME_HOME="/srv/0al/.runtime-home"
readonly INSTALLED_TOOL="/usr/local/sbin/0al-hosted-managed-checkout"

usage() {
  cat <<'EOF'
Usage:
  hosted-managed-checkout.sh install
  hosted-managed-checkout.sh status --repository <platform|specgraph>
  hosted-managed-checkout.sh sync --repository <platform|specgraph> --commit <40-character SHA-1>
EOF
}

fail() {
  echo "hosted-managed checkout: $*" >&2
  exit 2
}

require_root() {
  [[ "${EUID}" -eq 0 ]] || fail "run as root"
}

repository_contract() {
  case "$1" in
    platform)
      REPOSITORY_ROOT="/srv/0al/platform"
      REPOSITORY_URL="https://github.com/0al-spec/Platform.git"
      ;;
    specgraph)
      REPOSITORY_ROOT="/srv/0al/specgraph"
      REPOSITORY_URL="https://github.com/0al-spec/SpecGraph.git"
      ;;
    *) fail "repository must be platform or specgraph" ;;
  esac
  readonly REPOSITORY_ROOT REPOSITORY_URL
}

require_runtime_boundary() {
  command -v git >/dev/null || fail "git is not installed"
  command -v setpriv >/dev/null || fail "setpriv is not installed"
  [[ -d "${RUNTIME_HOME}" && ! -L "${RUNTIME_HOME}" ]] || \
    fail "${RUNTIME_HOME} must be a real directory"
  [[ "$(stat -c '%u:%g:%a' "${RUNTIME_HOME}")" == "${RUNTIME_UID}:${RUNTIME_GID}:700" ]] || \
    fail "${RUNTIME_HOME} must have owner ${RUNTIME_UID}:${RUNTIME_GID} and mode 0700"
  [[ -d "${REPOSITORY_ROOT}" && ! -L "${REPOSITORY_ROOT}" ]] || \
    fail "${REPOSITORY_ROOT} must be a real directory"
  [[ "$(stat -c '%u:%g' "${REPOSITORY_ROOT}")" == "${RUNTIME_UID}:${RUNTIME_GID}" ]] || \
    fail "${REPOSITORY_ROOT} must have owner ${RUNTIME_UID}:${RUNTIME_GID}"
}

git_as_runtime() {
  setpriv --reuid="${RUNTIME_UID}" --regid="${RUNTIME_GID}" --clear-groups \
    env HOME="${RUNTIME_HOME}" XDG_CONFIG_HOME="${RUNTIME_HOME}/.config" \
    GIT_CONFIG_NOSYSTEM=1 git "$@"
}

require_checkout_contract() {
  [[ -d "${REPOSITORY_ROOT}/.git" && ! -L "${REPOSITORY_ROOT}/.git" ]] || \
    fail "${REPOSITORY_ROOT} is not a Git checkout"
  local remote
  remote="$(git_as_runtime -C "${REPOSITORY_ROOT}" remote get-url origin)"
  [[ "${remote}" == "${REPOSITORY_URL}" ]] || fail "origin URL does not match the repository contract"
}

require_clean_checkout() {
  [[ -z "$(git_as_runtime -C "${REPOSITORY_ROOT}" status --porcelain --untracked-files=all)" ]] || \
    fail "repository worktree is not clean"
}

install_helper() {
  require_root
  install -o root -g root -m 0755 "$0" "${INSTALLED_TOOL}"
  echo "hosted-managed checkout: installed ${INSTALLED_TOOL}"
}

checkout_status() {
  require_root
  require_runtime_boundary
  require_checkout_contract
  require_clean_checkout
  local commit
  commit="$(git_as_runtime -C "${REPOSITORY_ROOT}" rev-parse HEAD)"
  [[ "${commit}" =~ ^[0-9a-f]{40}$ ]] || fail "checkout HEAD is not a full commit id"
  echo "repository=${repository_name}"
  echo "commit=${commit}"
  echo "worktree=clean"
}

sync_checkout() {
  require_root
  [[ "${commit}" =~ ^[0-9a-f]{40}$ ]] || fail "commit must be a full lowercase SHA-1"
  require_runtime_boundary
  local fresh_clone="false"
  if [[ ! -d "${REPOSITORY_ROOT}/.git" ]]; then
    [[ -z "$(find "${REPOSITORY_ROOT}" -mindepth 1 -maxdepth 1 -print -quit)" ]] || \
      fail "refusing to initialize a non-empty repository root"
    git_as_runtime clone --no-checkout "${REPOSITORY_URL}" "${REPOSITORY_ROOT}"
    fresh_clone="true"
  fi
  require_checkout_contract
  if [[ "${fresh_clone}" != "true" ]]; then
    require_clean_checkout
  fi
  git_as_runtime -C "${REPOSITORY_ROOT}" fetch --no-tags origin main
  git_as_runtime -C "${REPOSITORY_ROOT}" cat-file -e "${commit}^{commit}"
  git_as_runtime -C "${REPOSITORY_ROOT}" checkout --detach "${commit}"
  [[ "$(git_as_runtime -C "${REPOSITORY_ROOT}" rev-parse HEAD)" == "${commit}" ]] || \
    fail "checkout did not reach the requested commit"
  checkout_status
}

command_name="${1:-}"
shift || true

if [[ "${command_name}" == "install" ]]; then
  [[ "$#" -eq 0 ]] || fail "install does not accept arguments"
  install_helper
  exit 0
fi

repository_name=""
commit=""
while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --repository) repository_name="${2:-}"; shift 2 ;;
    --commit) commit="${2:-}"; shift 2 ;;
    *) fail "unknown argument: $1" ;;
  esac
done
[[ -n "${repository_name}" ]] || fail "--repository is required"
repository_contract "${repository_name}"

case "${command_name}" in
  status)
    [[ -z "${commit}" ]] || fail "status does not accept --commit"
    checkout_status
    ;;
  sync)
    [[ -n "${commit}" ]] || fail "sync requires --commit"
    sync_checkout
    ;;
  *) usage; exit 2 ;;
esac
