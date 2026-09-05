-- 将 CRM 的 Nginx Proxy Manager 主机配置对齐到已通过 ChatGPT 验收的 SmartSearch 配置。
-- 关闭 NPM 自动生成的 WebSocket 与 block-exploits 片段，由 advanced_config 统一接管 location /。
UPDATE proxy_host
SET allow_websocket_upgrade = 0,
    block_exploits = 0,
    advanced_config = 'location / {
    access_log off;
    error_log /dev/null crit;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    proxy_buffering off;
    proxy_request_buffering off;
    proxy_cache off;
    proxy_connect_timeout 30s;
    proxy_read_timeout 900s;
    proxy_send_timeout 900s;
    send_timeout 900s;
    include conf.d/include/proxy.conf;
}',
    modified_on = datetime('now')
WHERE id = 35
  AND domain_names = '["crm-home.172906573.xyz"]'
  AND is_deleted = 0;

-- 防止错误环境或代理主机编号变化时静默修改其他站点；应用脚本必须校验 changes() = 1。
SELECT changes() AS updated_proxy_hosts;
