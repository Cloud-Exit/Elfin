[Unit]
Description=Elfin offline survival companion
After=network.target docker.service

[Service]
Type=simple
User=__USER__
Group=render
WorkingDirectory=__ELFIN_DIR__
EnvironmentFile=__ELFIN_DIR__/.env
ExecStartPre=/bin/bash -c '\
  . __ELFIN_DIR__/.env 2>/dev/null || true; \
  cd __ELFIN_DIR__; \
  if [ "$TARGET" = "rockchip" ]; then \
    docker compose up -d llama-embed qdrant kiwix; \
    sg render -c "bash scripts/rk_llama_cpp.sh server-bg"; \
  else \
    docker compose up -d llama-server llama-embed qdrant kiwix; \
  fi; \
  for i in $(seq 1 300); do curl -sf http://localhost:8081/health >/dev/null && break; sleep 2; done; \
  for i in $(seq 1 60); do curl -sf http://localhost:8082/health >/dev/null && break; sleep 1; done; \
  for i in $(seq 1 60); do curl -sf http://localhost:6333/healthz >/dev/null && break; sleep 1; done'
ExecStart=__BUN_PATH__ run src/backend/server.ts
ExecStopPost=/bin/bash -c '. __ELFIN_DIR__/.env 2>/dev/null || true; cd __ELFIN_DIR__; if [ "$TARGET" = "rockchip" ]; then bash scripts/rk_llama_cpp.sh stop 2>/dev/null || true; fi'
TimeoutStartSec=900
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
