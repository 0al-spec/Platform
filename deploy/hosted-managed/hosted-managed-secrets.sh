#!/usr/bin/env bash
set +x
set -euo pipefail

readonly SECRET_ROOT="/srv/0al/secrets"
readonly SERVICE_TOKEN_FILE="${SECRET_ROOT}/service-token"
readonly DATABASE_PASSWORD_FILE="${SECRET_ROOT}/database-password"
readonly DATABASE_URL_FILE="${SECRET_ROOT}/database-url"
readonly GITHUB_TOKEN_FILE="${SECRET_ROOT}/github-token"

usage() {
  cat <<'EOF'
Usage:
  hosted-managed-secrets.sh provision
  hosted-managed-secrets.sh status

Provision reads three independent credentials from a controlling terminal.
Secret values are never accepted as arguments or printed.
EOF
}

fail() {
  echo "hosted-managed secrets: $*" >&2
  exit 2
}

require_root() {
  [[ "${EUID}" -eq 0 ]] || fail "run as root"
}

require_secret_root() {
  [[ -d "${SECRET_ROOT}" && ! -L "${SECRET_ROOT}" ]] || \
    fail "${SECRET_ROOT} must be a real directory"
  [[ "$(stat -c '%u:%g:%a' "${SECRET_ROOT}")" == "0:1000:750" ]] || \
    fail "${SECRET_ROOT} must have owner 0:1000 and mode 0750"
}

read_hidden() {
  local prompt="$1" destination="$2" value
  IFS= read -r -s -p "${prompt}: " value
  printf '\n' >&2
  [[ -n "${value}" ]] || fail "${prompt} must not be empty"
  printf -v "${destination}" '%s' "${value}"
  unset value
}

validate_values() {
  local database_password="$1" service_token="$2" github_token="$3"
  [[ "${database_password}" =~ ^[0-9a-f]{64}$ ]] || \
    fail "PostgreSQL password must be the 64-character lowercase hex value created for this deployment"
  [[ "${service_token}" =~ ^[0-9a-f]{64}$ ]] || \
    fail "Platform bearer token must be the 64-character lowercase hex value created for this deployment"
  [[ "${database_password}" != "${service_token}" ]] || \
    fail "database and service credentials must be independent"
  [[ "${github_token}" =~ ^github_pat_[A-Za-z0-9_]{20,}$ ]] || \
    fail "GitHub token must be a fine-grained personal access token"
}

assert_new_targets() {
  local path
  for path in \
    "${SERVICE_TOKEN_FILE}" \
    "${DATABASE_PASSWORD_FILE}" \
    "${DATABASE_URL_FILE}" \
    "${GITHUB_TOKEN_FILE}"; do
    [[ ! -e "${path}" && ! -L "${path}" ]] || \
      fail "refusing to overwrite existing ${path}"
  done
}

provision_secrets() {
  require_root
  [[ -t 0 && -t 1 ]] || fail "provision requires an interactive terminal"
  require_secret_root
  assert_new_targets

  local database_password="" service_token="" github_token=""
  local service_temp="" password_temp="" url_temp="" github_temp=""
  read_hidden "PostgreSQL password" database_password
  read_hidden "Platform bearer token" service_token
  read_hidden "GitHub review-status token" github_token
  validate_values "${database_password}" "${service_token}" "${github_token}"

  umask 077
  service_temp="$(mktemp "${SECRET_ROOT}/.service-token.XXXXXX")"
  password_temp="$(mktemp "${SECRET_ROOT}/.database-password.XXXXXX")"
  url_temp="$(mktemp "${SECRET_ROOT}/.database-url.XXXXXX")"
  github_temp="$(mktemp "${SECRET_ROOT}/.github-token.XXXXXX")"
  trap 'rm -f "${service_temp:-}" "${password_temp:-}" "${url_temp:-}" "${github_temp:-}"' EXIT

  printf '%s' "${service_token}" > "${service_temp}"
  printf '%s' "${database_password}" > "${password_temp}"
  printf 'postgresql://managed_operations:%s@managed-operation-postgres:5432/managed_operations' \
    "${database_password}" > "${url_temp}"
  printf '%s' "${github_token}" > "${github_temp}"
  chown 0:1000 "${service_temp}" "${password_temp}" "${url_temp}" "${github_temp}"
  chmod 0440 "${service_temp}" "${password_temp}" "${url_temp}" "${github_temp}"

  mv "${service_temp}" "${SERVICE_TOKEN_FILE}"
  mv "${password_temp}" "${DATABASE_PASSWORD_FILE}"
  mv "${url_temp}" "${DATABASE_URL_FILE}"
  mv "${github_temp}" "${GITHUB_TOKEN_FILE}"
  trap - EXIT
  unset database_password service_token github_token

  echo "hosted-managed secrets: provisioned four runtime files"
  secret_status
}

validate_secret_file() {
  local path="$1"
  [[ -f "${path}" && ! -L "${path}" ]] || fail "missing regular file ${path}"
  [[ "$(stat -c '%u:%g:%a' "${path}")" == "0:1000:440" ]] || \
    fail "${path} must have owner 0:1000 and mode 0440"
}

secret_status() {
  require_root
  require_secret_root
  local database_password service_token github_token database_url expected_url
  local path
  for path in \
    "${SERVICE_TOKEN_FILE}" \
    "${DATABASE_PASSWORD_FILE}" \
    "${DATABASE_URL_FILE}" \
    "${GITHUB_TOKEN_FILE}"; do
    validate_secret_file "${path}"
  done

  service_token="$(<"${SERVICE_TOKEN_FILE}")"
  database_password="$(<"${DATABASE_PASSWORD_FILE}")"
  database_url="$(<"${DATABASE_URL_FILE}")"
  github_token="$(<"${GITHUB_TOKEN_FILE}")"
  validate_values "${database_password}" "${service_token}" "${github_token}"
  expected_url="postgresql://managed_operations:${database_password}@managed-operation-postgres:5432/managed_operations"
  [[ "${database_url}" == "${expected_url}" ]] || \
    fail "database URL does not match the provisioned database credential"
  unset database_password service_token github_token database_url expected_url

  echo "service-token=ready"
  echo "database-password=ready"
  echo "database-url=ready"
  echo "github-token=ready"
}

command_name="${1:-}"
shift || true
[[ "$#" -eq 0 ]] || fail "unexpected arguments"

case "${command_name}" in
  provision) provision_secrets ;;
  status) secret_status ;;
  *) usage; exit 2 ;;
esac
