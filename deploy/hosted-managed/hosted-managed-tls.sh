#!/usr/bin/env bash
set -euo pipefail

readonly CONFIG_ROOT="/etc/0al"
readonly DOMAIN_FILE="${CONFIG_ROOT}/hosted-managed-tls-domain"
readonly LETSENCRYPT_ROOT="/etc/letsencrypt"
readonly SECRET_ROOT="/srv/0al/secrets"
readonly INSTALLED_TOOL="/usr/local/sbin/0al-hosted-managed-tls"
readonly DEPLOY_HOOK="${LETSENCRYPT_ROOT}/renewal-hooks/deploy/0al-hosted-managed-tls"
readonly COMPOSE_FILE="/srv/0al/platform/docker-compose.hosted-managed-production.example.yml"
readonly COMPOSE_ENV="/etc/0al/hosted-managed-production.env"
readonly COMPOSE_PROJECT="platform-managed-production"

usage() {
  cat <<'EOF'
Usage:
  hosted-managed-tls.sh provision --domain <hostname> --email <address> --expected-ip <IPv4>
  hosted-managed-tls.sh sync
  hosted-managed-tls.sh status
EOF
}

fail() {
  echo "hosted-managed TLS: $*" >&2
  exit 2
}

require_root() {
  [[ "${EUID}" -eq 0 ]] || fail "run as root"
}

validate_domain() {
  local domain="$1"
  [[ "${#domain}" -le 253 ]] || fail "invalid domain"
  [[ "${domain}" =~ ^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$ ]] || \
    fail "invalid domain"
}

configured_domain() {
  [[ -f "${DOMAIN_FILE}" ]] || fail "missing ${DOMAIN_FILE}"
  local domain
  domain="$(tr -d '\r\n' < "${DOMAIN_FILE}")"
  validate_domain "${domain}"
  printf '%s\n' "${domain}"
}

install_domain_config() {
  local domain="$1"
  local temporary
  install -d -o root -g root -m 0755 "${CONFIG_ROOT}"
  temporary="$(mktemp "${CONFIG_ROOT}/.hosted-managed-tls-domain.XXXXXX")"
  printf '%s\n' "${domain}" > "${temporary}"
  chown root:root "${temporary}"
  chmod 0644 "${temporary}"
  mv -f "${temporary}" "${DOMAIN_FILE}"
}

install_renewal_hook() {
  install -d -o root -g root -m 0755 "$(dirname "${DEPLOY_HOOK}")"
  install -o root -g root -m 0755 "$0" "${INSTALLED_TOOL}"
  install -o root -g root -m 0755 "$0" "${DEPLOY_HOOK}"
}

sync_certificate() {
  require_root
  local domain lineage expected_lineage certificate private_key
  local certificate_temp private_key_temp renewed_domain matched=false
  domain="$(configured_domain)"
  expected_lineage="${LETSENCRYPT_ROOT}/live/${domain}"
  lineage="${RENEWED_LINEAGE:-${expected_lineage}}"

  if [[ -n "${RENEWED_DOMAINS:-}" ]]; then
    for renewed_domain in ${RENEWED_DOMAINS}; do
      [[ "${renewed_domain}" == "${domain}" ]] && matched=true
    done
    [[ "${matched}" == true ]] || exit 0
  fi

  [[ "$(realpath -m "${lineage}")" == "$(realpath -m "${expected_lineage}")" ]] || \
    fail "renewed lineage does not match configured domain"

  certificate="${lineage}/fullchain.pem"
  private_key="${lineage}/privkey.pem"
  [[ -r "${certificate}" && -r "${private_key}" ]] || fail "certificate lineage is incomplete"

  install -d -m 0750 "${SECRET_ROOT}"
  chown root:1000 "${SECRET_ROOT}"
  certificate_temp="$(mktemp "${SECRET_ROOT}/.tls-certificate.XXXXXX")"
  private_key_temp="$(mktemp "${SECRET_ROOT}/.tls-private-key.XXXXXX")"
  trap 'rm -f "${certificate_temp:-}" "${private_key_temp:-}"' EXIT
  install -m 0440 "${certificate}" "${certificate_temp}"
  install -m 0440 "${private_key}" "${private_key_temp}"
  chown root:1000 "${certificate_temp}" "${private_key_temp}"
  mv -f "${certificate_temp}" "${SECRET_ROOT}/tls-certificate.pem"
  mv -f "${private_key_temp}" "${SECRET_ROOT}/tls-private-key.pem"
  trap - EXIT

  if [[ -f "${COMPOSE_FILE}" && -f "${COMPOSE_ENV}" ]]; then
    local ingress_container
    ingress_container="$(docker compose --project-name "${COMPOSE_PROJECT}" \
      --env-file "${COMPOSE_ENV}" --file "${COMPOSE_FILE}" \
      ps --quiet managed-operation-ingress 2>/dev/null || true)"
    if [[ -n "${ingress_container}" ]]; then
      docker compose --project-name "${COMPOSE_PROJECT}" \
        --env-file "${COMPOSE_ENV}" --file "${COMPOSE_FILE}" \
        up --detach --no-deps --force-recreate managed-operation-ingress
    fi
  fi
}

provision_certificate() {
  require_root
  local domain="" email="" expected_ip="" resolved
  while [[ "$#" -gt 0 ]]; do
    case "$1" in
      --domain) domain="${2:-}"; shift 2 ;;
      --email) email="${2:-}"; shift 2 ;;
      --expected-ip) expected_ip="${2:-}"; shift 2 ;;
      *) fail "unknown provision argument: $1" ;;
    esac
  done
  validate_domain "${domain}"
  [[ "${email}" == *@*.* ]] || fail "a valid contact email is required"
  [[ "${expected_ip}" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || fail "expected IPv4 is required"
  command -v certbot >/dev/null || fail "certbot is not installed"

  resolved="$(getent ahostsv4 "${domain}" | awk '{print $1}' | sort -u)"
  grep -Fxq "${expected_ip}" <<<"${resolved}" || fail "domain does not resolve to expected IPv4"

  install_domain_config "${domain}"
  install_renewal_hook
  certbot certonly --standalone --non-interactive --agree-tos \
    --keep-until-expiring --preferred-challenges http \
    --cert-name "${domain}" --domain "${domain}" --email "${email}"
  "${INSTALLED_TOOL}" sync
  systemctl enable --now certbot.timer
  "${INSTALLED_TOOL}" status
}

certificate_status() {
  local domain certificate
  domain="$(configured_domain)"
  certificate="${SECRET_ROOT}/tls-certificate.pem"
  [[ -r "${certificate}" ]] || fail "runtime certificate is missing"
  openssl x509 -in "${certificate}" -noout -subject -issuer -dates
  openssl x509 -in "${certificate}" -checkend 2592000 -noout || \
    fail "certificate expires in less than 30 days"
  echo "domain=${domain}"
  echo "renewal_timer=$(systemctl is-enabled certbot.timer)"
}

command_name="${1:-}"
if [[ -z "${command_name}" && -n "${RENEWED_LINEAGE:-}" ]]; then
  command_name="sync"
else
  shift || true
fi

case "${command_name}" in
  provision) provision_certificate "$@" ;;
  sync) sync_certificate ;;
  status) certificate_status ;;
  *) usage; exit 2 ;;
esac
