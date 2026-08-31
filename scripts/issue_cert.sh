#!/bin/bash
# Автовыпуск сертификата app.raebae.fun + включение SSL на 8445 + рестарт бота.
# Запускается в фоне; завершается после успешной настройки.
set -u
DOMAIN=app.raebae.fun
WEBROOT=/opt/schedule-bot/webapp

# не дублировать запуск
[ -f /tmp/issue_cert.lock ] && exit 0
touch /tmp/issue_cert.lock
trap 'rm -f /tmp/issue_cert.lock' EXIT

echo "$(date -Is) старт, жду DNS (проверка каждые 10 мин, до 60 попыток)"
for i in $(seq 1 60); do
  if dig +short "$DOMAIN" @8.8.8.8 | grep -q "144.31.207.159"; then
    echo "$(date -Is) DNS резолвится (попытка $i), пробую certbot"
    break
  fi
  echo "$(date -Is) попытка $i: DNS ещё не виден"
  sleep 600
done

certbot certonly --webroot -w "$WEBROOT" -d "$DOMAIN" \
  --non-interactive --agree-tos --register-unsafely-without-email \
  --keep-until-expiring || { echo "$(date -Is) certbot FAILED"; exit 1; }

cat > /etc/nginx/sites-available/schedule-app << 'NGINX'
server {
    listen 80;
    server_name app.raebae.fun;

    root /opt/schedule-bot/webapp;
    index index.html;

    location /.well-known/acme-challenge/ { root /opt/schedule-bot/webapp; }

    location / { return 301 https://app.raebae.fun:8445$request_uri; }
}

server {
    listen 8445 ssl;
    server_name app.raebae.fun;

    ssl_certificate     /etc/letsencrypt/live/app.raebae.fun/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/app.raebae.fun/privkey.pem;

    root /opt/schedule-bot/webapp;
    index index.html;

    gzip on;
    gzip_types text/css application/javascript application/json image/svg+xml;

    location /data/ {
        alias /opt/schedule-bot/data/;
        add_header Cache-Control "no-store";
    }

    location / {
        add_header Cache-Control "no-cache";
        try_files $uri $uri/ =404;
    }

    location ~* \.(css|js|png|svg|ico)$ {
        expires 1h;
        add_header Cache-Control "public, max-age=3600";
    }
}
NGINX
nginx -t && systemctl reload nginx

# обновить WEBAPP_URL в .env, если ещё не задан
if ! grep -q "^WEBAPP_URL=https" /opt/schedule-bot/.env; then
  sed -i "s|^WEBAPP_URL=.*|WEBAPP_URL=https://app.raebae.fun:8445|" /opt/schedule-bot/.env
fi
systemctl restart schedule-bot
echo "$(date -Is) ГОТОВО: https://app.raebae.fun:8445"
