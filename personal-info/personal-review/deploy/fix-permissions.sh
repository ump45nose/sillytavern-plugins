#!/bin/bash
# 修复当前部署及其明确登记的源码链接，不跟随其他链接、不修改容器数据卷。
set -euo pipefail
APP_ROOT=/vol2/1000/Docker/personal-review
SOURCE_ROOT=/vol1/1000/Code/personal-info/personal-review
TRIMACL=/usr/trim/bin/trimacl
[ "$(id -u)" -eq 0 ] || { echo "必须以 root 执行" >&2; exit 2; }
[ -x "$TRIMACL" ] && [ -f "$APP_ROOT/.env" ] || exit 2
backup=$(mktemp -d /vol2/1000/Docker/backups/personal-review/permissions-XXXXXXXX)
chmod 0700 "$backup"
# ACL 元数据单独备份，秘密内容不进入备份或输出。
getfattr -R -d -m 'system.trim_acl' "$SOURCE_ROOT" > "$backup/source-trim-acl.txt" 2>&1
getfacl -R -p "$SOURCE_ROOT" > "$backup/source-posix-acl.txt" 2>&1
for name in bin review schemas scripts; do
    target=$(readlink -f "$APP_ROOT/$name")
    [ "$target" = "$SOURCE_ROOT/$name" ] || { echo "拒绝未登记源码路径" >&2; exit 2; }
    "$TRIMACL" -b "$target"
    "$TRIMACL" -m e "$target"
    "$TRIMACL" -m a:o:rwxpDaAeEc:sfd "$target"
    "$TRIMACL" -m a:u:988:rxaec:sfd "$target"
    # NAS 的子项 Trim ACL 会覆盖 POSIX named ACL。只清理登记的非秘密源码区。
    while IFS= read -r -d '' file; do
        setfattr -x system.trim_acl "$file" 2>/dev/null || true
    done < <(find "$target" -mindepth 1 -xdev ! -type l -print0)
done
# 生产 .env、数据库、配置和运行数据的现有所有权保持独立。
runuser -u hermes -- "$APP_ROOT/bin/reviewctl" config validate >/dev/null
for name in data state logs tmp artifacts; do
    [ -d "$APP_ROOT/$name" ] || continue
    runuser -u hermes -- bash -c 'file=$(mktemp "$1/.permission-smoke.XXXXXX"); rm -f "$file"' _ "$APP_ROOT/$name"
done
printf '{"status":"ok","backup":"%s"}\n' "$backup"
