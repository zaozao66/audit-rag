# 配置说明

## 配置文件说明

为了保护敏感信息（如 API 密钥），项目中不包含实际的配置文件。

## 如何配置项目

1. 复制示例配置文件：
   ```bash
   cp config.example.json config.json
   ```

2. 编辑 `config.json` 文件，替换其中的占位符：
   - 将 `your_development_api_key_here` 替换为您的开发环境 API 密钥
   - 将 `your_production_api_key_here` 替换为您的生产环境 API 密钥

3. 根据需要修改其他配置项

## 配置文件结构

配置文件包含以下主要部分：

- `development`: 开发环境配置
- `production`: 生产环境配置
- `default_env`: 默认使用的环境
- `current_env`: 当前运行的环境

新增语音配置（位于 `development/production` 下）：

- `audio.script`: 播报文案生成配置
- `audio.tts`: TTS引擎、模型、音色、缓存与超时配置

示例（节选）：

```json
{
  "audio": {
    "script": {
      "max_chars": 1200
    },
    "tts": {
      "provider": "qwen",
      "model": "qwen3-tts-flash-2025-11-27",
      "default_voice": "Cherry",
      "default_format": "mp3",
      "default_sample_rate": 24000,
      "request_timeout": 20,
      "output_dir": "./data/audio_cache",
      "public_base_path": "/v1/audio/files",
      "cache_ttl_hours": 48,
      "cache_max_disk_mb": 2048,
      "providers": {
        "qwen": {
          "endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1",
          "api_key": "YOUR_API_KEY",
          "model": "qwen3-tts-flash-2025-11-27"
        }
      }
    }
  }
}
```

## 环境选择

程序会根据配置文件中的 `current_env` 字段或环境变量来决定使用哪套配置。

## 注意事项

- 请勿将 `config.json` 文件提交到版本控制系统
- 该文件已添加到 `.gitignore` 中
- 所有敏感信息（如 API 密钥）都应存储在配置文件中，而不是代码中
- 实时TTS需安装依赖：`websocket-client>=1.8.0`
- `qwen3-tts-flash-realtime-2025-11-27` 仅用于实时接口 `/v1/audio/speech/realtime`
- 非实时接口 `/v1/audio/speech` 推荐使用 `qwen3-tts-flash-2025-11-27`
