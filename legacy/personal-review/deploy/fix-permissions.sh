#!/bin/bash
# 修复 FnOS/Trim NAS 升级后 personal-review 被父目录 ACL 污染的问题。
set -euo pipefail

APP_ROOT=/vol2/1000/Docker/personal-review
BACKUP_ROOT=/vol2/1000/Docker/backups/personal-review
TRIMACL=/usr/trim/bin/trimacl
HERMES_UID=$(id -u hermes)
YUWK_UID=$(id -u yuwk)

# require_runtime：校验执行身份、工具和目标，避免把递归权限操作应用到错误目录。
require_runtime() {
  if [ "$(id -u)" -ne 0 ]; then
    echo "必须以 root 执行" >&2
    exit 2
  fi
  if [ ! -x "$TRIMACL" ]; then
    echo "缺少 FnOS Trim ACL 工具：$TRIMACL" >&2
    exit 2
  fi
  if [ ! -d "$APP_ROOT/review" ] || [ ! -f "$APP_ROOT/.env" ]; then
    echo "拒绝处理结构不完整的项目目录：$APP_ROOT" >&2
    exit 2
  fi
}

# backup_permissions：只保存权限和 ACL 元数据，不复制或输出 .env 内容。
backup_permissions() {
  local stamp target
  stamp=$(date '+%Y%m%d-%H%M%S')
  target="$BACKUP_ROOT/${stamp}-permissions-before"
  install -d -o root -g root -m 0700 "$target"
  getfattr -R -d -m 'system.trim_acl' "$APP_ROOT" >"$target/trim-acl.txt" 2>&1 || true
  getfacl -R -p "$APP_ROOT" >"$target/posix-acl.txt" 2>&1 || true
  find "$APP_ROOT" -xdev -printf '%m %u:%g %y %p\n' >"$target/modes.txt"
  printf '%s\n' "$target"
}

# normalize_posix：建立静态代码与运行数据的基础属主和模式。
normalize_posix() {
  local name target
  setfacl -R -b "$APP_ROOT"
  setfacl -R -k "$APP_ROOT" 2>/dev/null || true
  while IFS= read -r -d '' target; do
    setfattr -x system.trim_acl "$target" 2>/dev/null || true
  done < <(find "$APP_ROOT" -xdev -print0)

  chown yuwk:Users "$APP_ROOT"
  chmod 0750 "$APP_ROOT"
  for name in bin config deploy review schemas scripts tests; do
    target="$APP_ROOT/$name"
    [ -e "$target" ] || continue
    chown -R yuwk:Users "$target"
    find "$target" -type d -exec chmod 0750 {} +
    find "$target" -type f -exec chmod 0640 {} +
  done
  for name in .env.example README.md pyproject.toml; do
    target="$APP_ROOT/$name"
    [ -f "$target" ] || continue
    chown yuwk:Users "$target"
    chmod 0640 "$target"
  done
  chmod 0750 "$APP_ROOT/bin/reviewctl" "$APP_ROOT/deploy/fix-permissions.sh"
  find "$APP_ROOT/scripts" -maxdepth 1 -type f -name '*.py' -exec chmod 0750 {} +
  find "$APP_ROOT/deploy/hermes-scripts" -maxdepth 1 -type f -name '*.sh' -exec chmod 0750 {} +

  for name in data state logs tmp artifacts; do
    target="$APP_ROOT/$name"
    [ -d "$target" ] || continue
    chown -R hermes:hermes "$target"
    find "$target" -type d -exec chmod 0700 {} +
    find "$target" -type f -exec chmod 0600 {} +
  done
  chown hermes:hermes "$APP_ROOT/.env"
  chmod 0600 "$APP_ROOT/.env"
}

# apply_trim_acl：阻断 Docker 父目录 ACL，并给静态区和运行区设置不同权限。
apply_trim_acl() {
  local name target
  "$TRIMACL" -m e "$APP_ROOT"
  "$TRIMACL" -m a:o:rwxpDaAeEc:sfd "$APP_ROOT"
  "$TRIMACL" -m a:u:0:rwxpDaAeEc:sfd "$APP_ROOT"
  "$TRIMACL" -m "a:u:${HERMES_UID}:rxaec:sfd" "$APP_ROOT"

  for name in data state logs tmp artifacts; do
    target="$APP_ROOT/$name"
    [ -d "$target" ] || continue
    "$TRIMACL" -m e "$target"
    "$TRIMACL" -m a:o:rwxpDaAeEc:sfd "$target"
    "$TRIMACL" -m a:u:0:rwxpDaAeEc:sfd "$target"
    "$TRIMACL" -m "a:u:${HERMES_UID}:rwxpDaAeEc:sfd" "$target"
    "$TRIMACL" -m "a:u:${YUWK_UID}:rwxpDaAeEc:sfd" "$target"
  done

  # chmod 会生成本地 Trim ACL；清掉子项 ACL 后才能继承上面的受控模型。
  while IFS= read -r -d '' target; do
    case "$target" in
      "$APP_ROOT/.env"|"$APP_ROOT/data"|"$APP_ROOT/state"|"$APP_ROOT/logs"|"$APP_ROOT/tmp"|"$APP_ROOT/artifacts") continue ;;
    esac
    setfattr -x system.trim_acl "$target" 2>/dev/null || true
  done < <(find "$APP_ROOT" -mindepth 1 -xdev -print0)
}

# verify_runtime：使用真实 Hermes 身份验证配置读取和所有运行目录写入能力。
verify_runtime() {
  local name
  runuser -u hermes -- "$APP_ROOT/bin/reviewctl" config validate >/dev/null
  for name in state logs data tmp artifacts; do
    runuser -u hermes -- bash -c 'file=$(mktemp "$1/.permission-smoke.XXXXXX"); rm -f "$file"' _ "$APP_ROOT/$name"
  done
}

require_runtime
backup_path=$(backup_permissions)
normalize_posix
apply_trim_acl
verify_runtime
printf '{"status":"ok","backup":"%s"}\n' "$backup_path"
