module.exports = {
  apps: [
    {
      name: 'model_manager',
      cwd: __dirname,
      script: './start_model_manager.sh',
      interpreter: 'none',
      exec_mode: 'fork',
      instances: 1,
      autorestart: true,
      max_restarts: 20,
      restart_delay: 2000,
      min_uptime: '10s',
      time: true,
      out_file: './logs/model_manager.out.log',
      error_file: './logs/model_manager.err.log',
      merge_logs: true,
      env: {
        MODEL_MANAGER_HTTP_HOST: process.env.MODEL_MANAGER_HTTP_HOST || '0.0.0.0',
        MODEL_MANAGER_HTTP_PORT: process.env.MODEL_MANAGER_HTTP_PORT || '18088',
        MODEL_MANAGER_GRPC_HOST: '0.0.0.0',
        MODEL_MANAGER_GRPC_PORT: '50061',
        MODEL_MANAGER_TOKEN_TTL: '43200',
        MODEL_MANAGER_WATCH_ENABLED: '1',
        MODEL_MANAGER_WATCH_INTERVAL: '5',
        MODEL_MANAGER_WATCH_DEBOUNCE: '2'
      }
    }
  ]
};
